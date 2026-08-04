"""Reglas de validacion previa de ordenes (T35).

Aqui vive la decision de alcance mas importante del proyecto en materia de
operativa: la aplicacion NO ofrece apalancamiento, asi que una orden se
valida contra el EFECTIVO y no contra el poder de compra.

Eso hace que esta capa sea mas estricta que el propio broker, y no al
reves. Medido en DUN684545 el 04/08/2026: comprar 10 AMZN cuesta 2.421 EUR
y el margen inicial que exige IB es de 797, un 33 %. IB dejaria comprar
tres veces mas de lo que hay en caja. Por eso whatIfOrder no puede ser el
validador: informa del margen, que es exactamente lo que no queremos usar.

El calculo esta en evaluar_orden(), que es una funcion pura: recibe datos
ya obtenidos y no habla con IB. Asi las reglas se prueban con pytest sin
Gateway levantado, igual que el mapper.

Reglas de esta capa:
  - no importa fastapi (no lanza HTTPException)
  - no importa ib_async (RNF-08)
"""

from app.broker import ib_gateway
from app.models.order import BrokerPreview, OrderRequest, OrderValidation
from app.models.quote import Quote

# Colchon sobre el precio de referencia en las ordenes de mercado. Una
# orden de mercado no tiene precio cierto: se ejecuta a lo que haya cuando
# llegue, y con datos retrasados 15 minutos el ultimo precio conocido es
# viejo. Sin colchon, una orden aprobada justo en el limite podria
# ejecutarse por encima y dejar la cuenta en descubierto. Un 2 % es una
# eleccion conservadora y arbitraria, y se documenta como tal.
COLCHON_MERCADO = 0.02

# En las limitadas no se aplica: una compra limitada se ejecuta al precio
# limite o mejor, nunca peor, asi que el coste maximo ya es exacto.
COLCHON_LIMITE = 0.0

# Comision de reserva cuando IB no la da (la manda como centinela en las
# ordenes que rechaza). Es el minimo real de IB para acciones de EE.UU.
# Suponer cero seria aprobar ordenes que dejan la caja en negativo por
# poco; suponer el minimo se equivoca del lado seguro.
COMISION_DE_RESERVA = 1.0


async def validate_order(req: OrderRequest) -> OrderValidation:
    """Comprueba una orden contra el broker y contra nuestras reglas."""
    preview = await ib_gateway.preview_order(req)
    quote = await ib_gateway.get_quote(req.con_id)
    base_currency, rates = await ib_gateway.get_fx_rates()
    account = await ib_gateway.get_account_summary()
    en_cartera = await ib_gateway.get_position_quantity(req.con_id)

    return evaluar_orden(
        req=req,
        preview=preview,
        quote=quote,
        base_currency=base_currency,
        rates=rates,
        cash=account.total_cash,
        position_quantity=en_cartera,
    )


def _precio_de_referencia(req: OrderRequest, quote: Quote):
    """Elige con que precio se calcula el coste, y de donde sale.

    En una limitada el precio lo pone el usuario y es cierto. En una de
    mercado hay que estimarlo, y se prefiere el lado del libro contra el
    que se cruzaria la orden: el ask al comprar y el bid al vender. Es el
    peor caso razonable, que es el que hay que usar al comprobar si el
    dinero llega.
    """
    if req.order_type == "LMT":
        return req.limit_price, "limite"

    preferido = quote.ask if req.action == "BUY" else quote.bid
    for valor, fuente in ((preferido, "ask" if req.action == "BUY" else "bid"),
                          (quote.last, "last"),
                          (quote.close, "close")):
        if valor is not None and valor > 0:
            return valor, fuente
    return None, ""


def _a_base(importe: float, divisa: str, base: str, rates: dict[str, float]) -> float | None:
    """Convierte a divisa base. None si no hay tipo de cambio."""
    if not divisa or divisa == base:
        return importe
    tipo = rates.get(divisa)
    if tipo is None:
        return None
    return importe * tipo


