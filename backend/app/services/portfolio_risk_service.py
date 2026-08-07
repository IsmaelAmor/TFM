"""Ensamblaje del panel de riesgo (T47).

Este modulo es el unico sitio donde se junta lo que pide IB con lo que
calcula risk_service. Es deliberado: risk_service son funciones puras sobre
listas de numeros y no debe saber que existe una cartera; el broker
devuelve datos y no debe saber que existe el riesgo. Aqui se cose.

La serie de la cartera se construye ponderando los rendimientos diarios de
cada posicion por su peso ACTUAL. Es una aproximacion y conviene decirlo en
la memoria: supone que la cartera de hoy se mantuvo todo el ano, cuando en
realidad los pesos han ido cambiando. La alternativa exacta exigiria
reconstruir la composicion historica dia a dia desde las operaciones, y el
historico de ejecuciones esta limitado al dia en curso (T38, D-22). Se
elige la aproximacion y se declara.
"""

import logging

from app.broker import ib_gateway
from app.models.portfolio import Portfolio
from app.models.risk import PortfolioRisk, PositionRisk
from app.services import risk_service as rs

logger = logging.getLogger(__name__)

# Minimo de sesiones comunes para publicar metricas de conjunto. Por debajo
# de 100 el VaR al 99 % no tiene ni una observacion en la cola (ver
# var_historico), asi que la cifra seria una extrapolacion disfrazada.
MINIMO_SESIONES = 100


async def get_portfolio_risk(
    account_id: str | None = None, tasa_libre_riesgo: float = 0.0
) -> PortfolioRisk:
    """Descarga los historicos de la cartera y devuelve el panel completo."""
    cartera: Portfolio = await ib_gateway.get_portfolio(account_id)
    vivas = [p for p in cartera.positions if p.quantity != 0 and p.con_id > 0]

    base = PortfolioRisk(
        account_id=cartera.account_id,
        base_currency=cartera.base_currency,
        simbolos=[p.symbol for p in vivas],
    )

    if not vivas:
        base.aviso = "La cartera no tiene posiciones abiertas."
        return base

    total = cartera.total_market_value
    if total <= 0:
        base.aviso = "El valor de mercado de la cartera no es positivo."
        return base

    pesos = [p.market_value_base / total for p in vivas]

    # En serie y no con gather: el pacing del historico es el riesgo R-03 y
    # el sondeo del 07/08 midio ~0,4 s por peticion sin error 162 pidiendo
    # una detras de otra. Paralelizar ganaria poco y arriesgaria el 162.
    series_por_fecha = []
    for p in vivas:
        historico = await ib_gateway.get_price_history(p.con_id)
        series_por_fecha.append({punto.date: punto.close for punto in historico.points})

    cierres = rs.alinear_series(series_por_fecha)
    sesiones = len(cierres[0]) if cierres else 0
    base.sesiones = sesiones

    rendimientos = [rs.rendimientos_log(c) for c in cierres]

    base.posiciones = [
        PositionRisk(
            con_id=p.con_id,
            symbol=p.symbol,
            peso=w,
            volatilidad=rs.volatilidad_anualizada(r),
            maximo_drawdown=rs.maximo_drawdown(c),
            var_historico_95=rs.var_historico(r, 0.95),
            var_parametrico_95=rs.var_parametrico(r, 0.95),
            sesiones=len(c),
        )
        for p, w, c, r in zip(vivas, pesos, cierres, rendimientos)
    ]

    base.indice_herfindahl = rs.indice_herfindahl(pesos)
    base.posiciones_efectivas = rs.posiciones_efectivas(pesos)
    base.correlaciones = rs.matriz_correlacion(rendimientos)

    if sesiones < MINIMO_SESIONES:
        base.aviso = (
            f"Solo hay {sesiones} sesiones comunes a todas las posiciones; "
            f"hacen falta {MINIMO_SESIONES} para estimar el VaR al 99 %. "
            "Se muestran los pesos y la concentracion, no las metricas de "
            "serie."
        )
        return base

    # Serie de la cartera: rendimiento diario ponderado por peso actual.
    cartera_diaria = [
        sum(w * r[i] for w, r in zip(pesos, rendimientos)) for i in range(sesiones - 1)
    ]

    base.volatilidad = rs.volatilidad_cartera(pesos, rendimientos)
    base.volatilidad_suma_ponderada = rs.volatilidad_suma_ponderada(pesos, rendimientos)
    if base.volatilidad is not None and base.volatilidad_suma_ponderada is not None:
        base.beneficio_diversificacion = (
            base.volatilidad_suma_ponderada - base.volatilidad
        )

    base.rendimiento_anualizado = rs.rendimiento_anualizado(cartera_diaria)
    base.ratio_sharpe = rs.ratio_sharpe(cartera_diaria, tasa_libre_riesgo)
    base.maximo_drawdown = rs.maximo_drawdown(_reconstruir_indice(cartera_diaria))

    base.var_historico_95 = rs.var_historico(cartera_diaria, 0.95)
    base.var_historico_99 = rs.var_historico(cartera_diaria, 0.99)
    base.var_parametrico_95 = rs.var_parametrico(cartera_diaria, 0.95)
    base.var_parametrico_99 = rs.var_parametrico(cartera_diaria, 0.99)

    if base.var_historico_95 is not None:
        base.var_historico_95_importe = base.var_historico_95 * total

    return base


def _reconstruir_indice(rendimientos: list[float], inicio: float = 100.0) -> list[float]:
    """Serie de niveles a partir de rendimientos logaritmicos.

    El drawdown se mide sobre PRECIOS, no sobre rendimientos, asi que la
    cartera necesita una serie de niveles que no existe: se reconstruye
    componiendo los rendimientos ponderados desde una base arbitraria de
    100. El drawdown es una fraccion, asi que la base elegida no afecta al
    resultado.
    """
    import math

    niveles = [inicio]
    for r in rendimientos:
        niveles.append(niveles[-1] * math.exp(r))
    return niveles
