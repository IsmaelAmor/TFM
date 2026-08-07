"""Logica de aplicacion del historico de operaciones (RF-13).

Capa fina, igual que instrument_service: hoy delega y poco mas. Existe
para que el router no importe app.broker directamente (RNF-08) y para
tener sitio donde poner lo que se le pida despues sin tocar ni el router
ni el gateway.

Lo que caeria aqui de forma natural el dia que haga falta: agrupar las
ejecuciones por orden cuando el mercado trocea una compra grande, convertir
los importes a la divisa base con las cotizaciones de cambio, y mezclar
estas ejecuciones con las que viniesen de un almacen propio o del Flex Web
Service. Nada de eso es de IB ni de HTTP, asi que este es su sitio y no el
mapper.
"""

from app.broker import ib_gateway
from app.models.execution import ExecutionHistory


async def get_executions(account_id: str | None = None) -> ExecutionHistory:
    """Devuelve las ejecuciones del dia en curso.

    El alcance limitado no se corrige aqui ni se disimula: viaja en el
    campo 'window' de la respuesta para que el cliente pueda distinguir
    "no has operado hoy" de "no hay mas datos disponibles".
    """
    return await ib_gateway.get_executions(account_id)
