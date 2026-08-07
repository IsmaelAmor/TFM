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


# --- rendimiento_anualizado ----------------------------------------------


def test_rendimiento_anualizado_es_la_media_por_252():
    # Diez rendimientos de 0,001 -> media 0,001 -> 0,001 * 252 = 0,252.
    # Se multiplica y no se compone porque los logaritmicos son aditivos.
    assert rs.rendimiento_anualizado([0.001] * 10) == pytest.approx(0.252)


def test_rendimiento_anualizado_serie_vacia_es_none():
    # Sin ningun salto medido no hay rendimiento que anualizar. None y no
    # cero: "sin datos" es informacion distinta de "no se ha movido".
    assert rs.rendimiento_anualizado([]) is None


# --- ratio_sharpe --------------------------------------------------------


def test_sharpe_sin_tasa_es_rendimiento_entre_volatilidad():
    # Valor esperado desde la definicion, no llamando a las funciones que
    # se estan probando: (media * 252) / (stdev * sqrt(252)).
    r = [0.004, -0.002, 0.010, -0.006, 0.003, 0.001]
    esperado = (statistics.fmean(r) * 252) / (statistics.stdev(r) * math.sqrt(252))
    assert rs.ratio_sharpe(r) == pytest.approx(esperado)


def test_sharpe_convierte_la_tasa_a_continua():
    # La prueba que caza el fallo silencioso: la tasa entra como simple
    # (0,03 = 3 %) y debe restarse como ln(1,03) = 0,029559, no como 0,03.
    # Restar la simple daria un numero plausible pero equivocado.
    r = [0.004, -0.002, 0.010, -0.006, 0.003, 0.001]
    numerador = statistics.fmean(r) * 252 - math.log(1.03)
    esperado = numerador / (statistics.stdev(r) * math.sqrt(252))
    assert rs.ratio_sharpe(r, 0.03) == pytest.approx(esperado)


def test_sharpe_baja_al_exigir_tasa_libre_de_riesgo():
    # El activo sin riesgo es el listo a batir: cuanto mas renta, menos
    # merito tiene la cartera y menor es el Sharpe.
    r = [0.004, -0.002, 0.010, -0.006, 0.003, 0.001]
    assert rs.ratio_sharpe(r, 0.03) < rs.ratio_sharpe(r, 0.0)


def test_sharpe_sube_si_sube_el_rendimiento_con_igual_riesgo():
    # Sumar una constante a cada rendimiento desplaza la media y deja la
    # desviacion tipica intacta: mismo riesgo, mas rentabilidad, mejor
    # Sharpe. Es la propiedad que define la metrica.
    base = [0.001, 0.020, -0.015, 0.008, -0.004]
    mejor = [x + 0.005 for x in base]

    assert statistics.stdev(mejor) == pytest.approx(statistics.stdev(base))
    assert rs.ratio_sharpe(mejor) > rs.ratio_sharpe(base)


def test_sharpe_volatilidad_cero_es_none():
    # Rendimientos identicos -> desviacion cero -> division por cero. Un
    # Sharpe infinito seria un dato falso, no un dato excelente.
    assert rs.ratio_sharpe([0.001] * 10) is None


def test_sharpe_serie_corta_es_none():
    assert rs.ratio_sharpe([0.004]) is None


def test_sharpe_rechaza_tasa_imposible():
    # Una tasa de -100 % o menos rompe el logaritmo. Es un error de
    # programacion, no un dato posible: se lanza en vez de devolver None.
    with pytest.raises(ValueError):
        rs.ratio_sharpe([0.004, -0.002, 0.010], -1.0)


# --- indice_herfindahl y posiciones_efectivas ----------------------------


def test_herfindahl_cartera_uniforme_es_uno_partido_n():
    # Cinco posiciones al 20 %: 5 * 0,2^2 = 0,2 = 1/5. Es el minimo que
    # puede alcanzar el indice con cinco posiciones.
    assert rs.indice_herfindahl([0.2] * 5) == pytest.approx(0.2)


def test_herfindahl_posicion_unica_es_uno():
    # Todo el dinero en un valor: concentracion maxima.
    assert rs.indice_herfindahl([1.0]) == pytest.approx(1.0)


def test_herfindahl_cartera_vacia_es_none():
    # La concentracion de nada no es cero: no esta definida.
    assert rs.indice_herfindahl([]) is None


def test_concentrar_sube_el_indice_y_baja_las_posiciones_efectivas():
    # La aserción que demuestra que la metrica mide lo que dice medir.
    # Misma cartera de cuatro valores, repartida y concentrada.
    repartida = [0.25, 0.25, 0.25, 0.25]
    concentrada = [0.70, 0.10, 0.10, 0.10]

    assert rs.indice_herfindahl(concentrada) > rs.indice_herfindahl(repartida)
    assert rs.posiciones_efectivas(concentrada) < rs.posiciones_efectivas(repartida)


def test_posiciones_efectivas_de_cartera_uniforme_es_el_numero_de_posiciones():
    # Ocho posiciones iguales equivalen exactamente a ocho posiciones.
    # Es lo que hace la cifra legible sin saber que es un Herfindahl.
    assert rs.posiciones_efectivas([0.125] * 8) == pytest.approx(8.0)


def test_posiciones_efectivas_cartera_vacia_es_none():
    assert rs.posiciones_efectivas([]) is None
