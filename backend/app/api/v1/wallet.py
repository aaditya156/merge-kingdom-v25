from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.api.deps import get_current_player_id
from backend.app.repositories.wallet_repo import InsufficientFundsException
from backend.app.schemas.wallet import (
    WalletBalanceResponse,
    SpendCurrencyRequest,
    EarnCoinsRequest,
    SpendResponse,
    TransactionResponse,
)
from backend.app.services.wallet_service import WalletService

router = APIRouter(prefix="/wallet", tags=["Authoritative Wallet & Ledger"])


@router.get("/balance", response_model=WalletBalanceResponse, status_code=status.HTTP_200_OK)
async def get_balance(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = WalletService(session)
    return await service.get_balance(player_id)


@router.post("/spend", response_model=SpendResponse, status_code=status.HTTP_200_OK)
async def spend_currency(
    request: SpendCurrencyRequest,
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    service = WalletService(session)
    try:
        return await service.spend_currency(player_id, request, idempotency_key=idempotency_key)
    except InsufficientFundsException as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error_code": "INSUFFICIENT_FUNDS",
                "message": str(e),
                "currency_type": e.currency_type,
                "required": e.required,
                "available": e.available,
            },
        )


@router.post("/earn-coins", response_model=SpendResponse, status_code=status.HTTP_200_OK)
async def earn_coins(
    request: EarnCoinsRequest,
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[Optional[str], Header(alias="Idempotency-Key")] = None,
):
    service = WalletService(session)
    return await service.earn_coins(player_id, request, idempotency_key=idempotency_key)


@router.get("/transactions", response_model=List[TransactionResponse], status_code=status.HTTP_200_OK)
async def get_transactions(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
):
    service = WalletService(session)
    return await service.get_history(player_id, limit=limit)
