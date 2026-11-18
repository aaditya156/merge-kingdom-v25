from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.repositories.wallet_repo import WalletRepository, InsufficientFundsException
from backend.app.schemas.wallet import (
    WalletBalanceResponse,
    SpendCurrencyRequest,
    EarnCoinsRequest,
    SpendResponse,
    TransactionResponse,
)

# Standard level completion reward cap
MAX_LEVEL_COMPLETION_COINS = 100


class WalletService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.wallet_repo = WalletRepository(session)

    async def get_balance(self, player_id: str) -> WalletBalanceResponse:
        wallet = await self.wallet_repo.get_wallet(player_id)
        return WalletBalanceResponse.model_validate(wallet)

    async def spend_currency(
        self,
        player_id: str,
        request: SpendCurrencyRequest,
        idempotency_key: Optional[str] = None,
    ) -> SpendResponse:
        wallet, tx = await self.wallet_repo.mutate_balance(
            player_id=player_id,
            currency_type=request.currency_type.upper(),
            amount=-abs(request.amount),
            transaction_type="STORE_SPEND",
            reference_id=request.item_id,
            idempotency_key=idempotency_key,
            metadata=request.metadata,
        )
        return SpendResponse(
            transaction=TransactionResponse.model_validate(tx),
            wallet=WalletBalanceResponse.model_validate(wallet),
        )

    async def earn_coins(
        self,
        player_id: str,
        request: EarnCoinsRequest,
        idempotency_key: Optional[str] = None,
    ) -> SpendResponse:
        # Priority 4 Fix: Validate level completion reward amount
        if request.coins_earned > MAX_LEVEL_COMPLETION_COINS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid reward amount: Level completion coins cannot exceed {MAX_LEVEL_COMPLETION_COINS}.",
            )

        # Priority 4 Fix: Level rewards are strictly idempotent per player per level
        effective_key = idempotency_key or f"level_reward_{player_id}_lvl_{request.level_completed}"

        # Check if already claimed with a different reward amount
        existing_tx = await self.wallet_repo.get_transaction_by_idempotency(effective_key)
        if existing_tx and existing_tx.amount != request.coins_earned:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Level {request.level_completed} reward was already claimed with amount {existing_tx.amount}.",
            )

        wallet, tx = await self.wallet_repo.mutate_balance(
            player_id=player_id,
            currency_type="COIN",
            amount=request.coins_earned,
            transaction_type="LEVEL_REWARD",
            reference_id=f"level_{request.level_completed}",
            idempotency_key=effective_key,
            metadata={"score": request.score, "level": request.level_completed},
        )
        return SpendResponse(
            transaction=TransactionResponse.model_validate(tx),
            wallet=WalletBalanceResponse.model_validate(wallet),
        )

    async def get_history(self, player_id: str, limit: int = 50) -> List[TransactionResponse]:
        txs = await self.wallet_repo.get_transaction_history(player_id, limit=limit)
        return [TransactionResponse.model_validate(t) for t in txs]
