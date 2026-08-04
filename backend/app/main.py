"""Punto de entrada de la API.

Despues de T24 este fichero no contiene logica: solo compone. Crea la
aplicacion, gestiona el ciclo de vida de la conexion y monta los routers.
Cada endpoint nuevo de T33-T40 anadira aqui una linea y ninguna mas.

Arranque, desde ~/TFM/backend:
    uvicorn app.main:app --reload --port 8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import account, instruments, orders, portfolio, status
from app.broker import ib_client
from app.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Conecta al arrancar y desconecta al parar.

    Si el Gateway no esta levantado, la API arranca igualmente: /status y
    /session responden y el resto devuelve 503. Es tu comportamiento
    original y es la decision correcta: un servidor que arranca y se
    explica vale mas que uno que no arranca.
    """
    try:
        await ib_client.connect()
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo conectar a IB Gateway al arrancar: %s", e)
    yield
    ib_client.disconnect()


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONT_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(status.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(instruments.router, prefix="/api")
app.include_router(orders.router, prefix="/api")