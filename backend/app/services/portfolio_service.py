"""Lógica de aplicación relativa a la cartera.

Aquí acabarán los pesos por posición, la concentración y el aviso de
diversificación en lenguaje natural. Las métricas de riesgo puras
(volatilidad, Sharpe, drawdown, correlaciones, VaR) irán en su propio
risk_service.py cuando llegue su tarea: se separan porque son cálculo
sobre series de precios y deben poder probarse sin IB Gateway levantado.
"""

from app.broker import ib_gateway
from app.models.portfolio import Portfolio


async def get_portfolio(account_id: str | None = None) -> Portfolio:
    return await ib_gateway.get_portfolio(account_id)
