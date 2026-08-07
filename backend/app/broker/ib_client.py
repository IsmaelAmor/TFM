"""Ciclo de vida de la conexión con IB Gateway.

Responsabilidad única: mantener UNA conexión viva mientras viva el proceso.

Por qué una sola: IB no admite dos conexiones con el mismo clientId, y el
socket es persistente. Conectar y desconectar en cada petición HTTP daría
errores de clientId en uso.

Reconexión (T29). El Gateway se reinicia a diario y la sesión se cae. El
arreglo se apoya en dos hechos MEDIDOS con scripts/sondea_reconexion.py el
07/08/2026, no en la documentación:

  1. Dos connectAsync solapados sobre la MISMA instancia de IB corrompen el
     socket: el decodificador de ib_async lanza KeyError y a partir de ahí
     todas las peticiones caducan aunque isConnected() diga True. Como el
     dashboard sondea cada 5 s, al caerse la sesión entran varias
     reconexiones a la vez y se pisan. Por eso la (re)conexión va detrás de
     un candado: N intentos simultáneos se convierten en uno.

  2. Cuando IB responde error 326 ("clientId en uso"), connectAsync NO lo
     propaga como excepción propia: agota el timeout entero y levanta un
     TimeoutError pelado, así que por el tipo de excepción no se distingue
     "id ocupado" de "Gateway caído". En producción el 326 lo causa nuestro
     PROPIO socket anterior, que tras el reinicio queda medio abierto y
     sigue reservando el clientId. Un disconnect() limpio libera el id en
     ~1,5 s (medido); por eso, antes de reconectar, se cierra el socket
     previo de forma explícita. Sin ese cierre, reintentar con el mismo id
     no converge nunca: ese era el fallo de T29.

Se descartó rotar el clientId (que también funcionaría, comprobado en la
sección 4 del sondeo) para no hacer derivar el id de la sesión: la
convención uvicorn=1 dejaría de cumplirse y /session informaría de un id
distinto del configurado. Con el cierre explícito + candado el mismo id
vuelve a estar libre, así que la rotación no hace falta (D-16).

La lógica de reconexión vive aquí y no en el router: es un problema de
conexión, no de HTTP. El router se limita a traducir el fallo a un 503
(ver app/api/deps.py).
"""

import asyncio
import logging

from ib_async import IB

from app.config import settings

logger = logging.getLogger(__name__)

_ib = IB()

# Serializa la (re)conexión. Es la pieza central del arreglo de T29: sin
# él, las peticiones concurrentes del polling reconectan a la vez sobre _ib
# y corrompen el socket (medido). Con él, solo una reconecta y las demás
# esperan y encuentran la sesión ya lista.
_lock = asyncio.Lock()


class BrokerUnavailable(Exception):
    """No hay conexión con IB Gateway y no se ha podido restablecer."""


async def connect() -> None:
    """Abre la conexión si no la hay. Idempotente y serializada.

    Hace el trabajo de reconexión completo, no solo el primer arranque:
    cierra el socket previo, reconecta con el clientId configurado y fija
    el tipo de dato de mercado.
    """
    # Camino rápido sin candado: si ya hay sesión, no hay nada que
    # serializar y no pagamos la contención del lock en cada petición.
    if _ib.isConnected():
        return

    async with _lock:
        # Doble comprobación: mientras esperábamos el candado, otra
        # petición del polling puede haber reconectado ya. Sin esto, las
        # cinco peticiones concurrentes reconectarían en fila, una tras
        # otra, en vez de una sola.
        if _ib.isConnected():
            return

        # Cierre explícito del socket anterior ANTES de reconectar. Tras el
        # reinicio del Gateway nuestro socket queda medio abierto y IB sigue
        # viendo el clientId como "en uso" (error 326). Un disconnect()
        # limpio libera el id en ~1,5 s; sin él, reconectar con el mismo id
        # no converge. Va SIN guardar por isConnected() a propósito: aquí ya
        # es False y aun así hay que forzar el cierre del socket fantasma
        # que la desconexión sucia dejó vivo.
        _ib.disconnect()

        await _ib.connectAsync(
            settings.IB_HOST,
            settings.IB_PORT,
            clientId=settings.IB_CLIENT_ID,
            timeout=settings.IB_TIMEOUT,
        )

        # Tipo de dato de mercado para toda la sesion. Se fija aqui y no en
        # cada peticion de precio porque es un ajuste del cliente: IB lo
        # guarda y lo aplica a todo lo posterior. Repetirlo por peticion no
        # cambiaria nada y abriria la puerta a que dos partes del codigo
        # asumieran tipos distintos.
        #
        # El valor 3 es dato retrasado unos 15 minutos. Es el unico
        # disponible en la cuenta paper DUN684545, que no tiene suscripcion
        # de datos en tiempo real. Configurable via IB_MARKET_DATA_TYPE por
        # si algun dia la hubiera: pasaria a 1 sin tocar codigo.
        _ib.reqMarketDataType(settings.IB_MARKET_DATA_TYPE)

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
