"""Traduccion de objetos ib_async a modelos propios.

Este fichero es lo que hace que RNF-08 signifique algo. Si el broker
devolviera PortfolioItem o AccountValue hacia arriba, el acoplamiento
seguiria existiendo, solo que escondido. Aqui se corta.

Todo el conocimiento sobre la forma exacta de los datos de IB vive aqui.
Si ib_async renombra un campo, se toca este fichero y ninguno mas.

Trampa verificada el 03/08/2026: el coste medio se llama avgCost en los
objetos Position (canal reqPositions) y averageCost en los PortfolioItem
(canal reqAccountUpdates). Usamos los segundos.

Divisas, verificado el 03/08/2026 con scripts/sondea_divisas.py: los tipos
de cambio llegan en accountValues() como etiquetas ExchangeRate, una por
divisa, y NO aparecen en accountSummary(). La divisa base se lee del campo
currency de la etiqueta NetLiquidation. Comprobacion que valida el tipo:
1.010.294,27 EUR de efectivo mas -142.079,42 USD por 0,8693308 da
886.780,25, que es exactamente el TotalCashValue que reporta IB.
"""

from app.models.account import AccountSummary
from app.models.portfolio import Portfolio, Position
from app.models.order import BrokerPreview, OrderResult
import math
from datetime import datetime, timezone
from app.models.instrument import Instrument
from app.models.quote import Quote
from app.models.price_history import PriceHistory, PricePoint
from app.models.execution import Execution, ExecutionHistory
from app.config import settings

# IB usa esta pseudodivisa para las filas ya consolidadas. No es una divisa
# real y nunca debe entrar en el diccionario de tipos de cambio.
_PSEUDO = "BASE"


