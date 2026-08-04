"""Validacion previa de ordenes."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_ib
from app.broker.ib_gateway import InstrumentNotFound
from app.models.order import OrderRequest, OrderResult, OrderValidation
from app.services import order_service

router = APIRouter(tags=["ordenes"], dependencies=[Depends(require_ib)])


@router.post(
    "/orders/validate",
    response_model=OrderValidation,
    summary="Comprueba una orden sin enviarla",
)
@router.post(
    "/orders",
    response_model=OrderResult,
    summary="Envia una orden al mercado",
)
async def create_order(req: OrderRequest) -> OrderResult:
    """Envia una orden, pasando obligatoriamente por la validacion previa.

    Devuelve 200 y no 201, por el mismo criterio que /orders/validate: el
    desenlace viaja en 'estado' (ejecutada, activa, rechazada o
    no_enviada), no en el codigo HTTP. Una orden rechazada es una respuesta
    correcta a una peticion correcta, no un error del cliente; obligar al
    frontend a leer el cuerpo de un 4xx para pintar el motivo que ya viene
    estructurado no aporta nada.
    """
    try:
        return await order_service.submit_order(req)
    except InstrumentNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get(
    "/orders/{order_id}",
    response_model=OrderResult,
    summary="Estado de una orden ya enviada",
)
async def read_order(order_id: int) -> OrderResult:
    """Seguimiento de una orden viva: el frontend sondea hasta que resuelve."""
    result = await order_service.get_order(order_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No hay ninguna orden con id {order_id} en esta sesion",
        )
    return result
async def validate_order(req: OrderRequest) -> OrderValidation:
    """POST y no GET aunque no modifique nada.

    La orden es un cuerpo con cinco campos y no un identificador; meterla
    en la query string la haria incomoda de leer y de cachear mal. Y el
    verbo separa con claridad esta ruta de la de envio, que sera
    POST /orders y si modifica.

    Una orden rechazada devuelve 200 con accepted=false, no un 4xx: la
    peticion es correcta y la respuesta es un veredicto con sus motivos.
    Un 400 obligaria al frontend a leer el error para pintar la misma
    informacion que ya viene en el cuerpo.
    """
    try:
        return await order_service.validate_order(req)
    except InstrumentNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e