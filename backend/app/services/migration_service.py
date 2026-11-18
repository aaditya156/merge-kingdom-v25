from typing import Optional
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

        # Determine current legacy coins balance
        current_coins = wallet.coins_balance
        if request and request.legacy_coins is not None:
            current_coins = max(current_coins, request.legacy_coins)

        # 3. Calculate lifetime purchased coins from purchase_records
        purchase_query = select(PurchaseRecord).where(
            PurchaseRecord.player_id == player_id,
            PurchaseRecord.verification_status == "VERIFIED",
        )
        purchases = (await self.session.execute(purchase_query)).scalars().all()
        lifetime_purchased_coins = sum(p.price_cents * 10 for p in purchases) if purchases else 0

        # 4. Apply the Approved Policy: PURCHASED-FIRST PROTECTION (PFP)
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
            # If 0 gems converted (Pure F2P), just touch lock version
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
