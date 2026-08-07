"""Modelos de cartera.

Los campos salen de lo que devuelve ib.portfolio() de verdad, verificado
contra DUN684545 el 03/08/2026 con scripts/compara_posiciones.py. No de la
documentación ni de suposiciones.

Sobre divisas: cada posición conserva sus importes en la divisa en que
cotiza, porque un precio de AMZN expresado en euros no significa nada.
Junto a ellos van los mismos importes convertidos a la divisa base de la
cuenta, que son los únicos que pueden sumarse entre sí. Los totales de
Portfolio están SIEMPRE en divisa base.
"""

from pydantic import BaseModel, Field


class Position(BaseModel):
    """Una posición abierta, ya valorada por IB."""

    con_id: int = Field(
        0,
        description="Identificador de contrato de IB; el unico identificador fiable",
    )
    con_id: int = Field(
        0,
        description="Identificador de contrato de IB; el unico identificador fiable",
    )
    symbol: str = Field(..., description="Ticker, p. ej. AMZN")
    sec_type: str = Field(..., description="Tipo IB: STK cubre acciones y ETFs")
    currency: str = Field(..., description="Divisa en que cotiza el instrumento")
    exchange: str = Field("", description="Mercado principal")
    quantity: float = Field(..., description="Numero de titulos")

    # Importes en la divisa del instrumento
    avg_cost: float = Field(..., description="Coste medio por titulo, en su divisa")
    market_price: float = Field(..., description="Ultimo precio conocido, en su divisa")
    market_value: float = Field(..., description="Valor de mercado, en su divisa")
    unrealized_pnl: float = Field(..., description="PnL no realizado, en su divisa")
    realized_pnl: float = Field(0.0, description="PnL realizado, en su divisa")

    # Los mismos importes en divisa base, que son los que se pueden sumar
    fx_rate: float = Field(1.0, description="Tipo de cambio aplicado a divisa base")
    market_value_base: float = Field(0.0, description="Valor de mercado en divisa base")
    cost_base: float = Field(0.0, description="Coste total en divisa base")
    unrealized_pnl_base: float = Field(0.0, description="PnL no realizado en divisa base")


class Portfolio(BaseModel):
    """Cartera completa con sus totales.

    Los totales van aquí y no en el frontend por una razon concreta: son
    la base del panel de metricas y del calculo de concentracion. Si los
    calculara Angular, el backend no podria razonar sobre ellos.

    Todos los totales estan expresados en base_currency. Sumar importes de
    divisas distintas produce un numero sin significado, asi que la
    conversion se hace antes de sumar y no despues.
    """

    account_id: str
    base_currency: str = Field("", description="Divisa base de la cuenta, p. ej. EUR")
    positions: list[Position] = Field(default_factory=list)
    total_market_value: float = Field(0.0, description="Valor total en divisa base")
    total_cost: float = Field(0.0, description="Coste total en divisa base")
    total_unrealized_pnl: float = Field(0.0, description="PnL total en divisa base")
