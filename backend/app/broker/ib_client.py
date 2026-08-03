"""Ciclo de vida de la conexión con IB Gateway.

Responsabilidad única: mantener UNA conexión viva mientras viva el proceso.

Por qué una sola: IB no admite dos conexiones con el mismo clientId, y el
socket es persistente. Conectar y desconectar en cada petición HTTP daría
errores de clientId en uso.

La lógica de reconexión es la que ya tenías en ensure_connected(), movida
aquí: es un problema de conexión, no de HTTP. El router se limita a
traducir el fallo a un 503 (ver app/api/deps.py).
"""

import logging

from ib_async import IB

from app.config import settings

logger = logging.getLogger(__name__)

_ib = IB()


class BrokerUnavailable(Exception):
    """No hay conexión con IB Gateway y no se ha podido restablecer."""


async def connect() -> None:
    """Abre la conexión. Idempotente: si ya está conectado, no hace nada."""
    if _ib.isConnected():
        return
    await _ib.connectAsync(
        settings.IB_HOST,
        settings.IB_PORT,
        clientId=settings.IB_CLIENT_ID,
        timeout=settings.IB_TIMEOUT,
    )
    logger.info(
        "Conectado a IB Gateway %s:%s (clientId=%s)",
        settings.IB_HOST,
        settings.IB_PORT,
        settings.IB_CLIENT_ID,
    )


async def ensure_connected() -> None:
    """Reconecta si la sesión se ha caído (reinicio diario del Gateway)."""
    if _ib.isConnected():
        return
    try:
        await connect()
    except Exception as e:  # noqa: BLE001
        raise BrokerUnavailable(f"IB Gateway no disponible: {e}") from e


def disconnect() -> None:
    if _ib.isConnected():
        _ib.disconnect()
        logger.info("Desconectado de IB Gateway")


def is_connected() -> bool:
    return _ib.isConnected()


def get_ib() -> IB:
    """Acceso a la instancia de IB. Uso restringido a app/broker/.

    Si un router o un servicio llama a esta función, RNF-08 deja de
    cumplirse aunque el grep de imports siga saliendo limpio.
    """
    return _ib
