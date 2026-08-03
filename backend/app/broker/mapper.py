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
