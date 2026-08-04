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
import math
from datetime import datetime, timezone
from app.models.instrument import Instrument
from app.models.quote import Quote

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