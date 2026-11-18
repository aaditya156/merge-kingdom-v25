from typing import Optional, Dict, Any, List
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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

        try:
            # 2. Lock wallet row exclusively
            wallet = await self.wallet_repo.get_wallet(player_id, for_update=True)
            save = await self.save_repo.get_latest_save(player_id)
            current_coins = wallet.coins_balance

            # 3. Calculate lifetime purchased coins strictly from recorded historical purchase quantities
            # Fact 4: Server has record of every purchase: player ID, pack ID, number of coins in the pack, timestamp.
            # Strictly exclude gem purchases and No Ads purchases.
            purchase_query = select(PurchaseRecord).where(
                PurchaseRecord.player_id == player_id,
                PurchaseRecord.verification_status.in_(["VERIFIED", "LEGACY"]),
            )
            all_purchases = (await self.session.execute(purchase_query)).scalars().all()

            lifetime_purchased_coins = 0
            unresolved_purchases: List[Dict[str, Any]] = []

            for p in all_purchases:
                # Explicitly restrict migration calculations strictly to historical COIN_PACK purchases.
                # All other purchase types (CURRENCY, ENTITLEMENT, HYBRID, GEM_PACKS) are strictly excluded.
                if p.purchase_type != "COIN_PACK":
                    continue

                if p.product_id.startswith("gems_") or "no_ads" in p.product_id:
                    continue

                # Extract recorded historical coin quantity:
                # Fact 4 explicitly records 'number of coins in the pack' on the purchase record.
                recorded_coins: Optional[int] = None
                if p.coins_in_pack is not None:
                    try:
                        val = int(p.coins_in_pack)
                        if val > 0:
                            recorded_coins = val
                    except (ValueError, TypeError):
                        recorded_coins = None

                if recorded_coins is None and p.raw_receipt and isinstance(p.raw_receipt, dict):
                    receipt_coins = p.raw_receipt.get("coins_in_pack")
                    if receipt_coins is not None:
                        try:
                            val = int(receipt_coins)
                            if val > 0:
                                recorded_coins = val
                        except (ValueError, TypeError):
                            recorded_coins = None

                if recorded_coins is not None:
                    lifetime_purchased_coins += recorded_coins
                else:
                    # Missing or invalid historical purchase quantity records:
                    # Do NOT invent quantities or apply guessed multipliers.
                    # Flag as unresolved for Finance/Product audit.
                    unresolved_purchases.append({
                        "store_transaction_id": p.store_transaction_id,
                        "product_id": p.product_id,
                        "error": "MISSING_OR_INVALID_COIN_QUANTITY",
                    })

            # 4. Apply the Approved Policy: PURCHASED-FIRST PROTECTION (PFP)
            converted_gems = min(current_coins, lifetime_purchased_coins)
            converted_coins = current_coins - converted_gems

            # 5. Capture immutable snapshot of legacy state and audit details
            snapshot = {
                "coins_before": wallet.coins_balance,
                "gems_before": wallet.gems_balance,
                "save_level": save.level if save else 1,
                "save_inventory": save.inventory if save else {},
                "unresolved_purchases": unresolved_purchases,
            }

            # 6. Insert Migration Record (Protected by database uniqueness constraint on player_id)
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
                await self.wallet_repo.mutate_balance(
                    player_id=player_id,
                    currency_type="COIN",
                    amount=-converted_gems,
                    transaction_type="MIGRATION_CONVERSION",
                    reference_id=mig_record.id,
                    idempotency_key=f"mig_debit_coin_{player_id}",
                    metadata={"converted_to_gems": converted_gems},
                )
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

        except IntegrityError:
            # Transaction-safe concurrent collision handling:
            # If two simultaneous migration requests race to insert MigrationRecord,
            # the database uniqueness constraint on player_id catches the collision.
            await self.session.rollback()
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
                    message="Concurrent migration resolved: Idempotent response returned.",
                )
            raise
