"""Pruebas de las métricas de riesgo (Fase 5), sin Gateway.

Las funciones de risk_service son puras, así que se prueban con series
inventadas y resultados calculados a mano. No se comprueba una función
contra sí misma: los valores esperados salen de la definición matemática,
no de ejecutar el código.
"""

import math
import statistics

import pytest

from app.services import risk_service as rs


# --- rendimientos_log ----------------------------------------------------

def test_rendimientos_log_cuenta_correcta():
    # n cierres -> n-1 rendimientos.
    cierres = [100.0, 110.0, 105.0, 120.0]
    assert len(rs.rendimientos_log(cierres)) == 3


def test_rendimientos_log_valor_conocido():
    # ln(110/100) = ln(1.1). Un solo salto, valor comprobable a mano.
    r = rs.rendimientos_log([100.0, 110.0])
    assert r[0] == pytest.approx(math.log(1.1))


def test_rendimientos_log_serie_corta_es_vacia():
    # Con menos de dos cierres no hay ningún salto que medir.
    assert rs.rendimientos_log([100.0]) == []
    assert rs.rendimientos_log([]) == []


def test_rendimientos_log_simetria():
    # Subir de 100 a 110 y volver a 100 deja rendimientos opuestos: los
    # logarítmicos son simétricos, a diferencia de los simples.
    r = rs.rendimientos_log([100.0, 110.0, 100.0])
    assert r[0] == pytest.approx(-r[1])


# --- volatilidad_anualizada ---------------------------------------------

def test_volatilidad_usa_desviacion_muestral_n_menos_1():
    # La clave: stdev (n-1), no pstdev (n). Se comprueba reproduciendo el
    # cálculo con statistics.stdev y el factor de anualización a mano.
    cierres = [100.0, 102.0, 101.0, 104.0, 103.0, 106.0]
    r = rs.rendimientos_log(cierres)
    esperado = statistics.stdev(r) * math.sqrt(rs.DIAS_HABILES_ANO)
    assert rs.volatilidad_anualizada(r) == pytest.approx(esperado)


def test_volatilidad_factor_de_anualizacion_es_raiz_252():
    # Con una desviación diaria conocida, la anualizada es esa por raíz de
    # 252. Se fabrican rendimientos de desviación muestral exactamente 0.01.
    r = [0.01, -0.01]
    # se comprueba contra la definición, sin suponer el número:
    esperado = statistics.stdev(r) * math.sqrt(252)
    assert rs.volatilidad_anualizada(r) == pytest.approx(esperado)


def test_volatilidad_insuficientes_datos_es_none():
    # Menos de dos rendimientos: la desviación muestral no está definida.
    assert rs.volatilidad_anualizada([]) is None
    assert rs.volatilidad_anualizada([0.01]) is None


def test_volatilidad_serie_plana_es_cero():
    # Precios que no se mueven: rendimientos todos cero, volatilidad cero.
    # Distinto de None: aquí sí hay datos, y dicen que no hay riesgo.
    r = rs.rendimientos_log([100.0, 100.0, 100.0])
    assert rs.volatilidad_anualizada(r) == pytest.approx(0.0)


# --- maximo_drawdown -----------------------------------------------------

def test_drawdown_caida_simple():
    # De 100 baja a 60: caída de 40/100 = 0.40.
    assert rs.maximo_drawdown([100.0, 60.0]) == pytest.approx(0.40)


def test_drawdown_pico_intermedio():
    # Sube a 120 (nuevo pico) y luego cae a 90: el peor drawdown se mide
    # desde 120, no desde el inicio. (120-90)/120 = 0.25.
    assert rs.maximo_drawdown([100.0, 120.0, 90.0, 110.0]) == pytest.approx(0.25)


def test_drawdown_serie_creciente_es_cero():
    # Una serie que solo sube nunca cae de su pico.
    assert rs.maximo_drawdown([100.0, 101.0, 105.0, 110.0]) == pytest.approx(0.0)


