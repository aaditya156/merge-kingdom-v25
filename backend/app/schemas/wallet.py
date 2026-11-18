from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class WalletBalanceResponse(BaseModel):
    player_id: str
    coins_balance: int
    gems_balance: int
    lock_version: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpendCurrencyRequest(BaseModel):
    currency_type: str = Field(..., description="'COIN' or 'GEM'")
    amount: int = Field(..., gt=0, description="Amount to debit")
    item_id: str = Field(..., description="Store item or booster being purchased")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EarnCoinsRequest(BaseModel):
    level_completed: int = Field(..., ge=1)
    coins_earned: int = Field(..., gt=0, le=500, description="Capped gameplay reward")
    score: int = Field(0, ge=0)


class TransactionResponse(BaseModel):
    id: str
    player_id: str
    currency_type: str
    amount: int
    balance_before: int
    balance_after: int
    transaction_type: str
    reference_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SpendResponse(BaseModel):
    transaction: TransactionResponse
    wallet: WalletBalanceResponse
