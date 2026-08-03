"""Pruebas de app.broker.mapper.

Se prueba el mapper y no los routers por una razon concreta: es la unica
pieza del backend donde vive el conocimiento sobre la forma exacta de los
datos de Interactive Brokers, y es la unica que puede romperse en silencio.
Si ib_async renombra un campo, la aplicacion no falla: devuelve ceros. Un
error asi no se ve en pantalla, se ve aqui.

Ademas es funcion pura: no necesita IB Gateway levantado ni red, asi que
estas pruebas se ejecutan siempre, tambien con el mercado cerrado.

Ejecutar desde backend/ con el venv activado:
    python -m pytest
"""

from types import SimpleNamespace

import pytest

from app.broker import mapper

# Tipo real de DUN684545 el 03/08/2026. Se usa en varias pruebas.
USD_EUR = 0.8693308


# ---------------------------------------------------------------------
# Utilidades: dobles de los objetos de ib_async
# ---------------------------------------------------------------------


def contrato(symbol="AMZN", sec_type="STK", currency="USD", primary="NASDAQ", exchange="SMART"):
    """Doble de un Contract de ib_async."""
    return SimpleNamespace(
        symbol=symbol,
        secType=sec_type,
        currency=currency,
        primaryExchange=primary,
        exchange=exchange,
    )


def item(
    symbol="AMZN",
    position=100.0,
    average_cost=229.62,
    market_price=284.86,
    market_value=28486.20,
    unrealized=5524.20,
    realized=0.0,
    **kwargs,
):
    """Doble de un PortfolioItem de ib_async."""
    return SimpleNamespace(
        contract=contrato(symbol=symbol, **kwargs),
        position=position,
        averageCost=average_cost,
        marketPrice=market_price,
        marketValue=market_value,
        unrealizedPNL=unrealized,
        realizedPNL=realized,
    )


def valor(tag, value, currency="EUR"):
    """Doble de un AccountValue de ib_async."""
    return SimpleNamespace(tag=tag, value=value, currency=currency)


# ---------------------------------------------------------------------
# _to_float
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("1234.56", 1234.56),  # IB manda importes como cadena
        (42, 42.0),
        ("", 0.0),  # y a veces vacios
        (None, 0.0),
        ("no es un numero", 0.0),
    ],
)
def test_to_float_tolera_lo_que_manda_ib(entrada, esperado):
    assert mapper._to_float(entrada) == esperado


# ---------------------------------------------------------------------
# portfolio_item_to_position
# ---------------------------------------------------------------------


def test_usa_average_cost_y_no_avg_cost():
    """La trampa documentada del 03/08/2026.

    reqPositions llama al campo avgCost y reqAccountUpdates lo llama
    averageCost. Si alguien "corrige" el mapper al nombre equivocado, el
    coste medio se va a cero sin que nada falle. Esta prueba lo impide.
    """
    posicion = mapper.portfolio_item_to_position(item(average_cost=229.62))
    assert posicion.avg_cost == 229.62


def test_traduce_todos_los_campos_de_una_posicion():
    posicion = mapper.portfolio_item_to_position(item())

    assert posicion.symbol == "AMZN"
    assert posicion.sec_type == "STK"
    assert posicion.currency == "USD"
    assert posicion.quantity == 100.0
    assert posicion.market_price == 284.86
    assert posicion.market_value == 28486.20
    assert posicion.unrealized_pnl == 5524.20


def test_prefiere_el_mercado_principal_sobre_smart():
    """SMART es el enrutador de IB, no un mercado. Interesa el real."""
    posicion = mapper.portfolio_item_to_position(item(primary="NASDAQ", exchange="SMART"))
    assert posicion.exchange == "NASDAQ"


def test_cae_a_exchange_si_no_hay_mercado_principal():
    posicion = mapper.portfolio_item_to_position(item(primary="", exchange="SMART"))
    assert posicion.exchange == "SMART"


# ---------------------------------------------------------------------
# account_values_to_fx
# ---------------------------------------------------------------------


def test_extrae_divisa_base_y_tipos_de_cambio():
    """Estructura real observada en DUN684545 el 03/08/2026."""
    values = [
        valor("ExchangeRate", "1.00", "BASE"),
        valor("ExchangeRate", "1.00", "EUR"),
        valor("ExchangeRate", "0.8693308", "USD"),
        valor("NetLiquidation", "1010322.54", "EUR"),
        valor("CashBalance", "886780.2476", "BASE"),
    ]

    base, rates = mapper.account_values_to_fx(values)

    assert base == "EUR"
    assert rates == {"EUR": 1.0, "USD": pytest.approx(USD_EUR)}


def test_la_pseudodivisa_base_nunca_entra_como_divisa():
    """IB usa currency='BASE' para filas consolidadas. No es una divisa."""
    values = [
        valor("ExchangeRate", "1.00", "BASE"),
        valor("ExchangeRate", "1.00", "EUR"),
        valor("NetLiquidation", "100", "EUR"),
    ]

    _, rates = mapper.account_values_to_fx(values)

    assert "BASE" not in rates


def test_deduce_la_base_si_falta_net_liquidation():
    """Respaldo: la divisa base es la que tiene tipo de cambio 1."""
    values = [
        valor("ExchangeRate", "1.00", "USD"),
        valor("ExchangeRate", "1.1503", "EUR"),
    ]

    base, _ = mapper.account_values_to_fx(values)

    assert base == "USD"


