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
from ib_async import Contract
from app.models.instrument import Instrument
from app.models.quote import Quote
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