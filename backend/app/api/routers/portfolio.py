"""Cartera y posiciones."""

from fastapi import APIRouter, Depends

from app.api.deps import require_ib
from app.models.portfolio import Portfolio
from app.services import portfolio_service

router = APIRouter(tags=["cartera"], dependencies=[Depends(require_ib)])


@router.get("/portfolio", response_model=Portfolio, summary="Posiciones abiertas")
async def get_portfolio(account_id: str | None = None) -> Portfolio:
    return await portfolio_service.get_portfolio(account_id)
