"""Historico de operaciones ejecutadas (RF-13)."""

from fastapi import APIRouter, Depends

from app.api.deps import require_ib
from app.models.execution import ExecutionHistory
from app.services import execution_service

router = APIRouter(tags=["historico"], dependencies=[Depends(require_ib)])


@router.get(
    "/executions",
    response_model=ExecutionHistory,
    summary="Ejecuciones del dia en curso",
)
async def get_executions() -> ExecutionHistory:
    """Operaciones que han cruzado de verdad en el mercado.

    Son EJECUCIONES y no ordenes: una orden que el mercado trocea produce
    varias, y una orden rechazada no produce ninguna. Para el estado de una
    orden concreta esta GET /api/orders/{order_id}.

    ALCANCE: solo el dia en curso, desde medianoche del servidor de IB. Es
    una limitacion del canal reqExecutions al usarse desde IB Gateway, no
    un filtro nuestro; esta explicada en app/models/execution.py y viaja en
    el campo 'window' de la respuesta.

    Una lista vacia es un resultado LEGITIMO y devuelve 200, no 404: "no
    has operado hoy" es una respuesta valida a la pregunta, no la ausencia
    del recurso. El recurso existe siempre; lo que varia es su contenido.
    Un 404 obligaria al cliente a tratar como error lo que es el caso
    normal de una jornada sin operaciones.

    Si el Gateway no responde, require_ib corta antes de llegar aqui y
    devuelve 503: eso SI es un error, y el cliente debe distinguirlo de la
    lista vacia para saber si reintentar o no.
    """
    return await execution_service.get_executions()
