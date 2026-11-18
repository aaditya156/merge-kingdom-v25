from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.entitlement import Entitlement
from backend.app.repositories.wallet_repo import WalletRepository
from backend.app.schemas.purchase import VerifyPurchaseRequest, VerifyPurchaseResponse
from backend.app.models.base import utc_now

# In-Game Store Catalog Mapping
PRODUCT_CATALOG = {
    "gems_tier_1": {"gems": 100, "price_cents": 99, "type": "CURRENCY", "entitlements": []},
    "gems_tier_2": {"gems": 500, "price_cents": 499, "type": "CURRENCY", "entitlements": []},
    "gems_tier_3": {"gems": 1200, "price_cents": 999, "type": "CURRENCY", "entitlements": []},
    "no_ads_bundle": {"gems": 200, "price_cents": 299, "type": "HYBRID", "entitlements": ["no_ads"]},
    "no_ads_standalone": {"gems": 0, "price_cents": 199, "type": "ENTITLEMENT", "entitlements": ["no_ads"]},
}


class PurchaseService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.wallet_repo = WalletRepository(session)

    async def verify_purchase(
        self,
        player_id: str,
        request: VerifyPurchaseRequest,
    ) -> VerifyPurchaseResponse:
        # 1. Duplicate check (Idempotency on store_transaction_id)
        query = select(PurchaseRecord).where(
            PurchaseRecord.store_transaction_id == request.store_transaction_id
        )
        result = await self.session.execute(query)
        existing_record = result.scalar_one_or_none()

        wallet = await self.wallet_repo.get_wallet(player_id)

        if existing_record:
            # Already processed, return idempotent response
            return VerifyPurchaseResponse(
                verification_status=existing_record.verification_status,
                store_transaction_id=existing_record.store_transaction_id,
                product_id=existing_record.product_id,
                gems_granted=0,
                entitlements_granted=[],
                new_coins_balance=wallet.coins_balance,
                new_gems_balance=wallet.gems_balance,
                message="Transaction already processed and verified.",
            )

        # 2. Lookup product in catalog
        product = PRODUCT_CATALOG.get(
            request.product_id,
            {"gems": 100, "price_cents": 99, "type": "CURRENCY", "entitlements": []}
        )
        gems_to_grant = product["gems"]
        entitlements_to_grant = product["entitlements"]

        # 3. Create purchase record
        purchase_rec = PurchaseRecord(
            player_id=player_id,
            store_platform=request.store_platform.upper(),
            store_transaction_id=request.store_transaction_id,
            product_id=request.product_id,
            purchase_type=product["type"],
            price_cents=product["price_cents"],
            verification_status="VERIFIED",
            purchased_at=utc_now(),
            verified_at=utc_now(),
        )
        self.session.add(purchase_rec)
        await self.session.flush()

        # 4. Grant Gems if applicable
        if gems_to_grant > 0:
            wallet, tx = await self.wallet_repo.mutate_balance(
                player_id=player_id,
                currency_type="GEM",
                amount=gems_to_grant,
                transaction_type="IAP_GRANT",
                reference_id=request.store_transaction_id,
                idempotency_key=f"iap_{request.store_transaction_id}",
            )

        # 5. Grant Entitlements if applicable
        for ent_key in entitlements_to_grant:
            ent_query = select(Entitlement).where(
                Entitlement.player_id == player_id,
                Entitlement.entitlement_key == ent_key,
            )
            ent_res = await self.session.execute(ent_query)
            existing_ent = ent_res.scalar_one_or_none()
            if existing_ent:
                existing_ent.is_active = True
                existing_ent.purchase_record_id = purchase_rec.id
            else:
                new_ent = Entitlement(
                    player_id=player_id,
                    entitlement_key=ent_key,
                    is_active=True,
                    granted_by_source="IAP_PURCHASE",
                    purchase_record_id=purchase_rec.id,
                )
                self.session.add(new_ent)

        await self.session.flush()

        return VerifyPurchaseResponse(
            verification_status="VERIFIED",
            store_transaction_id=request.store_transaction_id,
            product_id=request.product_id,
            gems_granted=gems_to_grant,
            entitlements_granted=entitlements_to_grant,
            new_coins_balance=wallet.coins_balance,
            new_gems_balance=wallet.gems_balance,
            message="Purchase successfully verified and credited.",
        )
