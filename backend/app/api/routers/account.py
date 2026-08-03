"""Resumen de cuenta."""

from fastapi import APIRouter, Depends

from app.api.deps import require_ib
from app.models.account import AccountSummary
from app.services import account_service

router = APIRouter(tags=["cuenta"], dependencies=[Depends(require_ib)])


@router.get("/account", response_model=AccountSummary, summary="Resumen de la cuenta")
async def get_account(account_id: str | None = None) -> AccountSummary:
    return await account_service.get_account_summary(account_id)
