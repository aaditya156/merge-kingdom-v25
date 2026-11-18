from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class MigrationStatusResponse(BaseModel):
    player_id: str
    migration_required: bool
    status: str = "PENDING"  # 'NOT_REQUIRED', 'PENDING', 'COMPLETED'
    original_coins: Optional[int] = None
    converted_coins: Optional[int] = None
    converted_gems: Optional[int] = None
    migrated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ExecuteMigrationRequest(BaseModel):
    # Optional override for legacy payload if client submits offline save snapshot
    legacy_coins: Optional[int] = None


class MigrationResultResponse(BaseModel):
    player_id: str
    status: str
    original_coins: int
    lifetime_purchased_coins: int
    converted_coins: int
    converted_gems: int
    policy_applied: str = "PURCHASED_FIRST_PROTECTION"
    migrated_at: datetime
    message: str = "Migration completed successfully."

    model_config = ConfigDict(from_attributes=True)
