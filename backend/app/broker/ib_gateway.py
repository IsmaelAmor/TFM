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
from ib_async import Contract, ExecutionFilter, LimitOrder, MarketOrder
from app.models.instrument import Instrument
from app.models.quote import Quote
from app.models.price_history import PriceHistory
from app.models.order import BrokerPreview, OrderRequest, OrderResult
from app.models.execution import ExecutionHistory
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

# ---------------------------------------------------------------------
# Envio de ordenes (T36)
# ---------------------------------------------------------------------

# Cuanto se espera, como maximo, a que una orden recien enviada alcance un
# estado terminal antes de contestar. No es el IB_TIMEOUT de las consultas:
# una MKT que cruza se resuelve en ~0,2 s y un rechazo por margen en ~0,1 s
# (medido el 04/08/2026). Una limitada que no cruza no termina nunca; para
# ella este limite es el que decide devolver 'activa' en lugar de dejar la
# peticion HTTP colgada.
_ESPERA_ENVIO = 4.0

# Codigos de error de IB que, al enviar, portan el motivo de un rechazo.
# El 201 es el rechazo por margen, el unico que DUN684545 emite de verdad.
# Se excluye a proposito el 202, que es el acuse de una cancelacion y no un
# problema, y toda la familia 2100+/10167, que son avisos de conexion y de
# datos diferidos.
_MOTIVOS_RECHAZO = frozenset({110, 200, 201, 203, 321, 383, 481})


def _motivo_de(capturados, order_id: int) -> tuple[int | None, str]:
    """Primer error de rechazo cuyo reqId coincide con la orden."""
    for req_id, codigo, mensaje in capturados:
        if req_id == order_id and codigo in _MOTIVOS_RECHAZO:
            return codigo, mensaje
    return None, ""


async def _esperar_terminal(trade, segundos: float) -> None:
    """Cede el control al bucle hasta que la orden termina o vence el plazo.

    El await deja que ib_async procese los eventos del socket y actualice
    el Trade; sin el, isDone() no cambiaria nunca. Una orden viva que no
    cruza agota el plazo y se devuelve tal cual esta: 'activa'.
    """
    loop = asyncio.get_running_loop()
    limite = loop.time() + segundos
    while loop.time() < limite:
        if trade.isDone():
            return
        await asyncio.sleep(0.05)


async def place_order(req: OrderRequest) -> OrderResult:
    """Envia una orden real al mercado y devuelve como quedo.

    A diferencia de preview_order, esto SI opera: deja posicion y aparece
    en el historial. La validacion de reglas propias es responsabilidad de
    order_service, que llama a esto solo si la orden paso el veredicto.

    No hace falta cerrojo global como en preview_order. Alli whatIfOrderAsync
    no da el orderId con el que filtrar y habia que serializar; aqui
    placeOrder devuelve el Trade con su orderId en el acto, asi que cada
    envio se queda solo con los errores de su propio reqId.
    """
    ib = get_ib()
    contrato = await _resolver_contrato(req.con_id)

    if req.order_type == "LMT":
        orden = LimitOrder(req.action, req.quantity, req.limit_price)
    else:
        orden = MarketOrder(req.action, req.quantity)
    orden.account = _default_account()

    capturados: list[tuple[int, int, str]] = []

    def _al_error(*args):
        """Recoge (reqId, codigo, mensaje) de cada evento de error.

        Firma variable como en preview_order: ib_async ha ido cambiando el
        numero de parametros de errorEvent entre versiones.
        """
        req_id = args[0] if len(args) > 0 else None
        codigo = args[1] if len(args) > 1 else None
        mensaje = args[2] if len(args) > 2 else ""
        if isinstance(codigo, int):
            capturados.append((req_id, codigo, str(mensaje)))

    ib.errorEvent += _al_error
    try:
        trade = ib.placeOrder(contrato, orden)
        order_id = trade.order.orderId
        await _esperar_terminal(trade, _ESPERA_ENVIO)

        # Carrera verificada el 04/08/2026: el paso a Inactive llega un
        # instante ANTES que el error 201 con el motivo. Si la orden acabo
        # rechazada pero su error aun no ha llegado, se concede una espera
        # corta; si no, quedaria como 'rechazada' sin explicacion.
        status = getattr(trade.orderStatus, "status", "") or ""
        if status in mapper._RECHAZADA and _motivo_de(capturados, order_id) == (None, ""):
            await asyncio.sleep(1.0)
    finally:
        # Se desuscribe siempre, tambien si placeOrder revienta: un
        # manejador olvidado contaminaria el siguiente envio con errores
        # ajenos.
        ib.errorEvent -= _al_error

    codigo, mensaje = _motivo_de(capturados, order_id)
    return mapper.trade_to_result(trade, error_code=codigo, error_message=mensaje)


