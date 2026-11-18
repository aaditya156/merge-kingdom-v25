from typing import Annotated, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.models.player import PlayerProfile
from backend.app.models.wallet import Wallet
from backend.app.models.save import GameSave
from backend.app.models.device import DeviceRegistration
from backend.app.models.entitlement import Entitlement
from backend.app.models.migration import MigrationRecord
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.ledger import CurrencyTransaction

router = APIRouter(prefix="/admin", tags=["Administrative & Diagnostics"])


@router.get("/players/{player_id}", status_code=status.HTTP_200_OK)
async def inspect_player(
    player_id: str,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    player = (await session.execute(
        select(PlayerProfile).where(PlayerProfile.player_id == player_id)
    )).scalar_one_or_none()

    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    wallet = (await session.execute(
        select(Wallet).where(Wallet.player_id == player_id)
    )).scalar_one_or_none()

    save = (await session.execute(
        select(GameSave).where(GameSave.player_id == player_id, GameSave.is_latest == True)
    )).scalar_one_or_none()

    devices = (await session.execute(
        select(DeviceRegistration).where(DeviceRegistration.player_id == player_id)
    )).scalars().all()

    entitlements = (await session.execute(
        select(Entitlement).where(Entitlement.player_id == player_id)
    )).scalars().all()

    mig_record = (await session.execute(
        select(MigrationRecord).where(MigrationRecord.player_id == player_id)
    )).scalar_one_or_none()

    recent_txs = (await session.execute(
        select(CurrencyTransaction).where(CurrencyTransaction.player_id == player_id).order_by(CurrencyTransaction.created_at.desc()).limit(10)
    )).scalars().all()

    return {
        "player_id": player.player_id,
        "nickname": player.nickname,
        "highest_level": player.highest_level,
        "wallet": {
            "coins": wallet.coins_balance if wallet else 0,
            "gems": wallet.gems_balance if wallet else 0,
            "lock_version": wallet.lock_version if wallet else 0,
        },
        "latest_save": {
            "revision_id": save.revision_id if save else 0,
            "level": save.level if save else 1,
            "inventory": save.inventory if save else {},
            "server_saved_at": save.server_saved_at.isoformat() if save else None,
        },
        "devices": [
            {
                "device_id": d.device_id,
                "platform": d.platform,
                "os_version": d.os_version,
                "app_version": d.app_version,
                "last_seen_at": d.last_seen_at.isoformat(),
            }
            for d in devices
        ],
        "entitlements": {e.entitlement_key: e.is_active for e in entitlements},
        "migration": {
            "status": mig_record.status if mig_record else "NOT_MIGRATED",
            "policy": mig_record.policy_applied if mig_record else None,
            "original_coins": mig_record.original_coins if mig_record else None,
            "converted_gems": mig_record.converted_gems if mig_record else None,
            "converted_coins": mig_record.converted_coins if mig_record else None,
        },
        "recent_transactions": [
            {
                "id": t.id,
                "currency": t.currency_type,
                "amount": t.amount,
                "type": t.transaction_type,
                "balance_after": t.balance_after,
                "created_at": t.created_at.isoformat(),
            }
            for t in recent_txs
        ]
    }


@router.get("/metrics", status_code=status.HTTP_200_OK)
async def get_metrics(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Dict[str, Any]:
    total_players = (await session.execute(select(func.count(PlayerProfile.player_id)))).scalar_one()
    total_devices = (await session.execute(select(func.count(DeviceRegistration.id)))).scalar_one()
    total_migrations = (await session.execute(
        select(func.count(MigrationRecord.id)).where(MigrationRecord.status == "COMPLETED")
    )).scalar_one()
    total_coins = (await session.execute(select(func.coalesce(func.sum(Wallet.coins_balance), 0)))).scalar_one()
    total_gems = (await session.execute(select(func.coalesce(func.sum(Wallet.gems_balance), 0)))).scalar_one()

    return {
        "total_players": total_players,
        "total_registered_devices": total_devices,
        "total_completed_migrations": total_migrations,
        "currency_in_circulation": {
            "coins": total_coins,
            "gems": total_gems,
        }
    }
