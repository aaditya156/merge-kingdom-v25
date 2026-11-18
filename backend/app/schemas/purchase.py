from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, ConfigDict


class VerifyPurchaseRequest(BaseModel):
    store_platform: str = Field(..., description="'GOOGLE_PLAY' or 'APPLE_APP_STORE'")
    store_transaction_id: str = Field(..., description="Unique receipt/transaction ID from store")
    product_id: str = Field(..., description="Product ID (e.g. 'gems_500', 'no_ads_pack')")
    receipt_data: Optional[str] = None


class VerifyPurchaseResponse(BaseModel):
    verification_status: str = "VERIFIED"
    store_transaction_id: str
    product_id: str
    gems_granted: int = 0
    entitlements_granted: List[str] = []
    new_coins_balance: int
    new_gems_balance: int
    message: str = "Purchase successfully verified and credited."
