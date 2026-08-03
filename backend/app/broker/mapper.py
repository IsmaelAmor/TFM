"""Traduccion de objetos ib_async a modelos propios.

Este fichero es lo que hace que RNF-08 signifique algo. Si el broker
devolviera PortfolioItem o AccountValue hacia arriba, el acoplamiento
seguiria existiendo, solo que escondido. Aqui se corta.

Todo el conocimiento sobre la forma exacta de los datos de IB vive aqui.
Si ib_async renombra un campo, se toca este fichero y ninguno mas.

Trampa verificada el 03/08/2026: el coste medio se llama avgCost en los
objetos Position (canal reqPositions) y averageCost en los PortfolioItem
(canal reqAccountUpdates). Usamos los segundos.
"""

from app.models.account import AccountSummary
from app.models.portfolio import Portfolio, Position


def _to_float(value, default: float = 0.0) -> float:
    """IB devuelve varios importes como cadena, y a veces vacios."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def portfolio_item_to_position(item) -> Position:
    """Convierte un PortfolioItem de IB en una Position propia."""
    contract = item.contract
    return Position(
        symbol=contract.symbol,
        sec_type=contract.secType,
        currency=contract.currency,
        exchange=contract.primaryExchange or contract.exchange or "",
        quantity=_to_float(item.position),
        avg_cost=_to_float(item.averageCost),
        market_price=_to_float(item.marketPrice),
        market_value=_to_float(item.marketValue),
        unrealized_pnl=_to_float(item.unrealizedPNL),
        realized_pnl=_to_float(item.realizedPNL),
    )


def portfolio_items_to_portfolio(items, account_id: str) -> Portfolio:
    """Convierte la lista de PortfolioItem en una Portfolio con totales.

    Los totales son suma directa de datos que ya vienen de IB, por eso se
    calculan aqui. Cualquier metrica con criterio propio (volatilidad,
    VaR, concentracion) NO va aqui: va en services/risk_service.py.
    """
    positions = [portfolio_item_to_position(i) for i in items]
    return Portfolio(
        account_id=account_id,
        positions=positions,
        total_market_value=sum(p.market_value for p in positions),
        total_cost=sum(p.avg_cost * p.quantity for p in positions),
        total_unrealized_pnl=sum(p.unrealized_pnl for p in positions),
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
