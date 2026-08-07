"""Pruebas del valor en riesgo (VaR histórico y paramétrico).

Series sintéticas, sin Gateway. Lo que se protege aquí no es la aritmética
—que es de manual— sino las tres decisiones que la rodean: el signo, la
conversión de logarítmico a dinero y el negarse a estimar sin muestra.
"""

import math

import pytest

from app.services import risk_service as r


def normalita(n: int = 300) -> list[float]:
    """Serie determinista con dispersión, sin depender de aleatoriedad."""
    return [0.001 * math.sin(i) - 0.0004 * (i % 7) for i in range(n)]


# ---------------------------------------------------------------------
# Convenciones: signo y unidades
# ---------------------------------------------------------------------


def test_el_var_es_una_perdida_positiva():
    """0,03 significa perder el 3 %. Un VaR negativo obligaría a recordar
    el signo en cada consumidor, y alguien acabaría olvidándolo."""
    serie = [-0.02] * 200

    assert r.var_historico(serie, 0.95) > 0
    assert r.var_parametrico(serie, 0.95) > 0


def test_convierte_el_cuantil_logaritmico_a_perdida_real():
    """Hermana de D-21. Un cuantil log de -0,05 es una pérdida del 4,88 %,
    no del 5 %. Publicar el log tal cual da un número plausible y mal."""
    serie = [-0.05] * 200

    assert r.var_historico(serie, 0.95) == pytest.approx(0.048771, abs=1e-6)
    assert r.var_historico(serie, 0.95) != pytest.approx(0.05, abs=1e-4)


def test_una_serie_sin_dias_malos_no_da_perdida_negativa():
    """Si todo sube, la lectura es 'no se espera pérdida', no una pérdida
    de signo cambiado."""
    assert r.var_historico([0.01] * 200, 0.95) == 0.0


# ---------------------------------------------------------------------
# Histórico: cuantil empírico
# ---------------------------------------------------------------------


def test_el_historico_lee_la_cola_real_y_no_la_aplana():
    """Tres desplomes del 9 % en 200 días tienen que aparecer en el VaR
    al 99 % con su tamaño real, sin aplanar: eso es lo que aporta el
    método frente al paramétrico.

    Y de paso fija cuántos hacen falta. Un ÚNICO atípico en 200 días no
    mueve el VaR al 99 %, porque el peor 1 % de 200 días son dos días y
    ahí solo hay uno malo: ese atípico vive en el 0,5 %. No es que el
    cuantil lo ignore, es que la pregunta al 99 % no es esa."""
    serie = [-0.09] * 3 + [0.001] * 197

    assert r.var_historico(serie, 0.99) == pytest.approx(0.086069, abs=1e-5)


def test_interpola_entre_las_dos_observaciones_que_rodean_el_cuantil():
    """Con 101 datos la posición del 99 % cae en 1,0 exacta; con 100 cae
    entre medias. Redondear a la más cercana movería el resultado por un
    artefacto de conteo, no por el riesgo."""
    serie = sorted([-0.10, -0.05] + [0.002] * 98)

    valor = r.var_historico(serie, 0.99)

    assert valor < r.var_historico(sorted([-0.10] * 2 + [0.002] * 98), 0.99)
    assert valor > r.var_historico(sorted([-0.05] * 2 + [0.002] * 98), 0.99)


def test_mas_confianza_nunca_da_menos_riesgo():
    serie = normalita()

    assert r.var_historico(serie, 0.99) >= r.var_historico(serie, 0.95)
    assert r.var_parametrico(serie, 0.99) >= r.var_parametrico(serie, 0.95)


# ---------------------------------------------------------------------
# Muestra insuficiente: la diferencia de fondo entre los dos métodos
# ---------------------------------------------------------------------


def test_el_historico_se_niega_a_estimar_sin_cola():
    """Al 99 % hacen falta 100 días para que exista un peor 1 %. Con 40 el
    cuantil lo decidiría el peor dato suelto, y eso no es una estimación.
    Devuelve None y no cero: cero diría 'no hay riesgo'."""
    corta = normalita(40)

    assert r.var_historico(corta, 0.99) is None
    assert r.var_historico(corta, 0.95) is not None


def test_el_parametrico_si_estima_con_serie_corta_porque_extrapola():
    """No mira la cola, la deduce de la campana. Es su ventaja y su
    peligro: contesta con la misma seguridad tenga o no fundamento."""
    assert r.var_parametrico(normalita(40), 0.99) is not None


def test_sin_datos_no_hay_var():
    for serie in ([], [0.01]):
        assert r.var_historico(serie, 0.95) is None
        assert r.var_parametrico(serie, 0.95) is None


def test_una_confianza_imposible_no_devuelve_un_numero():
    serie = normalita()

    for mala in (0.0, 1.0, 1.5, -0.2):
        assert r.var_historico(serie, mala) is None
        assert r.var_parametrico(serie, mala) is None


def test_serie_plana_da_riesgo_cero_no_none():
    """Desviación cero es un dato, no una carencia: no se mueve, no hay
    pérdida esperada. Distinto de 'no puedo calcularlo'."""
    assert r.var_parametrico([0.0] * 50, 0.95) == 0.0
