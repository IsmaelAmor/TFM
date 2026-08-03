"""Modelos de cuenta y de sesion."""

from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    """Resumen economico de la cuenta.

    Las cuatro magnitudes son las que ya filtrabas en tu main.py, ahora
    tipadas en vez de devueltas como lista de pares tag/valor. Tipadas
    aparecen en el OpenAPI con su nombre y su tipo, que es lo que hace
    util el contrato de T18.
    """

    account_id: str
    currency: str
    net_liquidation: float = Field(..., description="Valor liquidativo total")
    total_cash: float = Field(..., description="Efectivo en cuenta")
    available_funds: float = Field(..., description="Fondos disponibles")
    buying_power: float = Field(..., description="Poder de compra")


class SessionInfo(BaseModel):
    """Estado de la sesion con IB Gateway."""

    connected: bool
    host: str
    port: int
    client_id: int
    accounts: list[str] = Field(default_factory=list)


class StatusInfo(BaseModel):
    """Estado del propio servicio, sin tocar IB."""

    service: str = "backend-tfm"
    status: str = "ok"
    api_version: str
