"""Configuración de la aplicación.

Lee el .env una sola vez, al importar. Nadie más debe llamar a os.getenv():
si un valor se configura desde fuera, se añade aquí.

Los nombres coinciden con tu backend/.env.example.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    IB_HOST: str = os.getenv("IB_HOST", "127.0.0.1")
    IB_PORT: int = int(os.getenv("IB_PORT", "4002"))
    IB_CLIENT_ID: int = int(os.getenv("IB_CLIENT_ID", "1"))
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    FRONT_ORIGIN: str = os.getenv("FRONT_ORIGIN", "http://localhost:4200")

    IB_TIMEOUT: int = 10
    API_TITLE: str = "TFM Cartera IBKR"
    API_VERSION: str = "0.3.0"


settings = Settings()