def evaluar_orden(
    req: OrderRequest,
    preview: BrokerPreview,
    quote: Quote,
    base_currency: str,
    rates: dict[str, float],
    cash: float,
    position_quantity: float,
) -> OrderValidation:
    """Aplica las reglas. Funcion pura: no habla con IB ni con HTTP."""
    motivos: list[str] = []
    avisos: list[str] = []

    divisa = preview.currency or quote.currency or ""
    simbolo = preview.symbol or quote.symbol or ""

    # ---- Precio de referencia
    precio, fuente = _precio_de_referencia(req, quote)
    colchon = COLCHON_LIMITE if req.order_type == "LMT" else COLCHON_MERCADO

    if precio is None:
        motivos.append(
            "No hay precio disponible para este valor, asi que no se puede "
            "estimar el coste. Prueba con una orden limitada."
        )
    elif fuente == "close":
        avisos.append(
            "El mercado esta cerrado: el calculo usa el cierre de la sesion "
            "anterior y el precio de ejecucion puede diferir bastante."
        )
    elif quote.delayed:
        avisos.append(
            "El precio es retrasado unos 15 minutos. Se aplica un colchon "
            f"del {colchon:.0%} sobre el precio de referencia."
            if colchon else
            "El precio mostrado es retrasado unos 15 minutos."
        )

    # ---- Tipo de cambio
    fx = 1.0 if (not divisa or divisa == base_currency) else rates.get(divisa, 0.0)
    if divisa and divisa != base_currency and not fx:
        motivos.append(
            f"No hay tipo de cambio de {divisa} a {base_currency}, asi que no "
            "se puede comprobar si el efectivo alcanza."
        )
        fx = 1.0

    # ---- Coste
    coste = 0.0
    coste_base = 0.0
    if precio is not None:
        coste = req.quantity * precio * (1 + colchon)
        coste_base = _a_base(coste, divisa, base_currency, rates) or coste

    # ---- Comision
    comision = preview.commission
    divisa_comision = preview.commission_currency or divisa
    if comision is None:
        comision = COMISION_DE_RESERVA
        divisa_comision = divisa
        avisos.append(
            f"IB no ha devuelto comision, asi que se estima el minimo de "
            f"{COMISION_DE_RESERVA:.2f} {divisa_comision}."
        )
    comision_base = _a_base(comision, divisa_comision, base_currency, rates) or 0.0

    total_base = coste_base + comision_base

    # ---- Reglas propias
    efectivo_despues = cash
    if req.action == "BUY":
        if precio is not None and total_base > cash:
            motivos.append(
                f"El coste estimado ({total_base:,.2f} {base_currency}) supera "
                f"el efectivo disponible ({cash:,.2f} {base_currency}). La "
                "aplicacion no opera a credito, asi que se valida contra el "
                "efectivo y no contra el poder de compra."
            )
        efectivo_despues = cash - total_base
    else:
        if req.quantity > position_quantity:
            tienes = (
                f"solo tienes {position_quantity:,.0f}"
                if position_quantity > 0
                else "no tienes ninguno"
            )
            motivos.append(
                f"Quieres vender {req.quantity:,.0f} titulos de {simbolo} y "
                f"{tienes}. La aplicacion no permite vender a descubierto."
            )
        # Una venta ingresa dinero; la comision se descuenta del ingreso.
        efectivo_despues = cash + coste_base - comision_base

    # ---- Lo que diga IB
    if not preview.accepted_by_broker:
        motivos.append(
            preview.broker_message
            or "Interactive Brokers ha rechazado la comprobacion previa."
        )
    if preview.warning_text:
        avisos.append(preview.warning_text)

    return OrderValidation(
        accepted=not motivos,
        reasons=motivos,
        warnings=avisos,
        con_id=req.con_id,
        symbol=simbolo,
        action=req.action,
        order_type=req.order_type,
        quantity=req.quantity,
        limit_price=req.limit_price,
        reference_price=precio,
        price_source=fuente,
        buffer_pct=colchon,
        currency=divisa,
        base_currency=base_currency,
        fx_rate=fx,
        estimated_cost=coste,
        estimated_cost_base=coste_base,
        commission=comision,
        commission_currency=divisa_comision,
        commission_base=comision_base,
        total_base=total_base,
        cash_available=cash,
        cash_after=efectivo_despues,
        position_quantity=position_quantity,
        broker=preview,
    )