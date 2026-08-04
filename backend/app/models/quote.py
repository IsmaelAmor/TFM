"""Modelo de cotizacion puntual.

Todos los precios son opcionales a proposito. Fuera del horario de mercado,
o en un valor sin negociacion, IB no manda precio, y un cero seria mentira:
un cero es un precio, y "no hay dato" no lo es. El frontend distingue los
dos casos porque aqui viajan como null.

Verificado el 04/08/2026: el dato retrasado llego con 15 minutos y 21
segundos de antiguedad (delayedLastTimestamp 09:38:55 frente a la respuesta
de las 09:54:16). Por eso quote_time y received_at son campos distintos:
confundirlos haria creer que el precio es de ahora mismo.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Quote(BaseModel):
    """Ultimo precio conocido de un instrumento."""

    con_id: int
    symbol: str
    currency: str = ""
    exchange: str = ""

    last: float | None = Field(None, description="Ultimo precio negociado")
    bid: float | None = Field(None, description="Mejor posicion compradora")
    ask: float | None = Field(None, description="Mejor posicion vendedora")
    close: float | None = Field(None, description="Cierre de la sesion anterior")
    volume: float | None = Field(None, description="Volumen negociado")

    change: float | None = Field(None, description="Variacion sobre el cierre anterior")
    change_pct: float | None = Field(None, description="Variacion en porcentaje")

    delayed: bool = Field(True, description="True si el dato es retrasado")
    market_data_type: int = Field(3, description="1 real, 2 congelado, 3 retrasado, 4 retrasado congelado")

    quote_time: datetime | None = Field(None, description="Momento al que corresponde el precio")
    received_at: datetime = Field(..., description="Momento en que lo recibimos")
