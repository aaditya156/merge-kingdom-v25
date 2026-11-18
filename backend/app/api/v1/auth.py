from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.schemas.auth import DeviceLoginRequest, TokenResponse
from backend.app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/device-login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def device_login(
    request: DeviceLoginRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = AuthService(session)
    return await service.device_login(request)
