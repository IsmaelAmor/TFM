"""Validacion previa de ordenes."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_ib
from app.broker.ib_gateway import InstrumentNotFound
from app.models.order import OrderRequest, OrderValidation
from app.services import order_service

router = APIRouter(tags=["ordenes"], dependencies=[Depends(require_ib)])


@router.post(
    "/orders/validate",
    response_model=OrderValidation,
    summary="Comprueba una orden sin enviarla",
)
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