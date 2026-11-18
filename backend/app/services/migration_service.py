from typing import Optional, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.migration import MigrationRecord
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.wallet import Wallet
from backend.app.models.save import GameSave
from backend.app.repositories.wallet_repo import WalletRepository
from backend.app.repositories.save_repo import SaveRepository
from backend.app.schemas.migration import (
    MigrationStatusResponse,
    ExecuteMigrationRequest,
    MigrationResultResponse,
)
from backend.app.models.base import utc_now

# Priority 1: Documented Historical Coin Packs (v2.0 - v2.4, Fact 4)
# In v2.4, players bought coin packs. Only documented coin packs are credited as purchased coins.
# Gem packs and No Ads bundles are strictly excluded from coin purchase calculations.
HISTORICAL_COIN_PACK_CATALOG: Dict[str, int] = {
    "coin_pack_small": 500,
    "coin_pack_medium": 1200,
    "coin_pack_large": 2500,
    "coin_pack_chest": 6500,
    "coin_pack_vault": 15000,
    "coin_pack_starter": 500,
    "legacy_coin_pack_500": 500,
    "legacy_coin_pack_1000": 1000,
}


class MigrationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.wallet_repo = WalletRepository(session)
        self.save_repo = SaveRepository(session)

    async def get_status(self, player_id: str) -> MigrationStatusResponse:
        mig_query = select(MigrationRecord).where(MigrationRecord.player_id == player_id)
        result = await self.session.execute(mig_query)
        record = result.scalar_one_or_none()

        if record:
            return MigrationStatusResponse(
                player_id=player_id,
                migration_required=False,
                status=record.status,
                original_coins=record.original_coins,
                converted_coins=record.converted_coins,
                converted_gems=record.converted_gems,
                migrated_at=record.migrated_at,
            )

        wallet = await self.wallet_repo.get_wallet(player_id)
        save = await self.save_repo.get_latest_save(player_id)

        has_legacy_state = (wallet and wallet.coins_balance > 0) or (save and save.level > 1)

        return MigrationStatusResponse(
            player_id=player_id,
            migration_required=has_legacy_state,
            status="PENDING" if has_legacy_state else "NOT_REQUIRED",
        )

    async def execute_migration(
        self,
        player_id: str,
        request: Optional[ExecuteMigrationRequest] = None,
    ) -> MigrationResultResponse:
        # 1. Idempotency check: Has this player already migrated?
        mig_query = select(MigrationRecord).where(MigrationRecord.player_id == player_id)
        result = await self.session.execute(mig_query)
        existing = result.scalar_one_or_none()

        if existing and existing.status == "COMPLETED":
            return MigrationResultResponse(
                player_id=existing.player_id,
                status=existing.status,
                original_coins=existing.original_coins,
                lifetime_purchased_coins=existing.lifetime_purchased_coins,
                converted_coins=existing.converted_coins,
                converted_gems=existing.converted_gems,
                policy_applied=existing.policy_applied,
                migrated_at=existing.migrated_at,
                message="Player already migrated. Idempotent response returned.",
            )

        # 2. Lock wallet row exclusively
        wallet = await self.wallet_repo.get_wallet(player_id, for_update=True)
        save = await self.save_repo.get_latest_save(player_id)

        # Priority 1 Fix: NEVER accept a client-supplied legacy_coins value as authoritative.
        # Use exclusively the trusted server-side wallet balance / snapshot.
        current_coins = wallet.coins_balance

        # 3. Calculate lifetime purchased coins from actual historical coin packs
        # Fact 4: Server has record of each coin pack bought: player, pack, number of coins, time.
        # Strictly exclude gem purchases (gems_tier_*) and No Ads purchases (no_ads_*).
        purchase_query = select(PurchaseRecord).where(
            PurchaseRecord.player_id == player_id,
            PurchaseRecord.verification_status.in_(["VERIFIED", "LEGACY"]),
        )
        all_purchases = (await self.session.execute(purchase_query)).scalars().all()

        lifetime_purchased_coins = 0
        for p in all_purchases:
            # Exclude non-coin purchases explicitly
            if p.product_id.startswith("gems_") or "no_ads" in p.product_id:
                continue

            if p.product_id in HISTORICAL_COIN_PACK_CATALOG:
                lifetime_purchased_coins += HISTORICAL_COIN_PACK_CATALOG[p.product_id]
            elif p.raw_receipt and isinstance(p.raw_receipt, dict) and "coins_in_pack" in p.raw_receipt:
                lifetime_purchased_coins += int(p.raw_receipt["coins_in_pack"])
            elif p.purchase_type == "COIN_PACK":
                # Known coin pack without catalog mapping: fallback only if explicitly documented
                pass

        # 4. Apply the Approved Policy: PURCHASED-FIRST PROTECTION (PFP)
        # Gems = min(current_coins, lifetime_purchased_coins)
        # Coins = current_coins - Gems
        converted_gems = min(current_coins, lifetime_purchased_coins)
        converted_coins = current_coins - converted_gems

        # 5. Capture immutable snapshot of legacy state before modifying
        snapshot = {
            "coins_before": wallet.coins_balance,
            "gems_before": wallet.gems_balance,
            "save_level": save.level if save else 1,
            "save_inventory": save.inventory if save else {},
        }

        # 6. Insert Migration Record
        mig_record = MigrationRecord(
            player_id=player_id,
            source_version="2.4",
            target_version="2.5",
            original_coins=current_coins,
            lifetime_purchased_coins=lifetime_purchased_coins,
            converted_coins=converted_coins,
            converted_gems=converted_gems,
            policy_applied="PURCHASED_FIRST_PROTECTION",
            original_save_snapshot=snapshot,
            status="COMPLETED",
            migrated_at=utc_now(),
        )
        self.session.add(mig_record)
        await self.session.flush()

        # 7. Record balanced audit ledger entries
        if converted_gems > 0:
            # Debit converted coins from wallet
            await self.wallet_repo.mutate_balance(
                player_id=player_id,
                currency_type="COIN",
                amount=-converted_gems,
                transaction_type="MIGRATION_CONVERSION",
                reference_id=mig_record.id,
                idempotency_key=f"mig_debit_coin_{player_id}",
                metadata={"converted_to_gems": converted_gems},
            )
            # Credit converted gems into wallet
            await self.wallet_repo.mutate_balance(
                player_id=player_id,
                currency_type="GEM",
                amount=converted_gems,
                transaction_type="MIGRATION_CONVERSION",
                reference_id=mig_record.id,
                idempotency_key=f"mig_credit_gem_{player_id}",
                metadata={"converted_from_coins": converted_gems},
            )
        else:
            wallet.lock_version += 1
            wallet.updated_at = utc_now()

        await self.session.flush()

        return MigrationResultResponse(
            player_id=player_id,
            status="COMPLETED",
            original_coins=current_coins,
            lifetime_purchased_coins=lifetime_purchased_coins,
            converted_coins=converted_coins,
            converted_gems=converted_gems,
            policy_applied="PURCHASED_FIRST_PROTECTION",
            migrated_at=mig_record.migrated_at,
            message="Migration successfully executed under Purchased-First Protection policy.",
        )
