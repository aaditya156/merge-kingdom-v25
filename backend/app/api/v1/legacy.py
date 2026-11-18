from typing import Annotated
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.schemas.save import LegacySaveRequest, LegacySaveResponse
from backend.app.repositories.player_repo import PlayerRepository
from backend.app.repositories.save_repo import SaveRepository
from backend.app.models.entitlement import Entitlement
from backend.app.models.wallet import Wallet
from backend.app.models.migration import MigrationRecord
from backend.app.models.base import utc_now

router = APIRouter(prefix="/legacy", tags=["Legacy Compatibility (v2.0 - v2.4)"])


@router.post("/sync", response_model=LegacySaveResponse, status_code=status.HTTP_200_OK)
async def legacy_sync(
    payload: LegacySaveRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
):
    player_repo = PlayerRepository(session)
    save_repo = SaveRepository(session)

    # 1. Ensure player exists
    player = await player_repo.get_by_id(payload.player_id)
    if not player:
        player = await player_repo.create_player(payload.player_id)

    # 2. Check entitlement (No Ads protection - solves Incident 3!)
    ent_query = await session.execute(
        select(Entitlement).where(
            Entitlement.player_id == payload.player_id,
            Entitlement.entitlement_key == "no_ads",
            Entitlement.is_active == True,
        )
    )
    ent = ent_query.scalar_one_or_none()

    # If incoming payload has no_ads=True, make sure server records it
    if payload.no_ads and not ent:
        ent = Entitlement(
            player_id=payload.player_id,
            entitlement_key="no_ads",
            is_active=True,
            granted_by_source="LEGACY_SAVE_RESTORE",
        )
        session.add(ent)
        await session.flush()

    # Authoritative No Ads state: True if server entitlement exists, else incoming
    authoritative_no_ads = True if ent and ent.is_active else payload.no_ads

    # 3. Retrieve latest server save
    current_save = await save_repo.get_latest_save(payload.player_id)
    
    # Semantic merge: Level progress is monotonic
    resolved_level = payload.level
    merged_inventory = payload.inventory
    next_revision = 1

    if current_save:
        next_revision = current_save.revision_id + 1
        resolved_level = max(current_save.level, payload.level)
        # Merge inventory
        merged_inventory = dict(current_save.inventory)
        for item, count in payload.inventory.items():
            merged_inventory[item] = max(merged_inventory.get(item, 0), count)

    # Save to server
    saved = await save_repo.create_or_update_save(
        player_id=payload.player_id,
        revision_id=next_revision,
        level=resolved_level,
        inventory=merged_inventory,
        game_state={},
        device_id="legacy_client",
        client_saved_at=datetime.fromtimestamp(payload.saved_at, tz=timezone.utc),
    )

    # 4. Check if player has already migrated to v2.5
    mig_query = await session.execute(
        select(MigrationRecord).where(
            MigrationRecord.player_id == payload.player_id,
            MigrationRecord.status == "COMPLETED"
        )
    )
    mig_record = mig_query.scalar_one_or_none()

    wallet_query = await session.execute(
        select(Wallet).where(Wallet.player_id == payload.player_id)
    )
    wallet = wallet_query.scalar_one_or_none()

    # CRITICAL AUDIT FIX: If player already migrated, DO NOT re-inflate coins from v2.4!
    # Doing so would allow double-spending (player keeps converted gems AND gets coins back).
    # Only update coins if not migrated yet.
    if wallet and not mig_record:
        wallet.coins_balance = max(wallet.coins_balance, payload.coins)

    # Return standard v2.4 JSON structure with current server timestamp
    current_timestamp_seconds = int(utc_now().timestamp())
    return LegacySaveResponse(
        player_id=payload.player_id,
        saved_at=current_timestamp_seconds,
        level=resolved_level,
        coins=wallet.coins_balance if wallet else payload.coins,
        inventory=merged_inventory,
        no_ads=authoritative_no_ads,
    )
