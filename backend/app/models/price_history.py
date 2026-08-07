"""Modelo de serie histórica de precios (Fase 5).

Alimenta el módulo de riesgo. De cada barra diaria que devuelve IB solo se
conservan los dos campos que el cálculo necesita: la fecha y el cierre. El
sondeo del 07/08/2026 (scripts/sondea_historico.py) confirmó que 'date'
llega ya como datetime.date, así que no hay parseo: se guarda tal cual.

Se descartan open/high/low/volume/average/barCount a propósito. La
volatilidad, el drawdown y las correlaciones se calculan sobre precios de
cierre; arrastrar el resto sería cargar el modelo con datos que ninguna
métrica usa. Es un modelo propio y no una BarData de ib_async para que
RNF-08 siga siendo cierto: ningún objeto de ib_async sale del paquete
broker.
"""

from datetime import date

from pydantic import BaseModel


class PricePoint(BaseModel):
    """Un cierre diario: la fecha de la sesión y su precio de cierre."""

    date: date
    close: float


class PriceHistory(BaseModel):
    """Serie de cierres diarios de un instrumento, identificado por conId.

    Los puntos vienen ordenados de más antiguo a más reciente, tal como los
    entrega IB. El orden importa: los rendimientos día a día se calculan
    sobre pares consecutivos, y una serie desordenada daría saltos falsos.
    """

    con_id: int
    points: list[PricePoint]

    @property
    def closes(self) -> list[float]:
        """Solo los cierres, que es lo que consume risk_service."""
        return [p.close for p in self.points]
