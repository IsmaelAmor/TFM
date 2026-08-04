"""Pruebas del mapeo de ordenes enviadas (T36).

Cubren mapper.estado_de_orden y mapper.trade_to_result con Trades
simulados. Todo el mapper es duck typing, asi que un SimpleNamespace con
los campos justos basta: no hace falta ib_async ni el Gateway levantado.

Las formas de los objetos simulados salen de lo verificado el 04/08/2026
con scripts/sondea_ordenes_envio.py contra DUN684545, no de la
documentacion.
"""

from types import SimpleNamespace as NS

import pytest

from app.broker import mapper


# ---------------------------------------------------------------------
# Fabricas de Trades simulados
# ---------------------------------------------------------------------

def _fill(commission, currency="USD"):
    return NS(commissionReport=NS(commission=commission, currency=currency))


def _trade(status, *, filled=0.0, remaining=1.0, avg=0.0,
           order_type="MKT", lmt=None, fills=()):
    return NS(
        order=NS(
            orderId=11,
            permId=1188970646,
            action="BUY",
            orderType=order_type,
            totalQuantity=1.0,
            lmtPrice=lmt,
        ),
        orderStatus=NS(
            status=status,
            filled=filled,
            remaining=remaining,
            avgFillPrice=avg,
        ),
        contract=NS(conId=3691937, symbol="AMZN", currency="USD", exchange="SMART"),
        fills=list(fills),
    )


# ---------------------------------------------------------------------
# estado_de_orden
# ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "status, esperado",
    [
        ("Filled", "ejecutada"),
        ("Submitted", "activa"),
        ("PreSubmitted", "activa"),
        ("PendingSubmit", "activa"),
        ("ApiPending", "activa"),
        ("Inactive", "rechazada"),
        ("ValidationError", "rechazada"),
        ("Cancelled", "cancelada"),
        ("ApiCancelled", "cancelada"),
        ("PendingCancel", "cancelada"),
    ],
)
def test_traduccion_de_cada_status(status, esperado):
    assert mapper.estado_de_orden(status) == esperado


def test_status_desconocido_se_trata_como_viva():
    """Ante la duda, 'activa': es el error menos danino de los tres."""
    assert mapper.estado_de_orden("EstadoQueIbInventeManana") == "activa"


# ---------------------------------------------------------------------
# trade_to_result: orden ejecutada
# ---------------------------------------------------------------------

def test_mkt_ejecutada_trae_comision_real_y_precio_medio():
    trade = _trade(
        "Filled", filled=1.0, remaining=0.0, avg=276.8,
        fills=(_fill(1.000003),),
    )
    r = mapper.trade_to_result(trade)

    assert r.estado == "ejecutada"
    assert r.filled_quantity == 1.0
    assert r.remaining_quantity == 0.0
    assert r.avg_fill_price == pytest.approx(276.8)
    assert r.commission == pytest.approx(1.000003)
    assert r.commission_currency == "USD"
    assert r.order_id == 11
    assert r.perm_id == 1188970646


def test_comision_suma_todas_las_ejecuciones():
    """Una orden puede llenarse en varios fills; la comision es la suma."""
    trade = _trade(
        "Filled", filled=2.0, remaining=0.0, avg=276.9,
        fills=(_fill(1.0), _fill(1.5)),
    )
    r = mapper.trade_to_result(trade)

    assert r.commission == pytest.approx(2.5)


# ---------------------------------------------------------------------
# trade_to_result: orden viva
# ---------------------------------------------------------------------

def test_lmt_viva_no_tiene_comision_ni_precio_medio():
    """Sin ejecucion, la comision es None (aun no se ha pagado nada)."""
    trade = _trade(
        "Submitted", filled=0.0, remaining=1.0, avg=0.0,
        order_type="LMT", lmt=193.96,
    )
    r = mapper.trade_to_result(trade)

    assert r.estado == "activa"
    assert r.commission is None
    assert r.avg_fill_price is None       # 0.0 es "sin ejecucion", no un precio
    assert r.limit_price == pytest.approx(193.96)


def test_mkt_no_expone_precio_limite():
    trade = _trade("Filled", filled=1.0, remaining=0.0, avg=276.8, lmt=None)
    r = mapper.trade_to_result(trade)

    assert r.limit_price is None


# ---------------------------------------------------------------------
# trade_to_result: orden rechazada
# ---------------------------------------------------------------------

def test_inactive_es_rechazada_y_limpia_el_html_del_motivo():
    """El motivo del 201 llega con <br> incrustados; deben desaparecer."""
    trade = _trade("Inactive", filled=0.0, remaining=500000.0, avg=0.0)
    mensaje = (
        "No podemos aceptar su orden. Sus fondos disponibles no son "
        "suficientes<br> para cubrir el cambio en los requisitos<br> de margen."
    )
    r = mapper.trade_to_result(trade, error_code=201, error_message=mensaje)

    assert r.estado == "rechazada"
    assert r.error_code == 201
    assert "<br>" not in r.broker_message
    assert "  " not in r.broker_message   # no quedan dobles espacios
    assert r.broker_message.startswith("No podemos aceptar su orden")


def test_rechazada_sin_mensaje_no_revienta():
    """Si el motivo no llego a capturarse, el resultado sigue siendo valido."""
    trade = _trade("Inactive", filled=0.0, remaining=1.0, avg=0.0)
    r = mapper.trade_to_result(trade)

    assert r.estado == "rechazada"
    assert r.broker_message == ""


# ---------------------------------------------------------------------
# trade_to_result: orden cancelada
# ---------------------------------------------------------------------

def test_cancelled_es_cancelada():
    trade = _trade("Cancelled", filled=0.0, remaining=1.0, avg=0.0)
    r = mapper.trade_to_result(trade)

    assert r.estado == "cancelada"