# ---------------------------------------------------------------------
# Conversión a divisa base
# ---------------------------------------------------------------------


def test_convierte_los_importes_a_divisa_base():
    posicion = mapper.portfolio_item_to_position(
        item(market_value=28486.20, unrealized=5524.20, average_cost=229.62, position=100),
        base_currency="EUR",
        rates={"USD": USD_EUR},
    )

    assert posicion.currency == "USD"
    assert posicion.market_value == 28486.20  # el nativo no se toca
    assert posicion.fx_rate == pytest.approx(USD_EUR)
    assert posicion.market_value_base == pytest.approx(28486.20 * USD_EUR)
    assert posicion.cost_base == pytest.approx(229.62 * 100 * USD_EUR)
    assert posicion.unrealized_pnl_base == pytest.approx(5524.20 * USD_EUR)


def test_la_divisa_base_no_se_convierte():
    posicion = mapper.portfolio_item_to_position(
        item(currency="EUR", market_value=1000.0),
        base_currency="EUR",
        rates={"USD": USD_EUR},
    )

    assert posicion.fx_rate == 1.0
    assert posicion.market_value_base == 1000.0


def test_divisa_desconocida_no_inventa_un_cambio():
    """Sin tipo para esa divisa se aplica 1: mejor sin convertir que mal."""
    posicion = mapper.portfolio_item_to_position(
        item(currency="JPY", market_value=1000.0),
        base_currency="EUR",
        rates={"USD": USD_EUR},
    )

    assert posicion.fx_rate == 1.0
    assert posicion.market_value_base == 1000.0


def test_sin_divisas_los_importes_base_igualan_a_los_nativos():
    """Cuenta de divisa unica: la conversion es la identidad."""
    posicion = mapper.portfolio_item_to_position(item(market_value=28486.20))

    assert posicion.fx_rate == 1.0
    assert posicion.market_value_base == 28486.20


# ---------------------------------------------------------------------
# portfolio_items_to_portfolio
# ---------------------------------------------------------------------


def test_los_totales_son_la_suma_de_las_posiciones():
    items = [
        item(symbol="AMZN", position=100, average_cost=229.62, market_value=28486.20, unrealized=5524.20),
        item(symbol="NVDA", position=100, average_cost=181.45, market_value=20708.00, unrealized=2563.00),
    ]

    cartera = mapper.portfolio_items_to_portfolio(items, "DUN684545")

    assert cartera.account_id == "DUN684545"
    assert len(cartera.positions) == 2
    assert cartera.total_market_value == pytest.approx(49194.20)
    assert cartera.total_cost == pytest.approx(41107.00)
    assert cartera.total_unrealized_pnl == pytest.approx(8087.20)


def test_los_totales_se_calculan_sobre_importes_ya_convertidos():
    """El orden importa: convertir y luego sumar, nunca al reves.

    Con una posicion en dolares y otra en euros, sumar los importes
    nativos daria un numero sin significado.
    """
    items = [
        item(symbol="AMZN", currency="USD", market_value=10000.0, unrealized=1000.0,
             average_cost=90.0, position=100),
        item(symbol="SAN", currency="EUR", market_value=5000.0, unrealized=500.0,
             average_cost=45.0, position=100),
    ]

    cartera = mapper.portfolio_items_to_portfolio(
        items, "DUN684545", base_currency="EUR", rates={"USD": USD_EUR, "EUR": 1.0}
    )

    assert cartera.base_currency == "EUR"
    assert cartera.total_market_value == pytest.approx(10000.0 * USD_EUR + 5000.0)
    assert cartera.total_unrealized_pnl == pytest.approx(1000.0 * USD_EUR + 500.0)
    # La suma sin convertir habria dado 15000: el error que esto previene.
    assert cartera.total_market_value != pytest.approx(15000.0)


def test_cartera_vacia_no_revienta():
    """Cuenta recien creada o antes de que llegue el canal de cuenta."""
    cartera = mapper.portfolio_items_to_portfolio([], "DUN684545")

    assert cartera.positions == []
    assert cartera.total_market_value == 0.0
    assert cartera.total_cost == 0.0


# ---------------------------------------------------------------------
# account_values_to_summary
# ---------------------------------------------------------------------


def test_lee_las_cuatro_etiquetas_que_interesan():
    values = [
        valor("NetLiquidation", "1010322.54"),
        valor("TotalCashValue", "886780.25"),
        valor("AvailableFunds", "985434.98"),
        valor("BuyingPower", "6569566.52"),
        valor("EtiquetaQueNoUsamos", "999"),
    ]

    resumen = mapper.account_values_to_summary(values, "DUN684545")

    assert resumen.account_id == "DUN684545"
    assert resumen.currency == "EUR"
    assert resumen.net_liquidation == pytest.approx(1010322.54)
    assert resumen.buying_power == pytest.approx(6569566.52)


def test_las_etiquetas_que_falten_valen_cero():
    """IB no siempre manda las cuatro. Mejor un cero que un KeyError."""
    resumen = mapper.account_values_to_summary([valor("NetLiquidation", "100")], "DUN684545")

    assert resumen.net_liquidation == 100.0
    assert resumen.total_cash == 0.0
    assert resumen.available_funds == 0.0
    assert resumen.buying_power == 0.0
