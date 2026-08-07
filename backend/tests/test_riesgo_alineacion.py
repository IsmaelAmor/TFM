"""Pruebas de la alineación de series por fecha (T47), sin Gateway.

Lo que se protege aquí es un error que no da excepción: emparejar cierres
de días distintos. Si esto se rompe, las correlaciones siguen saliendo y
siguen pareciendo razonables.
"""

from datetime import date

from app.services import risk_service as r


def d(dia):
    return date(2026, 8, dia)


def test_series_ya_alineadas_se_devuelven_enteras():
    a = {d(3): 100.0, d(4): 101.0, d(5): 102.0}
    b = {d(3): 50.0, d(4): 51.0, d(5): 52.0}
    assert r.alinear_series([a, b]) == [[100.0, 101.0, 102.0], [50.0, 51.0, 52.0]]


def test_descarta_el_dia_que_le_falta_a_una_de_las_series():
    """Un festivo en una plaza y no en la otra: la sesión sin pareja no
    puede entrar, no hay con qué compararla."""
    a = {d(3): 100.0, d(4): 101.0, d(5): 102.0}
    b = {d(3): 50.0, d(5): 52.0}
    assert r.alinear_series([a, b]) == [[100.0, 102.0], [50.0, 52.0]]


def test_no_empareja_por_posicion_sino_por_fecha():
    """LA prueba que importa. Emparejando por posición, el 101 de 'a' iría
    con el 52 de 'b', que es de otro día. Sale un número y está mal."""
    a = {d(3): 100.0, d(4): 101.0, d(5): 102.0}
    b = {d(3): 50.0, d(5): 52.0}
    alineadas = r.alinear_series([a, b])
    assert alineadas[0][1] == 102.0
    assert alineadas[0][1] != 101.0


def test_ordena_cronologicamente_aunque_el_diccionario_no_lo_este():
    a = {d(5): 102.0, d(3): 100.0, d(4): 101.0}
    assert r.alinear_series([a]) == [[100.0, 101.0, 102.0]]


def test_sin_fechas_comunes_devuelve_listas_vacias():
    """Vacío y no None: la capa de arriba lo traduce a 'sin datos'."""
    a = {d(3): 100.0}
    b = {d(4): 50.0}
    assert r.alinear_series([a, b]) == [[], []]


def test_todas_las_series_salen_con_la_misma_longitud():
    """Es la precondición que exigen covarianza y volatilidad_cartera."""
    a = {d(3): 1.0, d(4): 2.0, d(5): 3.0, d(6): 4.0}
    b = {d(4): 1.0, d(5): 2.0, d(6): 3.0}
    c = {d(3): 1.0, d(5): 2.0, d(6): 3.0}
    alineadas = r.alinear_series([a, b, c])
    assert len({len(s) for s in alineadas}) == 1
    assert len(alineadas[0]) == 2


def test_lista_vacia_de_series():
    assert r.alinear_series([]) == []
