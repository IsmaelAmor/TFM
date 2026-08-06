"""Pruebas de enrutado (05/08/2026).

Nacen de un fallo real: dos decoradores @router.post apilados sobre la
misma funcion dejaron /orders/validate apuntando al envio, o sea que
comprobar una orden la cursaba. Ninguna prueba lo vio porque todas
prueban funciones, y el fallo estaba en el cableado entre la URL y la
funcion, que es justo lo que nadie miraba.

Se consulta el esquema OpenAPI y no app.routes. app.routes es interior de
FastAPI: su forma cambia entre versiones (verificado el 05/08, esta
version envuelve los sub-routers en _IncludedRouter y no aplana las rutas,
asi que iterar app.routes ya no las encuentra). El OpenAPI es contrato
publico y estable: es la fuente correcta para preguntar por el enrutado.

No hacen falta ni Gateway ni servidor: construir la app genera el esquema.
El lifespan, y con el la conexion a IB, solo corre al arrancar uvicorn.

Ejecutar desde backend/ con el venv activado:
    python -m pytest tests/test_rutas.py
"""

from collections import Counter

from app.main import app


def operaciones() -> list[tuple[str, str, str]]:
    """Lista de (verbo, ruta, operationId) segun el esquema OpenAPI.

    El operationId lo genera FastAPI a partir del nombre de la funcion que
    atiende la ruta: 'validate_order_api_orders_validate_post'. Empieza por
    el nombre de la funcion, que es justo lo que estas pruebas comprueban.
    """
    esquema = app.openapi()
    salida = []
    for ruta, metodos in esquema["paths"].items():
        for verbo, op in metodos.items():
            salida.append((verbo.upper(), ruta, op["operationId"]))
    return salida


def funcion_de(verbo: str, ruta: str) -> str:
    """Nombre de la funcion que atiende una ruta, o '' si la ruta no existe.

    El operationId es 'nombre_funcion' + '_api_' + resto. Cortar por
    '_api_' devuelve el nombre de la funcion sin depender de como FastAPI
    construya el sufijo.
    """
    for v, r, op_id in operaciones():
        if v == verbo and r == ruta:
            return op_id.split("_api_")[0]
    return ""


def test_validar_una_orden_no_la_envia():
    """La prueba que habria cazado el fallo del 05/08."""
    assert funcion_de("POST", "/api/orders/validate") == "validate_order"


def test_cada_ruta_de_ordenes_atiende_a_su_funcion():
    assert funcion_de("POST", "/api/orders") == "create_order"
    assert funcion_de("GET", "/api/orders/{order_id}") == "read_order"


def test_ninguna_funcion_atiende_dos_rutas_distintas():
    """Generaliza el fallo en vez de vigilar solo el caso que lo produjo.

    Si una funcion aparece en dos operaciones distintas es que hay
    decoradores apilados, sea en ordenes o donde sea.
    """
    nombres = [op_id.split("_api_")[0] for _, _, op_id in operaciones()]
    repetidas = [n for n, veces in Counter(nombres).items() if veces > 1]

    assert repetidas == [], f"Funciones cableadas a mas de una ruta: {repetidas}"