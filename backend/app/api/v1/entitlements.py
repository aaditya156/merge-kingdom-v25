from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.api.deps import get_current_player_id
from backend.app.schemas.entitlement import PlayerEntitlementsResponse
from backend.app.services.entitlement_service import EntitlementService

router = APIRouter(prefix="/entitlements", tags=["Entitlements (No Ads)"])


@router.get("", response_model=PlayerEntitlementsResponse, status_code=status.HTTP_200_OK)
async def get_entitlements(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = EntitlementService(session)
    return await service.get_player_entitlements(player_id)


@router.post("/restore", response_model=PlayerEntitlementsResponse, status_code=status.HTTP_200_OK)
async def restore_entitlements(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = EntitlementService(session)
    return await service.restore_entitlements(player_id)
