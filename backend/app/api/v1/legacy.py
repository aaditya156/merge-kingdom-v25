from typing import Annotated, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.schemas.save import LegacySaveRequest, LegacySaveResponse
from backend.app.repositories.player_repo import PlayerRepository
from backend.app.repositories.save_repo import SaveRepository
from backend.app.models.entitlement import Entitlement
from backend.app.models.wallet import Wallet
from backend.app.models.migration import MigrationRecord
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.device import DeviceRegistration
from backend.app.models.base import utc_now

router = APIRouter(prefix="/legacy", tags=["Legacy Compatibility (v2.0 - v2.4)"])

NO_ADS_LEGACY_PRODUCTS = ["no_ads_bundle", "no_ads_standalone", "no_ads_legacy"]


@router.post("/sync", response_model=LegacySaveResponse, status_code=status.HTTP_200_OK)
async def legacy_sync(
    payload: LegacySaveRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    x_device_id: Annotated[Optional[str], Header(alias="X-Device-Id")] = None,
):
    player_repo = PlayerRepository(session)
    save_repo = SaveRepository(session)

    # Priority 2 Fix: Authenticate / bind device to player_id
    player = await player_repo.get_by_id(payload.player_id, load_devices=True)

    if not player:
        # Initial registration for this legacy player
        player = await player_repo.create_player(payload.player_id)
        if x_device_id:
            await player_repo.register_device(
                player_id=payload.player_id,
                device_id=x_device_id,
                platform="Android",
                os_version="Legacy Client",
                app_version="2.4",
            )
    else:
        # Existing player: if player has registered devices, verify that requesting device is authorized
        if player.devices:
            registered_device_ids = {d.device_id for d in player.devices}
            if x_device_id and x_device_id not in registered_device_ids:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Unauthorized: Device is not bound to this player account.",
                )

    # Priority 2 Fix: Do NOT grant No Ads based merely on client payload.no_ads flag!
    # Check if an authoritative active entitlement already exists on the server
    ent_query = await session.execute(
        select(Entitlement).where(
            Entitlement.player_id == payload.player_id,
            Entitlement.entitlement_key == "no_ads",
            Entitlement.is_active == True,
        )
    )
    ent = ent_query.scalar_one_or_none()

    # If not on server, check for verified purchase evidence in purchase_records
    if not ent:
        purchase_evidence = (await session.execute(
            select(PurchaseRecord).where(
                PurchaseRecord.player_id == payload.player_id,
                PurchaseRecord.verification_status.in_(["VERIFIED", "LEGACY"]),
                PurchaseRecord.product_id.in_(NO_ADS_LEGACY_PRODUCTS),
            )
        )).first()

        if purchase_evidence:
            ent = Entitlement(
                player_id=payload.player_id,
                entitlement_key="no_ads",
                is_active=True,
                granted_by_source="IAP_PURCHASE_RESTORE",
            )
            session.add(ent)
            await session.flush()

    # Authoritative state is derived purely from trusted server records
    authoritative_no_ads = True if (ent and ent.is_active) else False

    # 3. Retrieve latest server save
    current_save = await save_repo.get_latest_save(payload.player_id)
    resolved_level = payload.level
    merged_inventory = payload.inventory
    next_revision = 1

    if current_save:
        next_revision = current_save.revision_id + 1
        resolved_level = max(current_save.level, payload.level)
        merged_inventory = dict(current_save.inventory)

    # Save to server
    await save_repo.create_or_update_save(
        player_id=payload.player_id,
        revision_id=next_revision,
        level=resolved_level,
        inventory=merged_inventory,
        game_state={},
        device_id=x_device_id or "legacy_client",
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

    # Preserve migrated wallet balances against legacy uploads
    if wallet and not mig_record:
        wallet.coins_balance = max(wallet.coins_balance, payload.coins)

    current_timestamp_seconds = int(utc_now().timestamp())
    return LegacySaveResponse(
        player_id=payload.player_id,
        saved_at=current_timestamp_seconds,
        level=resolved_level,
        coins=wallet.coins_balance if wallet else payload.coins,
        inventory=merged_inventory,
        no_ads=authoritative_no_ads,
    )
