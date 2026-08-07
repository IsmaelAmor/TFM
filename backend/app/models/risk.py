"""Modelos del panel de riesgo (T47, RF-19).

La respuesta se disena para que el frontend NO calcule nada: cada cifra que
se pinta viene ya resuelta. Si Angular calculara los pesos o la
diversificacion, el backend no podria razonar sobre ellos ni contrastarlos
con un limite, que es lo que hara el chequeo pre-trade (T48).

Casi todo es opcional a proposito. Una serie demasiado corta, una posicion
recien comprada o una cartera sin fechas comunes producen metricas NO
DEFINIDAS, y eso es distinto de un cero. Un None se pinta "n/d"; un cero
dice "no hay riesgo", que seria mentira.
"""

from pydantic import BaseModel, Field


class PositionRisk(BaseModel):
    """Metricas de una posicion aislada."""

    con_id: int
    symbol: str
    peso: float = Field(0.0, description="Fraccion del valor total de la cartera")
    volatilidad: float | None = Field(None, description="Anualizada, 0,28 = 28 %")
    maximo_drawdown: float | None = Field(None, description="Caida pico-valle, positiva")
    var_historico_95: float | None = Field(None, description="Perdida diaria, positiva")
    var_parametrico_95: float | None = None
    sesiones: int = Field(0, description="Barras usadas tras alinear por fecha")


class PortfolioRisk(BaseModel):
    """Riesgo del conjunto, mas el detalle por posicion.

    volatilidad y volatilidad_suma_ponderada se publican JUNTAS: la primera
    tiene en cuenta que las posiciones no caen a la vez y la segunda no. Su
    diferencia es el beneficio de diversificacion, y es el argumento
    central del modulo. Lo mismo con los dos VaR: el historico lee la cola
    real y el parametrico la extrapola de una normal; que difieran no es un
    fallo, es el resultado.
    """

    account_id: str
    base_currency: str = ""
    sesiones: int = Field(0, description="Fechas comunes a todas las posiciones")

    volatilidad: float | None = None
    volatilidad_suma_ponderada: float | None = None
    beneficio_diversificacion: float | None = Field(
        None, description="Suma ponderada menos volatilidad conjunta"
    )
    rendimiento_anualizado: float | None = None
    ratio_sharpe: float | None = None
    maximo_drawdown: float | None = None

    var_historico_95: float | None = Field(None, description="Fraccion del valor")
    var_historico_99: float | None = None
    var_parametrico_95: float | None = None
    var_parametrico_99: float | None = None
    var_historico_95_importe: float | None = Field(
        None, description="El VaR al 95 % en divisa base"
    )

    indice_herfindahl: float | None = None
    posiciones_efectivas: float | None = None
    correlaciones: list[list[float | None]] = Field(default_factory=list)
    simbolos: list[str] = Field(default_factory=list)

    posiciones: list[PositionRisk] = Field(default_factory=list)
    aviso: str = Field("", description="Por que faltan metricas, si faltan")