def _to_float(value, default: float = 0.0) -> float:
    """IB devuelve varios importes como cadena, y a veces vacios."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def account_values_to_fx(values) -> tuple[str, dict[str, float]]:
    """Extrae la divisa base y los tipos de cambio de accountValues().

    Devuelve una tupla (divisa_base, {divisa: factor_a_base}). El factor
    multiplica: importe_en_divisa * factor = importe_en_base.

    La divisa base sale del currency de NetLiquidation. Si por lo que sea
    no viniera, se deduce de cual es la divisa cuyo tipo de cambio es 1.
    """
    base = ""
    rates: dict[str, float] = {}

    for v in values:
        divisa = v.currency or ""
        if not divisa or divisa == _PSEUDO:
            continue
        if v.tag == "ExchangeRate":
            rates[divisa] = _to_float(v.value, 1.0)
        elif v.tag == "NetLiquidation":
            base = divisa

    if not base:
        base = next((d for d, r in rates.items() if r == 1.0), "")

    return base, rates


def portfolio_item_to_position(
    item,
    base_currency: str = "",
    rates: dict[str, float] | None = None,
) -> Position:
    """Convierte un PortfolioItem de IB en una Position propia.

    Sin base_currency ni rates, los importes en divisa base coinciden con
    los nativos y el tipo de cambio es 1. Es el comportamiento correcto
    para una cuenta de divisa unica.
    """
    rates = rates or {}
    contract = item.contract
    divisa = contract.currency

    tipo = 1.0 if divisa == base_currency else rates.get(divisa, 1.0)

    cantidad = _to_float(item.position)
    coste_medio = _to_float(item.averageCost)
    valor = _to_float(item.marketValue)
    latente = _to_float(item.unrealizedPNL)

    return Position(
        symbol=contract.symbol,
        sec_type=contract.secType,
        currency=divisa,
        exchange=contract.primaryExchange or contract.exchange or "",
        quantity=cantidad,
        avg_cost=coste_medio,
        market_price=_to_float(item.marketPrice),
        market_value=valor,
        unrealized_pnl=latente,
        realized_pnl=_to_float(item.realizedPNL),
        fx_rate=tipo,
        market_value_base=valor * tipo,
        cost_base=coste_medio * cantidad * tipo,
        unrealized_pnl_base=latente * tipo,
    )


def portfolio_items_to_portfolio(
    items,
    account_id: str,
    base_currency: str = "",
    rates: dict[str, float] | None = None,
) -> Portfolio:
    """Convierte la lista de PortfolioItem en una Portfolio con totales.

    Los totales se calculan sobre los importes ya convertidos a divisa
    base. Sumar dolares con euros produce un numero sin significado, asi
    que la conversion va antes de la suma y no despues.

    Los totales son suma directa de datos que ya vienen de IB, por eso se
    calculan aqui. Cualquier metrica con criterio propio (volatilidad,
    VaR, concentracion) NO va aqui: va en services/risk_service.py.
    """
    positions = [portfolio_item_to_position(i, base_currency, rates) for i in items]
    return Portfolio(
        account_id=account_id,
        base_currency=base_currency,
        positions=positions,
        total_market_value=sum(p.market_value_base for p in positions),
        total_cost=sum(p.cost_base for p in positions),
        total_unrealized_pnl=sum(p.unrealized_pnl_base for p in positions),
    )


# Etiquetas del accountSummary de IB que alimentan AccountSummary.
_TAGS = {
    "NetLiquidation": "net_liquidation",
    "TotalCashValue": "total_cash",
    "AvailableFunds": "available_funds",
    "BuyingPower": "buying_power",
}


def account_values_to_summary(values, account_id: str) -> AccountSummary:
    """Convierte la lista plana de AccountValue en un AccountSummary.

    IB entrega el resumen como pares tag/valor, asi que primero lo
    volcamos a diccionario y luego leemos las etiquetas que interesan.
    """
    datos = {campo: 0.0 for campo in _TAGS.values()}
    currency = "USD"

    for v in values:
        if v.tag in _TAGS:
            datos[_TAGS[v.tag]] = _to_float(v.value)
            if v.currency:
                currency = v.currency

    return AccountSummary(account_id=account_id, currency=currency, **datos)

# ---------------------------------------------------------------------
# Instrumentos (T33)
# ---------------------------------------------------------------------

# Mercados que devuelve reqMatchingSymbols y que no son negociables.
# Verificado el 04/08/2026 buscando "Iberdrola": IBE.DUM, IBE.CASH, IBE.RTS
# y otros diez aparecen en CORPACT, que es donde IB coloca los artefactos
# de operaciones societarias (ampliaciones, dividendos en especie, derechos).
# VALUE contiene lineas de valoracion de instrumentos ya extinguidos y
# DOLLR4LOT es un mercado de lotes sueltos. Ninguno se puede comprar, asi
# que ofrecerlos en el buscador seria ofrecer algo que la orden rechazaria.
_MERCADOS_NO_NEGOCIABLES = frozenset({"CORPACT", "VALUE", "DOLLR4LOT"})


def contract_descriptions_to_instruments(descriptions) -> list[Instrument]:
    """Convierte la respuesta de reqMatchingSymbols en instrumentos propios.

    Filtra a secType STK por decision de alcance: la cartera es de acciones
    y ETFs, y ambos llegan de IB como STK. Con ello desaparecen los BOND
    (que ademas vienen sin simbolo y con conId -1), los IND y los FUND que
    devuelve la busqueda.
    """
    salida: list[Instrument] = []
    for desc in descriptions:
        c = getattr(desc, "contract", None)
        if c is None:
            continue
        if getattr(c, "secType", "") != "STK":
            continue
        # Restriccion de divisa (decision de alcance, configurable via
        # IB_TRADING_CURRENCY). El mismo ticker cotiza en varias plazas y
        # divisas —"AMZN" aparece en pesos, francos y dolares canadienses—
        # y operar en varias meteria riesgo de cambio en cada orden. Se
        # limita a una unica divisa operativa (USD por defecto) para que
        # todo lo que el buscador ofrezca se pueda pagar con el mismo
        # efectivo. No es una limitacion tecnica: es alcance deliberado.
        if getattr(c, "currency", "") != settings.IB_TRADING_CURRENCY:
            continue
        if not getattr(c, "symbol", "") or getattr(c, "conId", 0) <= 0:
            continue
        if (getattr(c, "primaryExchange", "") or "") in _MERCADOS_NO_NEGOCIABLES:
            continue

        salida.append(
            Instrument(
                con_id=c.conId,
                symbol=c.symbol,
                # description es el nombre del emisor y viene ya en la
                # busqueda. Se usa getattr porque es un campo que la API de
                # TWS anadio tarde: si un Gateway antiguo no lo mandara, el
                # buscador seguiria funcionando con el ticker a secas.
                name=getattr(c, "description", "") or "",
                sec_type=c.secType,
                currency=getattr(c, "currency", "") or "",
                exchange=getattr(c, "primaryExchange", "") or "",
            )
        )
    return salida


# ---------------------------------------------------------------------
# Cotizaciones (T34)
# ---------------------------------------------------------------------


def _precio(valor) -> float | None:
    """Traduce a None lo que IB usa para decir "no hay dato".

    Son dos cosas distintas y hay que cazar las dos, verificado el
    04/08/2026 en el propio ticker: IBDefaults(emptyPrice=-1, unset=nan).
    Un nan colado en un JSON lo rompe, y un -1 se pinta como un precio
    negativo perfectamente creible. Ninguno de los dos puede salir de aqui.
    """
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or v < 0:
        return None
    return v


def ticker_to_quote(ticker) -> Quote:
    """Convierte un Ticker de ib_async en una Quote propia.

    ib_async ya normaliza los ticks retrasados (tipos 66-76 de la API) a los
    campos last, bid, ask y close de siempre, verificado el 04/08/2026. Este
    mapper no necesita saber que el dato venia retrasado; solo lo anota.

    La variacion se calcula aqui y no en Angular por el mismo criterio que
    los totales de cartera: es un dato derivado que el backend puede razonar
    y el frontend solo pintaria.
    """
    contrato = getattr(ticker, "contract", None)

    last = _precio(getattr(ticker, "last", None))
    close = _precio(getattr(ticker, "close", None))

    change = None
    change_pct = None
    if last is not None and close is not None and close != 0:
        change = last - close
        change_pct = (change / close) * 100

    tipo = int(getattr(ticker, "marketDataType", 3) or 3)

    # delayedLastTimestamp es el momento al que corresponde el precio, que
    # no es el momento en que lo recibimos. Si no viniera, se cae a time.
    momento = getattr(ticker, "delayedLastTimestamp", None) or getattr(ticker, "time", None)

    return Quote(
        con_id=getattr(contrato, "conId", 0) or 0,
        symbol=getattr(contrato, "symbol", "") or "",
        currency=getattr(contrato, "currency", "") or "",
        exchange=getattr(contrato, "primaryExchange", "") or getattr(contrato, "exchange", "") or "",
        last=last,
        bid=_precio(getattr(ticker, "bid", None)),
        ask=_precio(getattr(ticker, "ask", None)),
        close=close,
        volume=_precio(getattr(ticker, "volume", None)),
        change=change,
        change_pct=change_pct,
        delayed=tipo in (3, 4),
        market_data_type=tipo,
        quote_time=momento,
        received_at=datetime.now(timezone.utc),
    )

# ---------------------------------------------------------------------
# Ordenes (T35)
# ---------------------------------------------------------------------

# Cualquier valor por encima de esto no es un importe: es el centinela con
# que IB dice "sin dato" (1.7976931348623157e+308, el maximo de un double).
# Verificado el 04/08/2026: sale siempre en minCommission y maxCommission,
# y tambien en commission cuando la orden se rechaza.
_CENTINELA = 1e300

# Errores de IB que significan que la orden no se aceptaria. El 201 es el
# rechazo por margen, que es el que devuelve DUN684545 al pedir mas de lo
# que cabe. Los demas cubren contrato mal resuelto (200), precio que no
# respeta el minTick (110) y validaciones del servidor (321).
_CODIGOS_RECHAZO = frozenset({110, 200, 201, 202, 203, 321, 383, 481})


def _importe(valor) -> float | None:
    """Traduce a None lo que IB manda como "sin dato" en OrderState.

    No se reutiliza _precio a proposito, aunque se parezcan: _precio
    descarta los negativos porque un precio negativo no existe, pero aqui
    los negativos son datos legitimos. equityWithLoanChange vale -1.14 en
    una compra normal, y pasarlo por _precio lo convertiria en None.
    """
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or abs(v) > _CENTINELA:
        return None
    return v


def order_state_to_preview(estado, contrato, errores) -> BrokerPreview:
    """Convierte la respuesta de whatIfOrder en un modelo propio.

    errores es la lista de (codigo, mensaje) que IB emitio durante la
    llamada. Es imprescindible: el campo status del OrderState vale
    'PreSubmitted' tanto en una orden aceptada como en una rechazada,
    verificado el 04/08/2026 comparando una compra de 10 AMZN con una de
    100.000. Lo unico que las distingue es el error 201, que viaja por el
    canal de eventos y no por el objeto.
    """
    rechazos = [(c, m) for c, m in (errores or []) if c in _CODIGOS_RECHAZO]

    datos = {
        "con_id": getattr(contrato, "conId", 0) or 0,
        "symbol": getattr(contrato, "symbol", "") or "",
        "currency": getattr(contrato, "currency", "") or "",
        "exchange": getattr(contrato, "exchange", "") or "",
    }

    if estado is None and not rechazos:
        # Ni respuesta ni error: el Gateway no contesto. No es un si.
        return BrokerPreview(
            accepted_by_broker=False,
            broker_message="IB Gateway no respondio a la comprobacion previa",
            **datos,
        )

    codigo, mensaje = rechazos[0] if rechazos else (None, "")

    return BrokerPreview(
        accepted_by_broker=not rechazos,
        broker_status=getattr(estado, "status", "") or "",
        broker_message=mensaje,
        error_code=codigo,
        warning_text=getattr(estado, "warningText", "") or "",
        commission=_importe(getattr(estado, "commission", None)),
        commission_currency=getattr(estado, "commissionCurrency", "") or "",
        init_margin_change=_importe(getattr(estado, "initMarginChange", None)),
        maint_margin_change=_importe(getattr(estado, "maintMarginChange", None)),
        equity_with_loan_change=_importe(getattr(estado, "equityWithLoanChange", None)),
        **datos,
    )


# ---------------------------------------------------------------------
# Envio de ordenes (T36)
# ---------------------------------------------------------------------

# Traduccion del status crudo de IB al vocabulario de la aplicacion.
# Verificado el 04/08/2026 con scripts/sondea_ordenes_envio.py contra
# DUN684545: una MKT que cruza termina en 'Filled'; un rechazo por margen
# deja la orden en 'Inactive' (no en 'PreSubmitted', como pasaba con
# whatIfOrder); una cancelacion recorre PendingCancel y acaba en
# 'Cancelled'. El resto de estados son fases de una orden todavia viva.
_EJECUTADA = frozenset({"Filled"})
_RECHAZADA = frozenset({"Inactive", "ValidationError"})
_CANCELADA = frozenset({"Cancelled", "ApiCancelled", "PendingCancel"})


def estado_de_orden(status: str) -> str:
    """Reduce el status de IB a: ejecutada, activa, rechazada o cancelada.

    Funcion pura y sin dependencias: es el nucleo que se prueba con pytest
    sin Gateway. Un estado desconocido se trata como 'activa' a proposito;
    equivocarse hacia "sigue en el mercado" es menos danino que dar por
    ejecutada o rechazada una orden que no lo esta.
    """
    if status in _EJECUTADA:
        return "ejecutada"
    if status in _RECHAZADA:
        return "rechazada"
    if status in _CANCELADA:
        return "cancelada"
    return "activa"


def _limpiar_mensaje(mensaje: str) -> str:
    """IB incrusta <br> en los mensajes de rechazo por margen.

    Verificado el 04/08/2026: el texto del error 201 llega con saltos de
    linea HTML. Se quitan para que se lea igual en un JSON que en un log.
    """
    return " ".join((mensaje or "").replace("<br>", " ").split())


def trade_to_result(trade, error_code=None, error_message="") -> OrderResult:
    """Convierte un Trade de ib_async en un OrderResult propio.

    error_code y error_message vienen de fuera porque el motivo del rechazo
    NO esta en el Trade: verificado el 04/08/2026, trade.log anota el paso a
    Inactive con errorCode 0 y mensaje vacio, y el 201 con el texto real
    viaja por errorEvent. Sin ese dato, una orden rechazada se veria sin
    explicacion. Duck typing en todo el cuerpo (getattr) para que las
    pruebas puedan pasar objetos simulados sin ib_async.
    """
    orden = getattr(trade, "order", None)
    estado_ib = getattr(trade, "orderStatus", None)
    contrato = getattr(trade, "contract", None)
    status = getattr(estado_ib, "status", "") or ""

    # Comision real: se suma la de cada ejecucion. En una orden viva no hay
    # fills todavia y queda en None, que es lo correcto: aun no se ha pagado.
    # Trampa verificada el 04/08/2026 con una venta real: ib_async crea el
    # Fill con un CommissionReport VACIO (commission=0.0, currency='') y lo
    # rellena cuando llega commissionReportEvent, que puede ser un instante
    # despues. Un report sin divisa es un report que IB aun no ha enviado,
    # no una comision de cero: se ignora y la comision queda en None hasta
    # que el GET de seguimiento la vea rellena.
    comision = None
    divisa_comision = ""
    for f in getattr(trade, "fills", None) or []:
        report = getattr(f, "commissionReport", None)
        if not (getattr(report, "currency", "") or ""):
            continue
        parcial = _importe(getattr(report, "commission", None))
        if parcial is not None:
            comision = (comision or 0.0) + parcial
            divisa_comision = getattr(report, "currency", "") or divisa_comision

    avg = _importe(getattr(estado_ib, "avgFillPrice", None))
    if avg is not None and avg <= 0:
        avg = None  # 0.0 es "sin ejecucion", no un precio

    tipo = getattr(orden, "orderType", "") or ""
    limite = _importe(getattr(orden, "lmtPrice", None)) if tipo == "LMT" else None

    return OrderResult(
        estado=estado_de_orden(status),
        order_id=int(getattr(orden, "orderId", 0) or 0),
        perm_id=int(getattr(orden, "permId", 0) or 0),
        con_id=int(getattr(contrato, "conId", 0) or 0),
        symbol=getattr(contrato, "symbol", "") or "",
        action=getattr(orden, "action", "") or "",
        order_type=tipo,
        quantity=_to_float(getattr(orden, "totalQuantity", 0.0)),
        limit_price=limite,
        filled_quantity=_to_float(getattr(estado_ib, "filled", 0.0)),
        remaining_quantity=_to_float(getattr(estado_ib, "remaining", 0.0)),
        avg_fill_price=avg,
        commission=comision,
        commission_currency=divisa_comision,
        broker_status=status,
        broker_message=_limpiar_mensaje(error_message),
        error_code=error_code,
        submitted_at=datetime.now(timezone.utc),
    )

# ---------------------------------------------------------------------
# Historico de precios (Fase 5)
# ---------------------------------------------------------------------


def bars_to_price_history(con_id: int, barras) -> PriceHistory:
    """Convierte las BarData de reqHistoricalData en un PriceHistory propio.

    De cada barra solo se conservan date y close: son los dos campos que el
    modulo de riesgo consume. Verificado el 07/08/2026 con
    scripts/sondea_historico.py que 'date' llega ya como datetime.date con
    barSize '1 day', asi que no se parsea nada; se copia tal cual.

    A diferencia de _precio y _importe, aqui no hay que cazar centinelas: el
    cierre historico de una sesion cerrada es siempre un numero real. Aun
    asi se descarta por seguridad cualquier barra cuyo close no sea > 0, que
    solo podria pasar con datos corruptos: un cierre de cero o negativo
    romperia el logaritmo de los rendimientos.

    El orden de IB (mas antiguo primero) se respeta sin reordenar: los
    rendimientos se calculan sobre pares consecutivos y dependen de el.
    """
    puntos = []
    for b in barras or []:
        cierre = getattr(b, "close", None)
        try:
            cierre = float(cierre)
        except (TypeError, ValueError):
            continue
        if cierre <= 0:
            continue
        puntos.append(PricePoint(date=b.date, close=cierre))

    return PriceHistory(con_id=con_id, points=puntos)


# ---------------------------------------------------------------------
# Historico de ejecuciones (T38)
# ---------------------------------------------------------------------

# IB nombra los lados de una ejecucion distinto que los de una orden:
# 'BOT'/'SLD' en Execution frente a 'BUY'/'SELL' en Order. Verificado el
# 07/08/2026 con sondea_ejecuciones_hoy.py. Se traduce aqui para que el
# historico y el formulario de ordenes hablen el mismo idioma; si no, la
# misma operacion apareceria como 'BUY' al enviarla y como 'BOT' al
# consultarla, y el frontend tendria que conocer las dos convenciones.
_LADOS = {"BOT": "BUY", "SLD": "SELL"}


def _lado_de_ejecucion(side: str) -> str:
    """Traduce el lado de IB al nuestro, o lo devuelve tal cual si no lo conoce.

    Devolver el original en vez de fallar es deliberado: un lado
    desconocido (IB usa otros codigos en productos que no operamos) no
    debe tumbar la consulta del historico entero.
    """
    return _LADOS.get(side, side)


def _comision_de_fill(report) -> tuple[float | None, str]:
    """Comision de una ejecucion, o None si todavia no ha llegado.

    Es la misma leccion de T36, y aqui muerde igual: ib_async construye el
    CommissionReport VACIO (commission=0.0, currency='') y lo rellena
    despues, cuando dispara commissionReportEvent. Verificado el
    07/08/2026: tres segundos despues de una ejecucion completada seguia
    vacio.

    Por eso la divisa, y no el importe, es lo que decide. Un report sin
    divisa es un report sin rellenar, y tomar su 0.0 por bueno seria
    afirmar que la operacion no costo nada. None significa "no se sabe",
    que es distinto de cero y es lo unico honesto que se puede decir.
    """
    if report is None:
        return None, ""
    divisa = getattr(report, "currency", "") or ""
    if not divisa:
        return None, ""
    return _to_float(getattr(report, "commission", 0.0)), divisa


def fill_to_execution(fill) -> Execution:
    """Convierte un Fill de ib_async en una Execution propia.

    El Fill agrupa tres cosas: el contrato, la ejecucion y el informe de
    comision. Se leen las tres aqui para que ningun objeto de ib_async
    salga del paquete broker (RNF-08).

    El sello de tiempo se deja EN UTC tal como llega. ib_async ya entrega
    execution.time como datetime con tzinfo=UTC, asi que no hay parseo ni
    conversion: localizar es cosa de quien pinta, no de quien registra.
    Guardar hora local en un libro de operaciones es el error clasico que
    se paga el dia del cambio de horario.
    """
    e = fill.execution
    c = fill.contract

    comision, divisa_comision = _comision_de_fill(
        getattr(fill, "commissionReport", None)
    )

    cantidad = _to_float(e.shares)
    precio = _to_float(e.price)

    return Execution(
        exec_id=e.execId,
        order_id=e.orderId,
        perm_id=e.permId,
        symbol=c.symbol,
        sec_type=getattr(c, "secType", ""),
        currency=getattr(c, "currency", ""),
        exchange=e.exchange or getattr(c, "exchange", ""),
        action=_lado_de_ejecucion(e.side),
        quantity=cantidad,
        price=precio,
        amount=cantidad * precio,
        commission=comision,
        commission_currency=divisa_comision,
        time=e.time,
        account_id=getattr(e, "acctNumber", ""),
    )


def fills_to_history(fills, account_id: str = "") -> ExecutionHistory:
    """Convierte la respuesta de reqExecutions en el historico del dia.

    Ordena de mas reciente a mas antigua, que es como se lee un historico:
    lo ultimo que ha pasado arriba. Ordenar aqui y no en el frontend
    permite que cualquier cliente reciba el mismo orden sin repetir la
    regla.

    La ventana se fija a 'current_day' porque es lo unico que el canal
    entrega (ver app/models/execution.py). No se deduce de los datos: una
    lista vacia no significa que la ventana sea otra.
    """
    ejecuciones = [fill_to_execution(f) for f in fills]
    ejecuciones.sort(key=lambda x: x.time, reverse=True)

    return ExecutionHistory(
        account_id=account_id,
        executions=ejecuciones,
        window="current_day",
        retrieved_at=datetime.now(timezone.utc),
    )
