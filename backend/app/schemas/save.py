import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, ConfigDict


class InventorySchema(BaseModel):
    hammer: int = Field(0, ge=0)
    shuffle: int = Field(0, ge=0)


class SaveSyncRequest(BaseModel):
    base_revision_id: int = Field(..., ge=0, description="Revision ID client loaded before making local changes")
    level: int = Field(..., ge=1, description="Current highest completed level")
    inventory: Dict[str, int] = Field(default_factory=dict, description="Consumable items inventory")
    game_state: Dict[str, Any] = Field(default_factory=dict, description="Board configuration, puzzle state")
    client_saved_at: datetime = Field(..., description="Timestamp from device clock")
    device_id: str = Field(..., description="Device ID initiating the sync")


class GameSaveResponse(BaseModel):
    player_id: str
    revision_id: int
    level: int
    inventory: Dict[str, int]
    game_state: Dict[str, Any]
    state_hash: str
    server_saved_at: datetime
    updated_by_device_id: str

    model_config = ConfigDict(from_attributes=True)


class SyncResultResponse(BaseModel):
    status: str = Field(..., description="'ACCEPTED', 'MERGED', or 'CONFLICT'")
    revision_id: int
    level: int
    inventory: Dict[str, int]
    game_state: Dict[str, Any]
    server_saved_at: datetime
    message: Optional[str] = None


class LegacySaveRequest(BaseModel):
    player_id: str
    saved_at: int
    level: int
    coins: int
    inventory: Dict[str, int]
    no_ads: bool = False


class LegacySaveResponse(BaseModel):
    player_id: str
    saved_at: int
    level: int
    coins: int
    inventory: Dict[str, int]
    no_ads: bool
