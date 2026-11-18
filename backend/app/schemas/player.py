from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class DeviceResponse(BaseModel):
    id: str
    device_id: str
    platform: str
    os_version: str
    app_version: str
    last_seen_at: datetime
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PlayerProfileResponse(BaseModel):
    player_id: str
    nickname: Optional[str] = None
    highest_level: int
    created_at: datetime
    last_active_at: datetime
    devices: List[DeviceResponse] = []

    model_config = ConfigDict(from_attributes=True)
