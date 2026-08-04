"""Pruebas de la validacion de ordenes (T35).

Cubren dos cosas distintas: la traduccion del OrderState de IB (mapper) y
las reglas propias (order_service.evaluar_orden). Las dos se prueban sin
Gateway porque evaluar_orden es una funcion pura y el mapper solo recibe
dobles.

Los dobles reproducen valores reales observados en DUN684545 el 04/08/2026
con scripts/sondea_ordenes.py, incluido el centinela de IB.

Ejecutar desde backend/ con el venv activado:
    python -m pytest
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.broker import mapper
from app.models.order import BrokerPreview, OrderRequest
from app.models.quote import Quote
from app.services import order_service

CENTINELA = 1.7976931348623157e308


def order_state(commission=1.00003, commission_currency="USD", status="PreSubmitted"):
    """Doble de un OrderState. Margenes como cadena, comisiones como float."""
    return SimpleNamespace(
        status=status,
        commission=commission,
        commissionCurrency=commission_currency,
        minCommission=CENTINELA,
        maxCommission=CENTINELA,
        initMarginChange="797.5099999999984",
        maintMarginChange="725.0199999999968",
        equityWithLoanChange="-1.1399999998975545",
        warningText="",
    )


def contrato(con_id=3691937, symbol="AMZN", currency="USD"):
    return SimpleNamespace(
        conId=con_id, symbol=symbol, currency=currency, exchange="SMART"
    )


def quote(last=278.72, bid=278.71, ask=279.0, close=284.02, delayed=True):
    return Quote(
        con_id=3691937, symbol="AMZN", currency="USD", exchange="NASDAQ",
        last=last, bid=bid, ask=ask, close=close,
        delayed=delayed, market_data_type=3,
        received_at=datetime.now(timezone.utc),
    )


def preview(aceptada=True, commission=1.00003, mensaje=""):
    return BrokerPreview(
        accepted_by_broker=aceptada,
        broker_status="PreSubmitted",
        broker_message=mensaje,
        commission=commission,
        commission_currency="USD" if commission is not None else "",
        con_id=3691937, symbol="AMZN", currency="USD", exchange="SMART",
    )


TIPOS = {"EUR": 1.0, "USD": 0.8688022}


def evaluar(req, cash=886855.36, position=0.0, pv=None, q=None):
    return order_service.evaluar_orden(
        req=req,
        preview=pv or preview(),
        quote=q or quote(),
        base_currency="EUR",
        rates=TIPOS,
        cash=cash,
        position_quantity=position,
    )


# ---------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------


def test_traduce_un_orderstate_aceptado():
    p = mapper.order_state_to_preview(order_state(), contrato(), [])

    assert p.accepted_by_broker is True
    assert p.commission == pytest.approx(1.00003)
    assert p.commission_currency == "USD"
    assert p.symbol == "AMZN"


def test_el_centinela_de_ib_se_traduce_a_none():
    """1.79e308 no es un importe: es como IB dice "sin dato"."""
    p = mapper.order_state_to_preview(
        order_state(commission=CENTINELA, commission_currency=""), contrato(), []
    )
    assert p.commission is None


def test_conserva_los_negativos_de_los_margenes():
    """equityWithLoanChange es negativo en una compra normal.

    Si se pasara por _precio, que descarta negativos, se perderia el dato.
    """
    p = mapper.order_state_to_preview(order_state(), contrato(), [])
    assert p.equity_with_loan_change == pytest.approx(-1.14, abs=0.01)


def test_el_error_201_manda_sobre_el_status():
    """La trampa central de T35.

    IB devuelve status 'PreSubmitted' tambien cuando rechaza. El veredicto
    sale del error 201, no del campo status.
    """
    errores = [(201, "Orden rechazada. Motivo:YOUR ORDER IS NOT ACCEPTED...")]
    p = mapper.order_state_to_preview(order_state(), contrato(), errores)

    assert p.accepted_by_broker is False
    assert p.error_code == 201
    assert p.broker_status == "PreSubmitted"
    assert "NOT ACCEPTED" in p.broker_message


def test_ignora_los_errores_que_no_son_rechazos():
    """El 10167 es el aviso de datos retrasados, no un rechazo."""
    p = mapper.order_state_to_preview(order_state(), contrato(), [(10167, "delayed")])
    assert p.accepted_by_broker is True


def test_sin_respuesta_no_es_un_si():
    p = mapper.order_state_to_preview(None, contrato(), [])
    assert p.accepted_by_broker is False
    assert "no respondio" in p.broker_message


# ---------------------------------------------------------------------
# Reglas propias
# ---------------------------------------------------------------------


def test_acepta_una_compra_que_cabe_en_el_efectivo():
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10))

    assert v.accepted is True
    assert v.reasons == []
    assert v.price_source == "ask"
    # 10 x 279.00 x 1.02 x 0.8688 mas comision, del orden de 2.470 EUR
    assert 2400 < v.total_base < 2550
    assert v.cash_after < v.cash_available


def test_rechaza_la_compra_que_no_cabe_en_el_efectivo():
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10), cash=1000.0)

    assert v.accepted is False
    assert any("efectivo" in m for m in v.reasons)


def test_valida_contra_efectivo_y_no_contra_poder_de_compra():
    """La regla de alcance, en una prueba.

    Con 2.000 EUR de efectivo IB aceptaria de sobra 10 AMZN, porque solo
    exige un 33 % de margen. La aplicacion lo rechaza igual.
    """
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10), cash=2000.0)

    assert v.broker.accepted_by_broker is True
    assert v.accepted is False


def test_la_compra_de_mercado_lleva_colchon_y_la_limitada_no():
    mercado = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10))
    limitada = evaluar(
        OrderRequest(con_id=3691937, action="BUY", order_type="LMT",
                     quantity=10, limit_price=279.0)
    )

    assert mercado.buffer_pct == pytest.approx(0.02)
    assert limitada.buffer_pct == 0.0
    assert limitada.price_source == "limite"
    assert limitada.estimated_cost < mercado.estimated_cost


def test_rechaza_vender_mas_de_lo_que_hay():
    v = evaluar(OrderRequest(con_id=3691937, action="SELL", quantity=10), position=4)

    assert v.accepted is False
    assert any("descubierto" in m for m in v.reasons)


def test_acepta_vender_lo_que_hay_y_suma_el_ingreso():
    v = evaluar(OrderRequest(con_id=3691937, action="SELL", quantity=4), position=4)

    assert v.accepted is True
    assert v.price_source == "bid"
    assert v.cash_after > v.cash_available


def test_convierte_el_coste_a_divisa_base():
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10))

    assert v.currency == "USD"
    assert v.base_currency == "EUR"
    assert v.fx_rate == pytest.approx(0.8688022)
    assert v.estimated_cost_base == pytest.approx(v.estimated_cost * 0.8688022)


def test_sin_comision_de_ib_se_estima_el_minimo():
    v = evaluar(
        OrderRequest(con_id=3691937, action="BUY", quantity=10),
        pv=preview(commission=None),
    )

    assert v.commission == pytest.approx(order_service.COMISION_DE_RESERVA)
    assert any("comision" in a for a in v.warnings)


def test_el_rechazo_del_broker_tumba_la_orden():
    v = evaluar(
        OrderRequest(con_id=3691937, action="BUY", quantity=10),
        pv=preview(aceptada=False, mensaje="Orden rechazada. Motivo:margen"),
    )

    assert v.accepted is False
    assert any("margen" in m for m in v.reasons)


def test_sin_precio_no_se_puede_validar_una_orden_de_mercado():
    ciega = quote(last=None, bid=None, ask=None, close=None)
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10), q=ciega)

    assert v.accepted is False
    assert any("precio" in m for m in v.reasons)


def test_avisa_cuando_solo_hay_cierre_anterior():
    cerrado = quote(last=None, bid=None, ask=None, close=284.02)
    v = evaluar(OrderRequest(con_id=3691937, action="BUY", quantity=10), q=cerrado)

    assert v.price_source == "close"
    assert any("cerrado" in a for a in v.warnings)


def test_una_limitada_sin_precio_no_se_admite():
    with pytest.raises(ValueError):
        OrderRequest(con_id=3691937, action="BUY", order_type="LMT", quantity=10)


def test_una_de_mercado_con_precio_limite_no_se_admite():
    with pytest.raises(ValueError):
        OrderRequest(con_id=3691937, action="BUY", quantity=10, limit_price=279.0)