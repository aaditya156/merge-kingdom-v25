from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, List
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.repositories.save_repo import SaveRepository
from backend.app.schemas.save import (
    SaveSyncRequest,
    SyncResultResponse,
    GameSaveResponse,
    OfflineOperationResponse,
)
from backend.app.models.offline import OfflineOperation
from backend.app.models.base import utc_now

# Prototype heuristic for progression bounds (Note: In production, requires move validation)
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

    async def apply_inventory_operation(
        self,
        player_id: str,
        operation_id: str,
        item_id: str,
        quantity: int,
        device_id: str,
    ) -> OfflineOperationResponse:
        """
        Server-side deduplication of offline consumption operations.
        Ensures identical operation IDs across devices cannot consume an item twice.
        """
        # 1. Deduplication check: Has this operation_id already been applied?
        existing_op = await self.session.execute(
            select(OfflineOperation).where(OfflineOperation.idempotency_key == operation_id)
        )
        op_record = existing_op.scalar_one_or_none()

        current_save = await self.save_repo.get_latest_save(player_id)
        if not current_save:
            current_save = await self.save_repo.create_or_update_save(
                player_id=player_id,
                revision_id=1,
                level=1,
                inventory={"hammer": 0, "shuffle": 0},
                game_state={},
                device_id=device_id,
                client_saved_at=utc_now(),
            )

        if op_record:
            # Operation already executed: return current inventory without deducting again
            return OfflineOperationResponse(
                status="DUPLICATE_IGNORED",
                operation_id=operation_id,
                inventory=current_save.inventory,
                revision_id=current_save.revision_id,
                message="Operation already processed. Duplicate consumption rejected.",
            )

        # 2. Record operation in database protected by uniqueness constraint on idempotency_key
        try:
            rec = OfflineOperation(
                player_id=player_id,
                device_id=device_id,
                operation_type="CONSUME_ITEM",
                idempotency_key=operation_id,
                payload={"item_id": item_id, "quantity": quantity},
                status="APPLIED",
                client_timestamp=utc_now(),
                processed_at=utc_now(),
            )
            self.session.add(rec)
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            current_save = await self.save_repo.get_latest_save(player_id)
            return OfflineOperationResponse(
                status="DUPLICATE_IGNORED",
                operation_id=operation_id,
                inventory=current_save.inventory,
                revision_id=current_save.revision_id,
                message="Concurrent duplicate operation ignored.",
            )

        # 3. Deduct consumed item safely and persist next save revision
        inv = dict(current_save.inventory)
        curr = inv.get(item_id, 0)
        inv[item_id] = max(0, curr - quantity)

        updated_save = await self.save_repo.create_or_update_save(
            player_id=player_id,
            revision_id=current_save.revision_id + 1,
            level=current_save.level,
            inventory=inv,
            game_state=current_save.game_state,
            device_id=device_id,
            client_saved_at=utc_now(),
        )

        return OfflineOperationResponse(
            status="APPLIED",
            operation_id=operation_id,
            inventory=updated_save.inventory,
            revision_id=updated_save.revision_id,
            message="Item consumed successfully.",
        )

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

        # Progression check: flags suspicious progression leaps
        if request.level > current_save.level + MAX_ALLOWED_LEVEL_JUMP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Progression anomaly detected: Level jump from {current_save.level} to {request.level} exceeds safety limit of {MAX_ALLOWED_LEVEL_JUMP} levels.",
            )

        # Process any offline operations submitted in this sync payload
        merged_inventory = dict(request.inventory)
        if request.offline_operations:
            for op in request.offline_operations:
                existing_op = await self.session.execute(
                    select(OfflineOperation).where(OfflineOperation.idempotency_key == op.operation_id)
                )
                if existing_op.scalar_one_or_none():
                    continue

                try:
                    offline_rec = OfflineOperation(
                        player_id=player_id,
                        device_id=op.device_id or request.device_id,
                        operation_type=op.operation_type,
                        idempotency_key=op.operation_id,
                        payload={"item_id": op.item_id, "quantity": op.quantity},
                        status="APPLIED",
                        client_timestamp=op.client_timestamp or request.client_saved_at,
                        processed_at=utc_now(),
                    )
                    self.session.add(offline_rec)
                    await self.session.flush()
                except IntegrityError:
                    await self.session.rollback()
                    continue

        # Case 2: Clean sequential update
        if request.base_revision_id == current_save.revision_id:
            next_revision = current_save.revision_id + 1
            resolved_level = max(current_save.level, request.level)
            
            try:
                saved = await self.save_repo.create_or_update_save(
                    player_id=player_id,
                    revision_id=next_revision,
                    level=resolved_level,
                    inventory=merged_inventory,
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
                await self.session.rollback()
                current_save = await self.save_repo.get_latest_save(player_id)

        # Case 3: Stale base revision or concurrency collision -> SEMANTIC 3-WAY MERGE
        merged_level = max(current_save.level, request.level)

        base_save = await self.save_repo.get_by_revision(player_id, request.base_revision_id)
        merged_inventory = dict(current_save.inventory)

        if base_save and base_save.inventory:
            for item in set(list(request.inventory.keys()) + list(base_save.inventory.keys())):
                client_qty = request.inventory.get(item, 0)
                base_qty = base_save.inventory.get(item, 0)
                delta = client_qty - base_qty
                server_current_qty = current_save.inventory.get(item, 0)
                merged_inventory[item] = max(0, server_current_qty + delta)
        else:
            merged_inventory = dict(current_save.inventory)

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
            message="Conflict detected: Applied 3-way semantic merge with delta reconciliation.",
        )