async def find_order(order_id: int) -> OrderResult | None:
    """Estado actual de una orden ya enviada en esta sesion.

    Sostiene el GET de seguimiento: el frontend sondea una limitada viva
    hasta que se ejecuta o se cancela. Usa trades() y no openTrades()
    porque tambien tiene que encontrar las ya terminadas.

    Limite conocido: tras reiniciar uvicorn solo se recuperan las ordenes
    VIVAS (verificado el 04/08/2026: openTrades() las repuebla al
    reconectar con el mismo clientId). Las ya ejecutadas de antes del
    reinicio no vuelven, lo que es aceptable: el seguimiento interesa
    mientras la orden sigue en juego, no como historico.
    """
    for trade in get_ib().trades():
        if trade.order.orderId == order_id:
            return mapper.trade_to_result(trade)
    return None

async def get_price_history(con_id: int) -> PriceHistory:
    """Serie de cierres diarios de 1 ano, para el modulo de riesgo.

    Parametros fijados segun el sondeo del 07/08/2026
    (scripts/sondea_historico.py), verificados contra DUN684545:

      - durationStr '1 Y', barSizeSetting '1 day': ~251 barras, los dias
        habiles de un ano. 252 es la constante de anualizacion, no el
        recuento exacto.
      - whatToShow 'ADJUSTED_LAST': corrige splits y dividendos. Sin
        ajustar, cada fecha ex-dividendo mete una caida que no es
        movimiento real de precio y un split mete un salto enorme; ambos
        dispararian la volatilidad medida (D-18). Medido en AAPL: primer
        cierre 220,03 sin ajustar frente a 219,16 ajustado.
      - useRTH True: solo sesion regular, sin extended hours.
      - formatDate 1: fecha como datetime.date, que es lo que el mapper
        espera sin parsear.

    Funciona con dato retrasado (marketDataType 3, lo unico que tiene la
    cuenta paper) y con el mercado cerrado: el historico no depende de
    suscripcion en tiempo real, verificado a las 10:30 con Wall Street aun
    sin abrir. La ultima barra es la de la ultima sesion cerrada, que es lo
    correcto: las metricas se calculan sobre sesiones completas.

    El pacing medido fue holgado (~0,4 s por peticion, sin error 162), asi
    que el modulo puede pedir el historico de las posiciones de la cartera
    en serie sin espaciar. Si la cartera creciera mucho, el limitador iria
    aqui, no en la capa de servicio.
    """
    ib = get_ib()
    contrato = await _resolver_contrato(con_id)

    # El wait_for es la misma red de seguridad que en get_quote: si IB no
    # contesta, la peticion HTTP no puede quedarse colgada. El historico
    # tarda mas que una cotizacion, asi que se le da un margen mayor que el
    # timeout general.
    try:
        barras = await asyncio.wait_for(
            ib.reqHistoricalDataAsync(
                contrato,
                endDateTime="",
                durationStr="1 Y",
                barSizeSetting="1 day",
                whatToShow="ADJUSTED_LAST",
                useRTH=True,
                formatDate=1,
            ),
            timeout=settings.IB_TIMEOUT * 3,
        )
    except asyncio.TimeoutError:
        logger.warning("Sin respuesta de historico para conId %s", con_id)
        barras = []

    return mapper.bars_to_price_history(con_id, barras)


async def get_executions(account_id: str | None = None) -> ExecutionHistory:
    """Ejecuciones del dia en curso, ya traducidas a modelo propio.

    ALCANCE DECLARADO: reqExecutions solo sirve las ejecuciones desde
    medianoche del servidor de IB. Medido el 07/08/2026 con tres sondas
    (scripts/sondea_ejecuciones*.py): con filtros de 1, 3, 7, 30 y 90 dias
    atras devuelve CERO, mientras que una compra hecha ese mismo dia
    aparece al instante. Los filtros de fecha acotan DENTRO de la ventana,
    no la amplian, asi que pasar un 'time' al filtro no serviria de nada y
    solo daria la falsa impresion de cubrir mas.

    La causa no es la API sino haber elegido IB Gateway: la ventana sube a
    siete dias con el ajuste "Show trades for..." del Trade Log de TWS, y
    el Gateway, al no tener interfaz grafica, no puede modificarlo.

    Se usa reqExecutionsAsync y no ib.fills(): fills() lee la memoria del
    cliente, o sea solo lo visto desde que este proceso se conecto, y se
    vaciaria en cada reinicio de uvicorn. reqExecutions pregunta al
    servidor de IB, que es la fuente.

    El filtro va VACIO a proposito. ExecutionFilter() ya trae clientId=0,
    que significa "todos los clientes": asi el historico incluye tambien
    lo operado desde TWS a mano, y no solo lo enviado por esta aplicacion.
    Un historico que ocultara las operaciones manuales mentiria por
    omision.
    """
    cuenta = account_id or _default_account()
    ib = get_ib()

    fills = await asyncio.wait_for(
        ib.reqExecutionsAsync(ExecutionFilter()),
        timeout=settings.IB_TIMEOUT,
    )

    if cuenta:
        fills = [f for f in fills if f.execution.acctNumber == cuenta]

    return mapper.fills_to_history(fills, cuenta)
