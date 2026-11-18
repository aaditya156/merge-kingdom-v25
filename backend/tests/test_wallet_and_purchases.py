import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db


@pytest.mark.asyncio
async def test_wallet_earning_spending_and_insufficient_funds(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_wallet_test", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Initial balance should be 0 coins, 0 gems
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["coins_balance"] == 0
        assert bal["gems_balance"] == 0

        # 2. Earn coins by beating level 1
        earn_res = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 1, "coins_earned": 100, "score": 2500},
        )
        assert earn_res.status_code == 200
        assert earn_res.json()["wallet"]["coins_balance"] == 100

        # 3. Spend 40 coins on booster
        spend_res = await client.post(
            "/api/v1/wallet/spend",
            headers=headers,
            json={"currency_type": "COIN", "amount": 40, "item_id": "booster_hammer"},
        )
        assert spend_res.status_code == 200
        assert spend_res.json()["wallet"]["coins_balance"] == 60

        # 4. Attempt to spend 100 coins (exceeds balance of 60) -> 400 Insufficient Funds
        fail_spend = await client.post(
            "/api/v1/wallet/spend",
            headers=headers,
            json={"currency_type": "COIN", "amount": 100, "item_id": "booster_super_shuffle"},
        )
        assert fail_spend.status_code == 400

        # Verify ledger has records
        txs = (await client.get("/api/v1/wallet/transactions", headers=headers)).json()
        assert len(txs) == 2  # 1 earn, 1 spend

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_purchase_verification_idempotency(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_iap_test", "platform": "iOS", "app_version": "2.5.0", "os_version": "iOS 17"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Verify Tier 2 Gems (500 gems)
        iap_res_1 = await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "apple_tx_1000998877",
                "product_id": "gems_tier_2",
            },
        )
        assert iap_res_1.status_code == 200
        assert iap_res_1.json()["gems_granted"] == 500
        assert iap_res_1.json()["new_gems_balance"] == 500

        # 2. Re-send identical purchase verification (simulating client retry storm)
        iap_res_2 = await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "apple_tx_1000998877",
                "product_id": "gems_tier_2",
            },
        )
        assert iap_res_2.status_code == 200
        assert iap_res_2.json()["gems_granted"] == 0  # Idempotent response!
        assert iap_res_2.json()["new_gems_balance"] == 500  # Gems balance NOT doubled!

    app.dependency_overrides.clear()
