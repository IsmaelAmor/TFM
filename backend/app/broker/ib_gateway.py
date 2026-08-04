"""Operaciones contra IB Gateway.

Unica puerta por la que entran datos de IB al proyecto. Cada funcion
recibe parametros simples y devuelve modelos propios, nunca objetos de
ib_async.

Cuando en T33-T40 anadas instrumentos, precios y ordenes, las operaciones
nuevas se anaden aqui, no en los servicios ni en los routers.
"""

import logging

from app.broker import mapper
from app.broker.ib_client import get_ib
from app.models.account import AccountSummary
from app.models.portfolio import Portfolio
import asyncio
from ib_async import Contract, LimitOrder, MarketOrder
from app.models.instrument import Instrument
from app.models.quote import Quote
from app.models.order import BrokerPreview, OrderRequest
from app.config import settings

logger = logging.getLogger(__name__)


def get_managed_accounts() -> list[str]:
    """Cuentas accesibles con la sesion actual."""
    return list(get_ib().managedAccounts())


def _default_account() -> str:
    cuentas = get_managed_accounts()
    return cuentas[0] if cuentas else ""


async def get_account_summary(account_id: str | None = None) -> AccountSummary:
    """Resumen economico de la cuenta."""
    cuenta = account_id or _default_account()
    values = await get_ib().accountSummaryAsync()
    return mapper.account_values_to_summary(values, cuenta)


async def get_portfolio(account_id: str | None = None) -> Portfolio:
    """Posiciones abiertas, ya valoradas por IB y convertidas a divisa base.

    Usa portfolio() y no positions(): el canal reqAccountUpdates trae
    marketPrice, marketValue, unrealizedPNL y realizedPNL, que
    reqPositions no da. Verificado contra DUN684545 el 03/08/2026.

    Los tipos de cambio se leen de accountValues() y no de
    accountSummary(): comprobado el 03/08/2026, accountSummary solo
    devuelve la divisa base y no incluye ninguna etiqueta ExchangeRate.
    accountValues() no es una llamada de red: lee el estado que el canal
    reqAccountUpdates ya mantiene en memoria, asi que no anade latencia.
    """
    cuenta = account_id or _default_account()
    ib = get_ib()

    base_currency, rates = mapper.account_values_to_fx(ib.accountValues(cuenta))
    if not base_currency:
        logger.warning("No se pudo determinar la divisa base de %s", cuenta)

    items = [i for i in ib.portfolio() if i.account == cuenta]
    return mapper.portfolio_items_to_portfolio(items, cuenta, base_currency, rates)

class InstrumentNotFound(Exception):
    """El conId solicitado no corresponde a ningun contrato de IB."""


async def search_instruments(query: str, limit: int = 20) -> list[Instrument]:
    """Busca instrumentos por ticker o por nombre de empresa.

    Usa reqMatchingSymbols y no reqContractDetails porque es el unico metodo
    de la API que acepta texto parcial y busca tambien por nombre: escribir
    "Iberdrola" devuelve IBE, y reqContractDetails habria exigido conocer ya
    el ticker exacto, que es justo lo que el usuario no sabe.

    Verificado el 04/08/2026: la respuesta ya incluye el nombre del emisor,
    asi que una sola llamada resuelve el buscador entero.

    IB limita este metodo a una peticion por segundo. No se protege aqui
    porque el buscador del frontend hara debounce; si en algun momento se
    llamara en bucle, este es el sitio donde pondriamos el limitador.
    """
    descripciones = await get_ib().reqMatchingSymbolsAsync(query)
    return mapper.contract_descriptions_to_instruments(descripciones or [])[:limit]


async def get_quote(con_id: int) -> Quote:
    """Ultimo precio conocido de un instrumento, identificado por conId.

    Por conId y no por ticker a proposito: "AMZN" corresponde a cinco
    cotizaciones distintas en cinco divisas, y pedir precio "de AMZN" no
    tendria una respuesta unica.

    Pide una foto (snapshot) y no un flujo continuo. Con datos retrasados el
    snapshot funciona, verificado el 04/08/2026, y ademas se cierra solo:
    un flujo habria que cancelarlo, y una cancelacion olvidada consume una
    de las lineas de datos de mercado de la cuenta hasta reiniciar.
    """
    ib = get_ib()

    # Primero resolvemos el contrato completo: reqMktData necesita saber en
    # que mercado pedir el precio, y el conId por si solo no lo dice.
    detalles = await ib.reqContractDetailsAsync(Contract(conId=con_id))
    if not detalles:
        raise InstrumentNotFound(f"No existe ningun contrato con conId {con_id}")

    detalle = detalles[0]
    contrato = detalle.contract

    # SMART es el enrutador de IB: elige el mercado con mejor ejecucion y es
    # el que tiene datos retrasados disponibles. Solo se usa si el contrato
    # lo admite; si no, se pide al mercado principal.
    if "SMART" in (getattr(detalle, "validExchanges", "") or ""):
        contrato.exchange = "SMART"
    elif not contrato.exchange:
        contrato.exchange = contrato.primaryExchange

    # reqTickersAsync pide el snapshot y espera a que IB lo de por completo.
    # El wait_for es la red de seguridad: si el mercado esta cerrado y el
    # snapshot no llega nunca, la peticion HTTP no puede quedarse colgada.
    try:
        tickers = await asyncio.wait_for(
            ib.reqTickersAsync(contrato), timeout=settings.IB_TIMEOUT
        )
    except asyncio.TimeoutError:
        logger.warning("Sin respuesta de precio para conId %s", con_id)
        tickers = []

    if not tickers:
        # Devolvemos una cotizacion vacia y no un error: que un valor no
        # cotice ahora mismo es normal, no es un fallo del sistema.
        return mapper.ticker_to_quote(
            type("TickerVacio", (), {"contract": contrato, "marketDataType": settings.IB_MARKET_DATA_TYPE})()
        )

    return mapper.ticker_to_quote(tickers[0])

