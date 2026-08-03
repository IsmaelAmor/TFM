"""Modelos de cartera.

Los campos salen de lo que devuelve ib.portfolio() de verdad, verificado
contra DUN684545 el 03/08/2026 con compara_posiciones.py. No de la
documentación ni de suposiciones.
"""

from pydantic import BaseModel, Field


class Position(BaseModel):
    """Una posición abierta, ya valorada por IB."""

    symbol: str = Field(..., description="Ticker, p. ej. AMZN")
    sec_type: str = Field(..., description="Tipo IB: STK cubre acciones y ETFs")
    currency: str = Field(..., description="Divisa del instrumento")
    exchange: str = Field("", description="Mercado principal")
    quantity: float = Field(..., description="Numero de titulos")
    avg_cost: float = Field(..., description="Coste medio de adquisicion")
    market_price: float = Field(..., description="Ultimo precio conocido")
    market_value: float = Field(..., description="Valor de mercado")
    unrealized_pnl: float = Field(..., description="PnL no realizado")
    realized_pnl: float = Field(0.0, description="PnL realizado")


class Portfolio(BaseModel):
    """Cartera completa con sus totales.

    Los totales van aquí y no en el frontend por una razon concreta: son
    la base del panel de metricas y del calculo de concentracion. Si los
    calculara Angular, el backend no podria razonar sobre ellos.
    """

    account_id: str
    positions: list[Position] = Field(default_factory=list)
    total_market_value: float = 0.0
    total_cost: float = 0.0
    total_unrealized_pnl: float = 0.0
