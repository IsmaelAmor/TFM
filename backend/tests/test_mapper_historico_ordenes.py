"""Pruebas de la traduccion de ejecuciones (T38, RF-13), sin Gateway.

Los objetos de ib_async se imitan con SimpleNamespace y los valores salen
del sondeo real del 07/08/2026 (scripts/sondea_ejecuciones_hoy.py): una
compra de 1 AMZN a 277,57 en ARCA, execId '0000e0d5.6a75dc04.01.01',
permId 1834615398 y sello 15:45:30 UTC. No son numeros inventados: son la
forma exacta en que llegan.

Ejecutar desde backend/ con el venv activado:
    python -m pytest tests/test_mapper_historico_ordenes.py
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.broker import mapper

UTC = timezone.utc


def contrato(symbol="AMZN", currency="USD"):
    return SimpleNamespace(
        symbol=symbol, secType="STK", currency=currency, exchange="SMART"
    )


def ejecucion(side="BOT", shares=1.0, price=277.57, momento=None, order_id=5):
    return SimpleNamespace(
        execId="0000e0d5.6a75dc04.01.01",
        orderId=order_id,
        permId=1834615398,
        side=side,
        shares=shares,
        price=price,
        exchange="ARCA",
        time=momento or datetime(2026, 8, 7, 15, 45, 30, tzinfo=UTC),
        acctNumber="DUN684545",
    )


def comision(importe=1.0, divisa="USD"):
    return SimpleNamespace(commission=importe, currency=divisa, execId="x")


def comision_vacia():
    """El CommissionReport tal como lo crea ib_async antes de rellenarlo."""
    return SimpleNamespace(commission=0.0, currency="", execId="")


def fill(exec_=None, contract=None, report=None):
    return SimpleNamespace(
        execution=exec_ or ejecucion(),
        contract=contract or contrato(),
        commissionReport=report if report is not None else comision_vacia(),
    )


# --- Traduccion del lado -------------------------------------------------


def test_bot_se_traduce_a_buy():
    # IB usa BOT/SLD en las ejecuciones y BUY/SELL en las ordenes. Sin
    # traducir, la misma operacion se llamaria distinto segun por donde se
    # consulte y el frontend tendria que conocer las dos convenciones.
    assert mapper.fill_to_execution(fill()).action == "BUY"


def test_sld_se_traduce_a_sell():
    e = mapper.fill_to_execution(fill(exec_=ejecucion(side="SLD")))
    assert e.action == "SELL"


def test_lado_desconocido_pasa_tal_cual_y_no_rompe():
    # Un codigo que no conocemos no debe tumbar la consulta del historico
    # entero: se deja pasar y se ve en pantalla.
    e = mapper.fill_to_execution(fill(exec_=ejecucion(side="XXX")))
    assert e.action == "XXX"


# --- Comision: la trampa de T36, otra vez --------------------------------


def test_comision_vacia_es_none_y_no_cero():
    # LA PRUEBA IMPORTANTE. ib_async crea el CommissionReport con
    # commission=0.0 y currency='' y lo rellena despues por evento. Tomar
    # ese 0.0 por bueno seria afirmar que la operacion no costo nada.
    e = mapper.fill_to_execution(fill(report=comision_vacia()))
    assert e.commission is None
    assert e.commission_currency == ""


def test_comision_poblada_se_conserva():
    e = mapper.fill_to_execution(fill(report=comision(1.05, "USD")))
    assert e.commission == pytest.approx(1.05)
    assert e.commission_currency == "USD"


def test_comision_cero_con_divisa_si_es_cero():
    # Distinto del caso anterior: si IB dice explicitamente 0 USD, es que
    # la operacion no tuvo comision. La divisa es lo que distingue "sin
    # dato" de "dato que vale cero".
    e = mapper.fill_to_execution(fill(report=comision(0.0, "USD")))
    assert e.commission == 0.0
    assert e.commission_currency == "USD"


def test_sin_commission_report_es_none():
    f = fill()
    f.commissionReport = None
    assert mapper.fill_to_execution(f).commission is None


# --- Campos y calculo ----------------------------------------------------


def test_importe_es_cantidad_por_precio():
    e = mapper.fill_to_execution(fill(exec_=ejecucion(shares=3.0, price=100.5)))
    assert e.amount == pytest.approx(301.5)


def test_identificadores_y_contrato():
    e = mapper.fill_to_execution(fill())
    assert e.exec_id == "0000e0d5.6a75dc04.01.01"
    assert e.order_id == 5
    # permId SI viene poblado aqui, a diferencia de justo tras placeOrder,
    # donde vale 0. Es el identificador estable de la orden en IB.
    assert e.perm_id == 1834615398
    assert e.symbol == "AMZN"
    assert e.currency == "USD"
    assert e.account_id == "DUN684545"


def test_mercado_de_ejecucion_gana_al_del_contrato():
    # El contrato dice SMART, que es el enrutador, no un mercado. La
    # ejecucion dice ARCA, que es donde cruzo de verdad. Un historico debe
    # contar donde ocurrio, no por donde se pidio.
    assert mapper.fill_to_execution(fill()).exchange == "ARCA"


def test_el_sello_de_tiempo_se_conserva_en_utc():
    # ib_async ya entrega datetime con tzinfo=UTC: ni se parsea ni se
    # convierte. Localizar es cosa de quien pinta, no de quien registra.
    e = mapper.fill_to_execution(fill())
    assert e.time.tzinfo is not None
    assert e.time.utcoffset() == timedelta(0)
    assert e.time == datetime(2026, 8, 7, 15, 45, 30, tzinfo=UTC)


# --- Historico completo --------------------------------------------------


def test_historico_ordena_de_mas_reciente_a_mas_antigua():
    base = datetime(2026, 8, 7, 15, 0, 0, tzinfo=UTC)
    fills = [
        fill(exec_=ejecucion(momento=base, order_id=1)),
        fill(exec_=ejecucion(momento=base + timedelta(hours=2), order_id=2)),
        fill(exec_=ejecucion(momento=base + timedelta(hours=1), order_id=3)),
    ]
    h = mapper.fills_to_history(fills, "DUN684545")
    assert [e.order_id for e in h.executions] == [2, 3, 1]


def test_historico_vacio_conserva_la_ventana():
    # Una lista vacia significa "no has operado hoy", NO "la ventana es
    # otra". El alcance viaja en la respuesta para que el cliente pueda
    # distinguirlo sin cablearlo a mano.
    h = mapper.fills_to_history([], "DUN684545")
    assert h.executions == []
    assert h.window == "current_day"
    assert h.account_id == "DUN684545"


def test_historico_sella_la_hora_de_consulta_en_utc():
    h = mapper.fills_to_history([], "DUN684545")
    assert h.retrieved_at.tzinfo is not None
    assert h.retrieved_at.utcoffset() == timedelta(0)


def test_una_orden_troceada_produce_varias_ejecuciones():
    # Una orden que el mercado parte en trozos son varias ejecuciones con
    # el mismo orderId. El historico las lista sueltas: agrupar, si hace
    # falta, es cosa de la capa de arriba.
    base = datetime(2026, 8, 7, 15, 0, 0, tzinfo=UTC)
    fills = [
        fill(exec_=ejecucion(shares=60.0, momento=base, order_id=7)),
        fill(exec_=ejecucion(shares=40.0, momento=base + timedelta(seconds=2), order_id=7)),
    ]
    h = mapper.fills_to_history(fills)
    assert len(h.executions) == 2
    assert {e.order_id for e in h.executions} == {7}
    assert sum(e.quantity for e in h.executions) == pytest.approx(100.0)