# ---------------------------------------------------------------------
# Ordenes (T35)
# ---------------------------------------------------------------------

# whatIfOrder no devuelve el rechazo en su respuesta: lo emite por
# errorEvent, que es global a la conexion. Si dos validaciones corrieran a
# la vez, el error de una podria atribuirse a la otra. El lock las
# serializa. Es la solucion honesta con una unica conexion a IB; la
# alternativa seria filtrar por reqId, pero ib_async no lo expone antes de
# hacer la llamada.
_cerrojo_whatif = asyncio.Lock()


async def _resolver_contrato(con_id: int):
    """Contrato completo a partir del conId, listo para operar.

    Misma logica que en get_quote: el conId identifica el instrumento pero
    no dice en que mercado enrutar. SMART es el enrutador de IB y es el que
    hay que usar cuando el contrato lo admite.
    """
    detalles = await get_ib().reqContractDetailsAsync(Contract(conId=con_id))
    if not detalles:
        raise InstrumentNotFound(f"No existe ningun contrato con conId {con_id}")

    detalle = detalles[0]
    contrato = detalle.contract
    if "SMART" in (getattr(detalle, "validExchanges", "") or ""):
        contrato.exchange = "SMART"
    elif not contrato.exchange:
        contrato.exchange = contrato.primaryExchange
    return contrato


async def get_fx_rates() -> tuple[str, dict[str, float]]:
    """Divisa base y tipos de cambio de la cuenta.

    Se expone aparte de get_portfolio porque la validacion de ordenes los
    necesita sin necesitar la cartera: el coste de comprar AMZN sale en USD
    y el efectivo esta en EUR, y compararlos sin convertir no significa
    nada. No es una llamada de red: lee el estado que ya mantiene el canal
    reqAccountUpdates.
    """
    cuenta = _default_account()
    return mapper.account_values_to_fx(get_ib().accountValues(cuenta))


async def get_position_quantity(con_id: int, account_id: str | None = None) -> float:
    """Titulos que la cuenta tiene de un contrato concreto.

    Por conId y no por simbolo: dos cotizaciones distintas del mismo
    ticker son dos posiciones distintas, y sumarlas seria dar por vendible
    algo que no se tiene.
    """
    cuenta = account_id or _default_account()
    total = 0.0
    for item in get_ib().portfolio():
        if item.account != cuenta:
            continue
        if getattr(item.contract, "conId", 0) == con_id:
            total += _a_float(item.position)
    return total


def _a_float(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


async def preview_order(req: OrderRequest) -> BrokerPreview:
    """Pregunta a IB que pasaria con esta orden, sin enviarla.

    whatIfOrder es un placeOrder con la bandera whatIf puesta: IB calcula
    margenes y comision y no encola nada. Comprobado el 04/08/2026 que no
    deja rastro, ni en openOrders() ni en trades().

    Lo que IB contesta NO sustituye a nuestra validacion: informa del
    margen, y el margen es justo la operativa apalancada que la aplicacion
    no ofrece. Con 886.000 EUR de efectivo IB acepta comprar por 2,4
    millones. Aqui solo se usa para dos cosas: la comision estimada, que
    no sabemos calcular solos, y el rechazo por margen, que si IB emite es
    que la orden es imposible incluso con sus reglas laxas.
    """
    ib = get_ib()
    contrato = await _resolver_contrato(req.con_id)

    if req.order_type == "LMT":
        orden = LimitOrder(req.action, req.quantity, req.limit_price)
    else:
        orden = MarketOrder(req.action, req.quantity)

    # La cuenta se fija aunque solo haya una: con varias, IB rechaza la
    # orden sin ella y el fallo apareceria muy lejos de su causa.
    orden.account = _default_account()

    capturados: list[tuple[int, str]] = []

    def _al_error(*args):
        """Recoge lo que IB diga durante la llamada.

        Firma variable a proposito: ib_async ha ido anadiendo parametros a
        este evento entre versiones, y una firma fija dejaria de recibir
        eventos sin avisar de nada.
        """
        codigo = args[1] if len(args) > 1 else None
        mensaje = args[2] if len(args) > 2 else ""
        if isinstance(codigo, int):
            capturados.append((codigo, str(mensaje)))

    async with _cerrojo_whatif:
        ib.errorEvent += _al_error
        try:
            estado = await asyncio.wait_for(
                ib.whatIfOrderAsync(contrato, orden), timeout=settings.IB_TIMEOUT
            )
            # Carrera verificada el 04/08/2026: cuando IB rechaza, el
            # OrderState llega primero (con la comision en centinela) y el
            # error 201 llega un instante DESPUES por su propio canal.
            # Desuscribirse nada mas volver la llamada dejaba el rechazo
            # sin capturar y el preview decia "aceptada" siendo mentira.
            # La comision ausente es la huella de la sospecha: solo en ese
            # caso se concede una espera corta a que el mensaje llegue.
            if not capturados and mapper._importe(
                getattr(estado, "commission", None)
            ) is None:
                await asyncio.sleep(1.0)
        except asyncio.TimeoutError:
            logger.warning("Sin respuesta de whatIfOrder para conId %s", req.con_id)
            estado = None
        finally:
            # Se desuscribe siempre, tambien si la llamada revienta: un
            # manejador olvidado seguiria acumulando errores ajenos y
            # contaminaria la siguiente validacion.
            ib.errorEvent -= _al_error

    return mapper.order_state_to_preview(estado, contrato, capturados)