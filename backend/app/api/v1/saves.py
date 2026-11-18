from typing import Annotated
from fastapi import APIRouter, Depends, status, Header
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.api.deps import get_current_player_id
from backend.app.schemas.save import (
    SaveSyncRequest,
    SyncResultResponse,
    GameSaveResponse,
    OfflineOperationRequest,
    OfflineOperationResponse,
)
from backend.app.services.save_sync_service import SaveSyncService

router = APIRouter(prefix="/saves", tags=["Game Saves & Sync"])


@router.get("/latest", response_model=GameSaveResponse, status_code=status.HTTP_200_OK)
async def get_latest_save(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = SaveSyncService(session)
    return await service.get_latest_save(player_id)


@router.post("/sync", response_model=SyncResultResponse, status_code=status.HTTP_200_OK)
async def sync_save(
    request: SaveSyncRequest,
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    service = SaveSyncService(session)
    return await service.sync_save(player_id, request)


@router.post("/operations/consume", response_model=OfflineOperationResponse, status_code=status.HTTP_200_OK)
async def consume_inventory_item(
    request: OfflineOperationRequest,
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = SaveSyncService(session)
    return await service.apply_inventory_operation(
        player_id=player_id,
        operation_id=request.operation_id,
        item_id=request.item_id,
        quantity=request.quantity,
        device_id=request.device_id,
    )
