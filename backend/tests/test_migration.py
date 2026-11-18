import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.wallet import Wallet
from backend.app.models.base import utc_now


@pytest.mark.asyncio
async def test_migration_pfp_policy_and_idempotency(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login player p_8812 (from Fact 1)
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_8812", "device_id": "phone_mig_test", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Setup: Manually insert legacy wallet balance (5400 coins) and purchase records (2000 purchased coins)
        wallet = (await db_session.execute(
            Wallet.__table__.select().where(Wallet.player_id == "p_8812")
        )).first()
        
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_8812")
            .values(coins_balance=5400, gems_balance=0)
        )
        # 2 purchases of $9.99 (999 cents * 10 = ~2000 purchased coins)
        rec1 = PurchaseRecord(
            player_id="p_8812",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="GPA.mig_sample_01",
            product_id="gems_tier_2",
            purchase_type="CURRENCY",
            price_cents=100,  # 100 * 10 = 1000 coins
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        rec2 = PurchaseRecord(
            player_id="p_8812",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="GPA.mig_sample_02",
            product_id="gems_tier_2",
            purchase_type="CURRENCY",
            price_cents=100,  # 100 * 10 = 1000 coins
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        db_session.add_all([rec1, rec2])
        await db_session.commit()

        # 2. Check Migration Status
        status_res = await client.get("/api/v1/migration/status", headers=headers)
        assert status_res.status_code == 200
        assert status_res.json()["migration_required"] is True

        # 3. Execute Migration (PFP Policy)
        # Expected:
        # lifetime_purchased_coins = 2000
        # current_coins = 5400
        # converted_gems = min(5400, 2000) = 2000
        # converted_coins = 5400 - 2000 = 3400
        mig_res = await client.post("/api/v1/migration/migrate", headers=headers)
        assert mig_res.status_code == 200
        data = mig_res.json()
        assert data["status"] == "COMPLETED"
        assert data["original_coins"] == 5400
        assert data["lifetime_purchased_coins"] == 2000
        assert data["converted_gems"] == 2000
        assert data["converted_coins"] == 3400
        assert data["policy_applied"] == "PURCHASED_FIRST_PROTECTION"

        # Verify wallet balance
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["coins_balance"] == 3400
        assert bal["gems_balance"] == 2000

        # 4. Repeat Migration call (Test Idempotency)
        mig_res_repeat = await client.post("/api/v1/migration/migrate", headers=headers)
        assert mig_res_repeat.status_code == 200
        repeat_data = mig_res_repeat.json()
        assert repeat_data["status"] == "COMPLETED"
        assert repeat_data["converted_gems"] == 2000

        # Verify wallet was not altered by repeated migration
        bal_repeat = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal_repeat["coins_balance"] == 3400
        assert bal_repeat["gems_balance"] == 2000

        # 5. Admin overview endpoint check
        admin_res = await client.get("/api/v1/admin/players/p_8812")
        assert admin_res.status_code == 200
        admin_data = admin_res.json()
        assert admin_data["wallet"]["gems"] == 2000
        assert admin_data["migration"]["status"] == "COMPLETED"

    app.dependency_overrides.clear()
