"""Busqueda de instrumentos y consulta de precios."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import require_ib
from app.broker.ib_gateway import InstrumentNotFound
from app.models.instrument import Instrument
from app.models.quote import Quote
from app.services import instrument_service

router = APIRouter(tags=["instrumentos"], dependencies=[Depends(require_ib)])


@router.get(
    "/instruments",
    response_model=list[Instrument],
    summary="Busca instrumentos por ticker o nombre",
)
async def search_instruments(
    q: str = Query(..., min_length=1, max_length=40, description="Ticker o nombre"),
    limit: int = Query(20, ge=1, le=50),
) -> list[Instrument]:
    return await instrument_service.search_instruments(q.strip(), limit)


@router.get(
    "/instruments/{con_id}/quote",
    response_model=Quote,
    summary="Ultimo precio conocido del instrumento",
)
async def get_quote(con_id: int) -> Quote:
    """El precio cuelga del instrumento y no es un recurso aparte.

    Es la relacion real: un precio no existe por si mismo, existe el precio
    de algo. La URL lo dice.
    """
    try:
        return await instrument_service.get_quote(con_id)
    except InstrumentNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
