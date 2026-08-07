"""Pruebas del ensamblaje del panel de riesgo (T47), sin Gateway.

Se sustituyen las dos llamadas al broker por dobles. Lo que se prueba no
es la aritmetica —eso ya lo cubren test_risk_service y test_riesgo_var—
sino las decisiones del ensamblaje: que los pesos salgan del valor en
divisa base, que una cartera sin datos suficientes lo diga en vez de
inventarse cifras, y que la diversificacion aparezca como diferencia entre
las dos volatilidades.
"""

import math
from datetime import date, timedelta

import pytest

from app.models.portfolio import Portfolio, Position
from app.models.price_history import PriceHistory, PricePoint
from app.services import portfolio_risk_service as prs


def posicion(con_id, symbol, valor):
    return Position(
        con_id=con_id,
        symbol=symbol,
        sec_type="STK",
        currency="USD",
        quantity=10.0,
        avg_cost=100.0,
        market_price=100.0,
        market_value=valor,
        unrealized_pnl=0.0,
        market_value_base=valor,
    )


def serie(con_id, saltos, inicio=100.0):
    """Historico con un cierre por dia habil, generado desde rendimientos."""
    puntos, nivel, dia = [], inicio, date(2025, 8, 1)
    for r in saltos:
        puntos.append(PricePoint(date=dia, close=round(nivel, 6)))
        nivel *= math.exp(r)
        dia += timedelta(days=1)
    return PriceHistory(con_id=con_id, points=puntos)


def zigzag(n, amplitud):
    return [amplitud if i % 2 == 0 else -amplitud for i in range(n)]


def montar(monkeypatch, cartera, historicos):
    async def falso_portfolio(account_id=None):
        return cartera

    async def falso_historico(con_id):
        return historicos[con_id]

    monkeypatch.setattr(prs.ib_gateway, "get_portfolio", falso_portfolio)
    monkeypatch.setattr(prs.ib_gateway, "get_price_history", falso_historico)


@pytest.mark.anyio
async def test_cartera_vacia_no_inventa_metricas(monkeypatch):
    montar(monkeypatch, Portfolio(account_id="DUN684545", base_currency="EUR"), {})
    r = await prs.get_portfolio_risk()
    assert r.volatilidad is None
    assert r.aviso


@pytest.mark.anyio
async def test_serie_corta_da_aviso_y_no_var(monkeypatch):
    """Menos de 100 sesiones: el VaR al 99 % no tendria ni una observacion
    en la cola. Se publican pesos y concentracion, no metricas de serie."""
    cartera = Portfolio(
        account_id="X",
        base_currency="EUR",
        positions=[posicion(1, "AAA", 1000.0)],
        total_market_value=1000.0,
    )
    montar(monkeypatch, cartera, {1: serie(1, zigzag(30, 0.01))})

    r = await prs.get_portfolio_risk()

    assert r.var_historico_99 is None
    assert "sesiones" in r.aviso
    assert r.posiciones_efectivas == pytest.approx(1.0)


@pytest.mark.anyio
async def test_pesos_salen_del_valor_en_divisa_base(monkeypatch):
    cartera = Portfolio(
        account_id="X",
        base_currency="EUR",
        positions=[posicion(1, "AAA", 750.0), posicion(2, "BBB", 250.0)],
        total_market_value=1000.0,
    )
    montar(
        monkeypatch,
        cartera,
        {1: serie(1, zigzag(200, 0.01)), 2: serie(2, zigzag(200, 0.02))},
    )

    r = await prs.get_portfolio_risk()

    assert [p.peso for p in r.posiciones] == pytest.approx([0.75, 0.25])
    assert r.indice_herfindahl == pytest.approx(0.625)


@pytest.mark.anyio
async def test_la_diversificacion_aparece_como_diferencia(monkeypatch):
    """Dos series que se mueven al reves: la volatilidad del conjunto queda
    por debajo de la suma ponderada, y esa resta es el beneficio."""
    cartera = Portfolio(
        account_id="X",
        base_currency="EUR",
        positions=[posicion(1, "AAA", 500.0), posicion(2, "BBB", 500.0)],
        total_market_value=1000.0,
    )
    sube = zigzag(200, 0.015)
    baja = [-x for x in sube]
    montar(monkeypatch, cartera, {1: serie(1, sube), 2: serie(2, baja)})

    r = await prs.get_portfolio_risk()

    assert r.volatilidad < r.volatilidad_suma_ponderada
    assert r.beneficio_diversificacion == pytest.approx(
        r.volatilidad_suma_ponderada - r.volatilidad
    )


@pytest.mark.anyio
async def test_el_var_se_expresa_tambien_en_dinero(monkeypatch):
    cartera = Portfolio(
        account_id="X",
        base_currency="EUR",
        positions=[posicion(1, "AAA", 2000.0)],
        total_market_value=2000.0,
    )
    montar(monkeypatch, cartera, {1: serie(1, zigzag(200, 0.01))})

    r = await prs.get_portfolio_risk()

    assert r.var_historico_95_importe == pytest.approx(r.var_historico_95 * 2000.0)


@pytest.mark.anyio
async def test_alinea_por_fecha_aunque_una_serie_sea_mas_larga(monkeypatch):
    """Una posicion con mas sesiones que otra: el conjunto usa solo las
    fechas comunes, no las de la serie mas larga."""
    cartera = Portfolio(
        account_id="X",
        base_currency="EUR",
        positions=[posicion(1, "AAA", 500.0), posicion(2, "BBB", 500.0)],
        total_market_value=1000.0,
    )
    montar(
        monkeypatch,
        cartera,
        {1: serie(1, zigzag(250, 0.01)), 2: serie(2, zigzag(180, 0.01))},
    )

    r = await prs.get_portfolio_risk()

    assert r.sesiones == 180