def test_drawdown_serie_vacia_es_none():
    assert rs.maximo_drawdown([]) is None


def test_drawdown_recuperacion_no_borra_el_peor():
    # Cae a 50 (drawdown 0.50), se recupera del todo y sigue subiendo. El
    # máximo drawdown histórico sigue siendo 0.50 aunque acabe en máximos.
    assert rs.maximo_drawdown([100.0, 50.0, 100.0, 200.0]) == pytest.approx(0.50)


# --- Agregación de cartera ----------------------------------------------

def test_covarianza_exige_igual_longitud():
    with pytest.raises(ValueError):
        rs.covarianza_muestral([0.1, 0.2], [0.1])


def test_correlacion_de_serie_consigo_misma_es_uno():
    r = [0.01, -0.02, 0.03, -0.01, 0.02]
    assert rs.correlacion(r, r) == pytest.approx(1.0)


def test_correlacion_inversa_perfecta_es_menos_uno():
    # Una serie y su opuesta se mueven exactamente al revés.
    r = [0.01, -0.02, 0.03, -0.01, 0.02]
    opuesta = [-x for x in r]
    assert rs.correlacion(r, opuesta) == pytest.approx(-1.0)


def test_correlacion_serie_plana_es_none():
    # Una serie sin variación no tiene correlación definida (σ=0).
    r = [0.01, -0.02, 0.03]
    plana = [0.0, 0.0, 0.0]
    assert rs.correlacion(r, plana) is None


def test_matriz_correlacion_diagonal_es_uno_y_simetrica():
    a = [0.01, -0.02, 0.03, -0.01]
    b = [0.02, 0.01, -0.01, 0.00]
    m = rs.matriz_correlacion([a, b])
    assert m[0][0] == pytest.approx(1.0)
    assert m[1][1] == pytest.approx(1.0)
    assert m[0][1] == pytest.approx(m[1][0])  # simétrica


def test_volatilidad_cartera_exige_un_peso_por_serie():
    with pytest.raises(ValueError):
        rs.volatilidad_cartera([1.0], [[0.1, 0.2], [0.1, 0.2]])


def test_dos_posiciones_identicas_no_diversifican():
    # Si las dos posiciones son la misma serie, no hay nada que compensar:
    # la volatilidad de la cartera IGUALA la suma ponderada. Cero beneficio.
    r = [0.01, -0.02, 0.03, -0.01, 0.02]
    pesos = [0.5, 0.5]
    conjunta = rs.volatilidad_cartera(pesos, [r, r])
    suma = rs.volatilidad_suma_ponderada(pesos, [r, r])
    assert conjunta == pytest.approx(suma)


def test_diversificacion_reduce_la_volatilidad():
    # EL ARGUMENTO CENTRAL. Dos series que no van a la vez: la volatilidad
    # de la cartera queda ESTRICTAMENTE por debajo de la suma ponderada.
    # Esa diferencia es el beneficio de diversificación.
    a = [0.01, -0.02, 0.03, -0.01, 0.02, -0.03]
    b = [-0.01, 0.02, -0.02, 0.01, -0.02, 0.03]  # se mueve casi al revés
    pesos = [0.5, 0.5]
    conjunta = rs.volatilidad_cartera(pesos, [a, b])
    suma = rs.volatilidad_suma_ponderada(pesos, [a, b])
    assert conjunta is not None and suma is not None
    assert conjunta < suma


def test_volatilidad_cartera_una_sola_posicion_iguala_la_individual():
    # Con una única posición al 100 %, la fórmula de cartera debe dar
    # exactamente la volatilidad de esa posición: caso límite de control.
    r = [0.01, -0.02, 0.03, -0.01, 0.02]
    conjunta = rs.volatilidad_cartera([1.0], [r])
    individual = rs.volatilidad_anualizada(r)
    assert conjunta == pytest.approx(individual)


def test_volatilidad_cartera_serie_corta_es_none():
    assert rs.volatilidad_cartera([1.0], [[0.01]]) is None
