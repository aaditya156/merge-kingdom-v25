import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.wallet import Wallet
from backend.app.models.entitlement import Entitlement
from backend.app.models.device import DeviceRegistration
from backend.app.models.base import utc_now
from backend.tests.conftest import TestSessionLocal


async def app_db_override():
    async with TestSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@pytest.mark.asyncio
async def test_client_supplied_migration_balance_inflation_ignored(db_session):
    """Test 1: Client sending legacy_coins=999999 cannot inflate migration balance."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create player with true server wallet balance of 200 coins
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_hacker_1", "device_id": "dev_hacker", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Set true server wallet balance to 200
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_hacker_1")
            .values(coins_balance=200, gems_balance=0)
        )
        await db_session.commit()

        # Attacker sends legacy_coins: 999999
        res = await client.post(
            "/api/v1/migration/migrate",
            headers=headers,
            json={"legacy_coins": 999999},
        )
        assert res.status_code == 200
        data = res.json()
        # Authoritative original_coins must remain 200, NOT 999999!
        assert data["original_coins"] == 200
        assert data["converted_coins"] == 200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_historical_purchase_calculation_excludes_gems_and_no_ads(db_session):
    """Test 2: Migration calculation only counts verified historical coin packs."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_coin_calc_test", "device_id": "dev_calc", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Set server wallet balance: 5000 coins
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_coin_calc_test")
            .values(coins_balance=5000, gems_balance=0)
        )

        # 1. Historical coin pack: coin_pack_medium (1200 coins)
        coin_rec = PurchaseRecord(
            player_id="p_coin_calc_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_coin_pack_01",
            product_id="coin_pack_medium",
            purchase_type="COIN_PACK",
            price_cents=499,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        # 2. Gem purchase: gems_tier_2 (500 gems) -> Must NOT count towards coin conversion
        gem_rec = PurchaseRecord(
            player_id="p_coin_calc_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_gem_pack_02",
            product_id="gems_tier_2",
            purchase_type="CURRENCY",
            price_cents=499,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        # 3. No ads purchase: no_ads_standalone -> Must NOT count towards coin conversion
        no_ads_rec = PurchaseRecord(
            player_id="p_coin_calc_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_no_ads_03",
            product_id="no_ads_standalone",
            purchase_type="ENTITLEMENT",
            price_cents=199,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        db_session.add_all([coin_rec, gem_rec, no_ads_rec])
        await db_session.commit()

        # Run migration
        res = await client.post("/api/v1/migration/migrate", headers=headers)
        assert res.status_code == 200
        data = res.json()
        # Lifetime purchased coins must be exactly 1200, NOT 1200 + 500 or price multipliers!
        assert data["lifetime_purchased_coins"] == 1200
        assert data["converted_gems"] == 1200
        assert data["converted_coins"] == 3800

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_forged_legacy_no_ads_entitlement_rejected(db_session):
    """Test 3: Old client uploading no_ads=True without server purchase evidence is NOT granted No Ads."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Player has never purchased No Ads
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_ad_forger", "device_id": "dev_forger", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]

        # Client uploads v2.4 save with forged no_ads: true
        legacy_res = await client.post(
            "/api/v1/legacy/sync",
            headers={"X-Device-Id": "dev_forger"},
            json={
                "player_id": "p_ad_forger",
                "saved_at": int(utc_now().timestamp()),
                "level": 10,
                "coins": 500,
                "inventory": {},
                "no_ads": True,  # Forged flag!
            },
        )
        assert legacy_res.status_code == 200
        # Server must override and return False because there is no verified purchase record
        assert legacy_res.json()["no_ads"] is False

        # Verify entitlement was NOT created in DB
        ent_res = await client.get("/api/v1/entitlements", headers={"Authorization": f"Bearer {token}"})
        assert len(ent_res.json()["entitlements"]) == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unauthorized_legacy_player_modification_blocked(db_session):
    """Test 4: Unbound device cannot tamper with another player's save via legacy endpoint."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Register victim player on device_victim
        await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_victim_99", "device_id": "device_victim", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )

        # Attacker on rogue_device attempts to upload save for p_victim_99
        rogue_res = await client.post(
            "/api/v1/legacy/sync",
            headers={"X-Device-Id": "rogue_device"},
            json={
                "player_id": "p_victim_99",
                "saved_at": int(utc_now().timestamp()),
                "level": 999,
                "coins": 0,
                "inventory": {},
                "no_ads": False,
            },
        )
        # Must be rejected with 403 Forbidden!
        assert rogue_res.status_code == 403

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_stale_inventory_does_not_restore_consumed_boosters(db_session):
    """Test 5: Spending booster on Device A must NOT be restored when Device B uploads stale inventory."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_main", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Initial Save: Player has 3 hammers (revision 1)
        save1 = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": 0,
                "level": 10,
                "inventory": {"hammer": 3, "shuffle": 1},
                "game_state": {},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "phone_main",
            },
        )
        assert save1.status_code == 200
        rev1 = save1.json()["revision_id"]

        # 2. Device A spends 2 hammers online (now has 1 hammer, revision 2)
        save2 = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": rev1,
                "level": 11,
                "inventory": {"hammer": 1, "shuffle": 1},
                "game_state": {},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "phone_main",
            },
        )
        assert save2.status_code == 200
        assert save2.json()["inventory"]["hammer"] == 1

        # 3. Device B was offline with base_revision_id=rev1, holding old 3 hammers
        # Device B reconnects and uploads
        stale_upload = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": rev1,  # Stale base revision
                "level": 10,
                "inventory": {"hammer": 3, "shuffle": 1},  # Stale inventory with 3 hammers
                "game_state": {},
                "client_saved_at": (utc_now() + timedelta(minutes=5)).isoformat(),
                "device_id": "tablet_offline",
            },
        )
        assert stale_upload.status_code == 200
        merged = stale_upload.json()
        # Hammer count must REMAIN 1! Consumed hammers are NOT restored!
        assert merged["inventory"]["hammer"] == 1

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_arbitrary_level_reward_amount_and_duplicate_manipulation(db_session):
    """Test 6: Level completion reward cannot exceed cap, and duplicate claims cannot manipulate reward."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_reward_test", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Attempting reward exceeding MAX_LEVEL_COMPLETION_COINS (e.g. 500 coins) -> 400
        bad_reward = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 1, "coins_earned": 500, "score": 100},
        )
        assert bad_reward.status_code == 400

        # 2. Legitimate reward of 50 coins -> 200
        good_reward = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 1, "coins_earned": 50, "score": 100},
        )
        assert good_reward.status_code == 200
        assert good_reward.json()["wallet"]["coins_balance"] == 50

        # 3. Duplicate request claiming a DIFFERENT amount (e.g. 100 coins) for same level -> 409 Conflict
        tampered_dup = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 1, "coins_earned": 100, "score": 100},
        )
        assert tampered_dup.status_code == 409

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_unknown_purchase_product_id_rejected(db_session):
    """Test 7: Unknown product IDs are rejected with 400 and do not grant default gems."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_iap_bad", "platform": "iOS", "app_version": "2.5.0", "os_version": "iOS 17"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        res = await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "fake_tx_999",
                "product_id": "nonexistent_hacked_gem_pack",
            },
        )
        assert res.status_code == 400

        # Verify wallet still has 0 gems
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["gems_balance"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_migration_rollback_after_gems_spent_limitation(db_session):
    """Test 8: Documenting and testing migration state after converted gems are spent."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_spend_rollback", "device_id": "dev_sr", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Player has 500 coins and 500 purchased coins
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_spend_rollback")
            .values(coins_balance=500, gems_balance=0)
        )
        p_rec = PurchaseRecord(
            player_id="p_spend_rollback",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_sr_01",
            product_id="coin_pack_small",
            purchase_type="COIN_PACK",
            price_cents=99,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        db_session.add(p_rec)
        await db_session.commit()

        # Migrate: converts 500 coins -> 500 gems
        mig = await client.post("/api/v1/migration/migrate", headers=headers)
        assert mig.status_code == 200
        assert mig.json()["converted_gems"] == 500

        # Player spends 400 gems on store item
        spend = await client.post(
            "/api/v1/wallet/spend",
            headers=headers,
            json={"currency_type": "GEM", "amount": 400, "item_id": "booster_pack"},
        )
        assert spend.status_code == 200
        assert spend.json()["wallet"]["gems_balance"] == 100

        # Limitation Demonstration: If an admin attempted a naive rollback (reverting 500 gems),
        # the wallet only has 100 gems left. Naive deduction would cause a negative balance.
        # This confirms that rollback requires manual audit reconciliation when converted currency has been consumed.
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["gems_balance"] == 100
        assert bal["coins_balance"] == 0

    app.dependency_overrides.clear()
