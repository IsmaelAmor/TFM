"""Pruebas del mapper de histórico de precios (Fase 5), sin Gateway.

Se usan barras sintéticas (SimpleNamespace) con la misma forma que las
BarData reales que devolvió scripts/sondea_historico.py el 07/08/2026:
date es un datetime.date y close un float. Así se comprueba la traducción
sin Gateway, igual que el resto de tests de mapper.
"""

from datetime import date
from types import SimpleNamespace

from app.broker import mapper
from app.models.price_history import PriceHistory


def barra(anio, mes, dia, close):
    """Doble de una BarData: solo los campos que el mapper mira."""
    return SimpleNamespace(date=date(anio, mes, dia), close=close)


def test_traduce_una_serie_completa():
    barras = [
        barra(2025, 8, 7, 220.03),
        barra(2025, 8, 8, 221.50),
        barra(2025, 8, 11, 219.80),
    ]

    h = mapper.bars_to_price_history(3691937, barras)

    assert isinstance(h, PriceHistory)
    assert h.con_id == 3691937
    assert len(h.points) == 3
    assert h.points[0].date == date(2025, 8, 7)
    assert h.points[0].close == 220.03


def test_expone_solo_los_cierres():
    barras = [barra(2025, 8, 7, 220.03), barra(2025, 8, 8, 221.50)]

    h = mapper.bars_to_price_history(1, barras)

    assert h.closes == [220.03, 221.50]


def test_respeta_el_orden_de_ib_sin_reordenar():
    # IB entrega más antiguo primero. El mapper NO reordena: los
    # rendimientos dependen del orden y alterarlo daría saltos falsos.
    barras = [barra(2025, 8, 7, 100.0), barra(2025, 8, 8, 110.0)]

    h = mapper.bars_to_price_history(1, barras)

    assert [p.date for p in h.points] == [date(2025, 8, 7), date(2025, 8, 8)]


def test_lista_vacia_da_historico_vacio():
    h = mapper.bars_to_price_history(1, [])
    assert h.points == []
    assert h.closes == []


def test_none_da_historico_vacio():
    # Si IB no devuelve barras, la función no debe reventar.
    h = mapper.bars_to_price_history(1, None)
    assert h.points == []


def test_descarta_cierres_no_positivos():
    # Un cierre de cero o negativo rompería el logaritmo de los
    # rendimientos: se descarta la barra en vez de arrastrar el problema.
    barras = [
        barra(2025, 8, 7, 220.0),
        barra(2025, 8, 8, 0.0),
        barra(2025, 8, 11, -5.0),
        barra(2025, 8, 12, 221.0),
    ]

    h = mapper.bars_to_price_history(1, barras)

    assert h.closes == [220.0, 221.0]


def test_descarta_cierre_no_numerico():
    barras = [barra(2025, 8, 7, 220.0), barra(2025, 8, 8, "sin dato")]

    h = mapper.bars_to_price_history(1, barras)

    assert h.closes == [220.0]
