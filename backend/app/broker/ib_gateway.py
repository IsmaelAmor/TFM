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
    """Posiciones abiertas, ya valoradas por IB.

    Usa portfolio() y no positions(): el canal reqAccountUpdates trae
    marketPrice, marketValue, unrealizedPNL y realizedPNL, que
    reqPositions no da. Verificado contra DUN684545 el 03/08/2026.
    """
    cuenta = account_id or _default_account()
    items = [i for i in get_ib().portfolio() if i.account == cuenta]
    return mapper.portfolio_items_to_portfolio(items, cuenta)
