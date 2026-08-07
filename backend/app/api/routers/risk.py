"""Panel de riesgo de la cartera (T47, RF-19)."""

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_ib
from app.models.risk import PortfolioRisk
from app.services import portfolio_risk_service

router = APIRouter(tags=["riesgo"], dependencies=[Depends(require_ib)])


@router.get(
    "/portfolio/risk",
    response_model=PortfolioRisk,
    summary="Metricas de riesgo de la cartera",
)
async def get_portfolio_risk(
    account_id: str | None = None,
    tasa_libre_riesgo: float = Query(
        0.0,
        ge=0.0,
        le=1.0,
        description="Tasa anual SIMPLE (0,03 = 3 %). Se convierte a continua.",
    ),
) -> PortfolioRisk:
    """Devuelve 200 siempre que haya conexion, aun sin metricas.

    Una cartera vacia o con series cortas no es un error del cliente: es un
    estado legitimo. Se responde 200 con las metricas a null y el campo
    aviso explicando por que, igual que /executions declara su ventana.
    """
    return await portfolio_risk_service.get_portfolio_risk(account_id, tasa_libre_riesgo)
