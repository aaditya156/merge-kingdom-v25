from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class EntitlementResponse(BaseModel):
    id: str
    player_id: str
    entitlement_key: str
    is_active: bool
    granted_by_source: str
    granted_at: datetime
    expires_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class PlayerEntitlementsResponse(BaseModel):
    player_id: str
    entitlements: List[EntitlementResponse]
