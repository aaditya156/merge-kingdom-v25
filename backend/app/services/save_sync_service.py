from datetime import datetime, timezone
from typing import Dict, Any, Tuple
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.repositories.save_repo import SaveRepository
from backend.app.schemas.save import SaveSyncRequest, SyncResultResponse, GameSaveResponse
from backend.app.models.base import utc_now

# Max legitimate level jump in a single offline sync batch
MAX_ALLOWED_LEVEL_JUMP = 100


class SaveSyncService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.save_repo = SaveRepository(session)

    async def get_latest_save(self, player_id: str) -> GameSaveResponse:
        save = await self.save_repo.get_latest_save(player_id)
        if not save:
            save = await self.save_repo.create_or_update_save(
                player_id=player_id,
                revision_id=1,
                level=1,
                inventory={"hammer": 0, "shuffle": 0},
                game_state={},
                device_id="system_init",
                client_saved_at=utc_now(),
            )
        return GameSaveResponse.model_validate(save)

    async def sync_save(self, player_id: str, request: SaveSyncRequest) -> SyncResultResponse:
        current_save = await self.save_repo.get_latest_save(player_id)

        # Case 1: First save for player
        if not current_save:
            saved = await self.save_repo.create_or_update_save(
                player_id=player_id,
                revision_id=1,
                level=request.level,
                inventory=request.inventory,
                game_state=request.game_state,
                device_id=request.device_id,
                client_saved_at=request.client_saved_at,
            )
            return SyncResultResponse(
                status="ACCEPTED",
                revision_id=saved.revision_id,
                level=saved.level,
                inventory=saved.inventory,
                game_state=saved.game_state,
                server_saved_at=saved.server_saved_at,
                message="Initial save created.",
            )

        # Progression Sanity Check: Prevent fraudulent level spoofing (e.g. jumping from level 1 to level 99999)
        if request.level > current_save.level + MAX_ALLOWED_LEVEL_JUMP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Progression anomaly detected: Level jump from {current_save.level} to {request.level} exceeds safety limit of {MAX_ALLOWED_LEVEL_JUMP} levels.",
            )

        # Case 2: Clean sequential update
        if request.base_revision_id == current_save.revision_id:
            next_revision = current_save.revision_id + 1
            resolved_level = max(current_save.level, request.level)
            
            try:
                saved = await self.save_repo.create_or_update_save(
                    player_id=player_id,
                    revision_id=next_revision,
                    level=resolved_level,
                    inventory=request.inventory,
                    game_state=request.game_state,
                    device_id=request.device_id,
                    client_saved_at=request.client_saved_at,
                )
                return SyncResultResponse(
                    status="ACCEPTED",
                    revision_id=saved.revision_id,
                    level=saved.level,
                    inventory=saved.inventory,
                    game_state=saved.game_state,
                    server_saved_at=saved.server_saved_at,
                    message="Save accepted cleanly.",
                )
            except IntegrityError:
                # Concurrent write collided at same revision, refresh and fall back to semantic merge
                await self.session.rollback()
                current_save = await self.save_repo.get_latest_save(player_id)

        # Case 3: Stale base revision or concurrency collision -> SEMANTIC 3-WAY MERGE
        merged_level = max(current_save.level, request.level)

        merged_inventory = dict(current_save.inventory)
        for item, count in request.inventory.items():
            merged_inventory[item] = max(merged_inventory.get(item, 0), count)

        merged_game_state = request.game_state if request.level >= current_save.level else current_save.game_state
        next_revision = current_save.revision_id + 1

        merged_save = await self.save_repo.create_or_update_save(
            player_id=player_id,
            revision_id=next_revision,
            level=merged_level,
            inventory=merged_inventory,
            game_state=merged_game_state,
            device_id=request.device_id,
            client_saved_at=request.client_saved_at,
        )

        return SyncResultResponse(
            status="MERGED",
            revision_id=merged_save.revision_id,
            level=merged_save.level,
            inventory=merged_save.inventory,
            game_state=merged_save.game_state,
            server_saved_at=merged_save.server_saved_at,
            message=f"Conflict resolved via 3-way semantic merge. Progress preserved at level {merged_level}.",
        )
