from pydantic import BaseModel, Field
from typing import Optional


class DeviceLoginRequest(BaseModel):
    player_id: Optional[str] = Field(None, description="Known player ID if resuming on this device")
    device_id: str = Field(..., description="Unique hardware/device installation ID")
    platform: str = Field("Android", description="Operating system platform: Android or iOS")
    os_version: str = Field("Android 14", description="OS release version, e.g. Android 7.0 or iOS 17.4")
    app_version: str = Field("2.5.0", description="Client build version, e.g. 2.4 or 2.5")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    player_id: str
    is_new_player: bool = False
    migration_required: bool = False


class UserRegisterRequest(BaseModel):
    email: str
    password: str
    player_id: Optional[str] = None


class UserLoginRequest(BaseModel):
    email: str
    password: str
