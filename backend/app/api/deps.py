"""Dependencias compartidas por los routers.

Aqui vive la unica traduccion de "problema de conexion" a "codigo HTTP".
La logica de reconexion no esta aqui: esta en broker/ib_client.py, que es
donde corresponde. Este fichero solo decide que numero devolver.

Uso en un router:
    router = APIRouter(dependencies=[Depends(require_ib)])
"""

from fastapi import HTTPException, status

from app.broker.ib_client import BrokerUnavailable, ensure_connected


async def require_ib() -> None:
    """Garantiza conexion con IB o corta la peticion con un 503."""
    try:
        await ensure_connected()
    except BrokerUnavailable as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
