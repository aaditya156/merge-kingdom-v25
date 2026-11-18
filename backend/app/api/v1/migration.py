from typing import Annotated, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.api.deps import get_current_player_id
from backend.app.schemas.migration import (
    MigrationStatusResponse,
    ExecuteMigrationRequest,
    MigrationResultResponse,
)
from backend.app.services.migration_service import MigrationService

router = APIRouter(prefix="/migration", tags=["Legacy Data Migration"])


@router.get("/status", response_model=MigrationStatusResponse, status_code=status.HTTP_200_OK)
async def get_migration_status(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = MigrationService(session)
    return await service.get_status(player_id)


@router.post("/migrate", response_model=MigrationResultResponse, status_code=status.HTTP_200_OK)
async def execute_migration(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
    request: Optional[ExecuteMigrationRequest] = None,
):
    service = MigrationService(session)
    return await service.execute_migration(player_id, request)
