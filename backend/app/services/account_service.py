"""Lógica de aplicación relativa a la cuenta.

Ahora mismo esta capa apenas hace nada más que delegar, y eso es correcto:
no se inventa trabajo para justificarse. Existe porque es el sitio donde
irán, sin reestructurar nada, los límites configurables de VaR y de
correlación media y el chequeo previo al envío de órdenes.

Reglas de esta capa:
  - no importa fastapi (no lanza HTTPException, no conoce códigos HTTP)
  - no importa ib_async (RNF-08)
"""

from app.broker import ib_gateway
from app.models.account import AccountSummary


async def get_account_summary(account_id: str | None = None) -> AccountSummary:
    return await ib_gateway.get_account_summary(account_id)
