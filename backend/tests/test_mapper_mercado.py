"""Pruebas del mapper de instrumentos y cotizaciones.

Se separan de test_mapper.py porque cubren otra fuente de datos: aquellas
prueban lo que llega por el canal de cuenta (reqAccountUpdates), estas lo
que llega por busqueda de simbolos y por datos de mercado.

Los dobles reproducen estructuras reales observadas en DUN684545 el
04/08/2026 con scripts/sondea_instrumentos.py.

Ejecutar desde backend/ con el venv activado:
    python -m pytest
"""

from types import SimpleNamespace

import pytest

from app.broker import mapper


def descripcion(symbol="AMZN", sec_type="STK", currency="USD",
                primary="NASDAQ", con_id=3691937, description="AMAZON.COM INC"):
    """Doble de un ContractDescription de reqMatchingSymbols."""
    return SimpleNamespace(
        derivativeSecTypes=["CFD", "OPT"],
        contract=SimpleNamespace(
            conId=con_id,
            symbol=symbol,
            secType=sec_type,
            currency=currency,
            primaryExchange=primary,
            description=description,
        ),
    )


def ticker(last=279.35, close=284.02, bid=279.18, ask=279.5,
           volume=3061.0, tipo=3, symbol="AMZN"):
    """Doble de un Ticker de ib_async con datos retrasados."""
    return SimpleNamespace(
        contract=SimpleNamespace(
            conId=3691937, symbol=symbol, currency="USD",
            primaryExchange="NASDAQ", exchange="SMART",
        ),
        last=last, close=close, bid=bid, ask=ask, volume=volume,
        marketDataType=tipo,
        delayedLastTimestamp=None,
        time=None,
    )


# ---------------------------------------------------------------------
# Busqueda de instrumentos
# ---------------------------------------------------------------------


def test_traduce_una_descripcion_completa():
    [inst] = mapper.contract_descriptions_to_instruments([descripcion()])

    assert inst.con_id == 3691937
    assert inst.symbol == "AMZN"
    assert inst.name == "AMAZON.COM INC"
    assert inst.currency == "USD"
    assert inst.exchange == "NASDAQ"


def test_descarta_lo_que_no_es_accion_ni_etf():
    """Decision de alcance: la cartera solo opera STK."""
    entradas = [
        descripcion(),
        descripcion(symbol="SMHLX", sec_type="FUND", primary="FUNDSERV", con_id=141406975),
        descripcion(symbol="SMH.IV", sec_type="IND", primary="PSE", con_id=134039480),
    ]

    salida = mapper.contract_descriptions_to_instruments(entradas)

    assert [i.symbol for i in salida] == ["AMZN"]


def test_descarta_los_bonos_sin_simbolo():
    """Estructura real: los BOND llegan sin symbol y con conId -1."""
    bono = descripcion(symbol="", sec_type="BOND", primary="", con_id=-1)
    assert mapper.contract_descriptions_to_instruments([bono]) == []


def test_descarta_los_artefactos_de_operaciones_societarias():
    """El artefacto societario se descarta por su mercado, no por la divisa.

    IBE.CASH y compania son STK, pero no se pueden comprar: aparecen en
    CORPACT al buscar. Se prueba con valores en USD a proposito, para que
    el filtro de divisa (que descartaria IBE por estar en EUR) no tape lo
    que aqui se verifica: que el filtro de mercado funciona por si solo.
    """
    entradas = [
        descripcion(symbol="ACME", currency="USD", primary="NASDAQ", con_id=1001,
                    description="ACME CORP"),
        descripcion(symbol="ACME.CASH", currency="USD", primary="CORPACT", con_id=1002,
                    description="ACME CORP"),
        descripcion(symbol="ACME00.OLD", currency="USD", primary="VALUE", con_id=1003,
                    description="ACME CORP"),
    ]

    salida = mapper.contract_descriptions_to_instruments(entradas)

    assert [i.symbol for i in salida] == ["ACME"]


def test_aguanta_un_contrato_sin_campo_description():
    """El campo es reciente en la API de TWS: si falta, el buscador sigue."""
    d = descripcion()
    del d.contract.description

    [inst] = mapper.contract_descriptions_to_instruments([d])

    assert inst.symbol == "AMZN"
    assert inst.name == ""


# ---------------------------------------------------------------------
# _precio
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        (279.35, 279.35),
        (0.0, 0.0),  # un cero puede ser un volumen legitimo
        (float("nan"), None),  # IBDefaults.unset
        (-1, None),  # IBDefaults.emptyPrice
        (None, None),
        ("no es un numero", None),
    ],
)
def test_precio_traduce_los_dos_vacios_de_ib(entrada, esperado):
    assert mapper._precio(entrada) == esperado


# ---------------------------------------------------------------------
# ticker_to_quote
# ---------------------------------------------------------------------


def test_traduce_una_cotizacion_completa():
    q = mapper.ticker_to_quote(ticker())

    assert q.con_id == 3691937
    assert q.symbol == "AMZN"
    assert q.last == 279.35
    assert q.close == 284.02
    assert q.bid == 279.18
    assert q.ask == 279.5


def test_calcula_la_variacion_sobre_el_cierre_anterior():
    q = mapper.ticker_to_quote(ticker(last=279.35, close=284.02))

    assert q.change == pytest.approx(-4.67)
    assert q.change_pct == pytest.approx(-1.6443, abs=1e-4)


def test_sin_precio_no_hay_variacion_inventada():
    """Mercado cerrado: mejor un null que un cero que parece un precio."""
    q = mapper.ticker_to_quote(ticker(last=float("nan")))

    assert q.last is None
    assert q.change is None
    assert q.change_pct is None


def test_marca_el_dato_como_retrasado():
    assert mapper.ticker_to_quote(ticker(tipo=3)).delayed is True
    assert mapper.ticker_to_quote(ticker(tipo=4)).delayed is True
    assert mapper.ticker_to_quote(ticker(tipo=1)).delayed is False

def test_descarta_lo_que_no_cotiza_en_la_divisa_operativa():
    """Restriccion de divisa (IB_TRADING_CURRENCY, USD por defecto).

    "AMZN" cotiza en varias plazas y divisas; operar en varias meteria
    riesgo de cambio en cada orden. El buscador solo ofrece la divisa
    operativa. Aqui: el AMZN en USD pasa, el mismo en EUR se descarta.
    """
    entradas = [
        descripcion(symbol="AMZN", currency="USD", primary="NASDAQ", con_id=3691937),
        descripcion(symbol="AMZN", currency="EUR", primary="IBIS", con_id=502092331),
    ]

    salida = mapper.contract_descriptions_to_instruments(entradas)

    assert [i.currency for i in salida] == ["USD"]
    assert len(salida) == 1