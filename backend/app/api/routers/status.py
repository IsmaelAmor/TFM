"""Estado del servicio y de la sesion con IB.

Estos dos endpoints no pasan por services/ a proposito: no hay logica de
aplicacion que aplicar, solo se expone el estado. Una capa de servicio que
se limitase a reenviar la llamada seria ceremonia vacia.

Tampoco usan require_ib: deben responder precisamente cuando IB no esta.
"""

from fastapi import APIRouter

from app.broker import ib_client, ib_gateway
from app.config import settings
from app.models.account import SessionInfo, StatusInfo

router = APIRouter(tags=["estado"])


@router.get("/status", response_model=StatusInfo, summary="Estado del servicio")
async def get_status() -> StatusInfo:
    return StatusInfo(api_version=settings.API_VERSION)


@router.get("/session", response_model=SessionInfo, summary="Estado de la sesion con IB")
async def get_session() -> SessionInfo:
    conectado = ib_client.is_connected()
    return SessionInfo(
        connected=conectado,
        host=settings.IB_HOST,
        port=settings.IB_PORT,
        client_id=settings.IB_CLIENT_ID,
        accounts=ib_gateway.get_managed_accounts() if conectado else [],
    )
