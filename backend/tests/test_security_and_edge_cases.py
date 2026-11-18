import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.wallet import Wallet
from backend.app.models.entitlement import Entitlement
from backend.app.models.device import DeviceRegistration
from backend.app.models.migration import MigrationRecord
from backend.app.models.ledger import CurrencyTransaction
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

        # 1. Historical coin pack: coin_pack_medium (1200 coins recorded)
        coin_rec = PurchaseRecord(
            player_id="p_coin_calc_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_coin_pack_01",
            product_id="coin_pack_medium",
            purchase_type="COIN_PACK",
            coins_in_pack=1200,
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
            coins_in_pack=500,
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


@pytest.mark.asyncio
async def test_legacy_device_authentication_and_unauthorized_access(db_session):
    """Test 9: Legacy device auth - missing header returns 401, rogue device returns 403, initial binding works."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Missing X-Device-Id header returns 401 Unauthorized
        res_no_header = await client.post(
            "/api/v1/legacy/sync",
            json={
                "player_id": "p_leg_auth_1",
                "saved_at": int(utc_now().timestamp()),
                "level": 5,
                "coins": 100,
                "inventory": {},
                "no_ads": False,
            },
        )
        assert res_no_header.status_code == 401
        assert "X-Device-Id" in res_no_header.json()["detail"]

        # 2. Initial binding: New player syncs with valid X-Device-Id -> 200 and binds device
        res_bind = await client.post(
            "/api/v1/legacy/sync",
            headers={"X-Device-Id": "device_leg_owner"},
            json={
                "player_id": "p_leg_auth_1",
                "saved_at": int(utc_now().timestamp()),
                "level": 5,
                "coins": 100,
                "inventory": {},
                "no_ads": False,
            },
        )
        assert res_bind.status_code == 200

        # 3. Attempting to access p_leg_auth_1 from an unknown/unbound device returns 403 Forbidden
        res_rogue = await client.post(
            "/api/v1/legacy/sync",
            headers={"X-Device-Id": "device_leg_attacker"},
            json={
                "player_id": "p_leg_auth_1",
                "saved_at": int(utc_now().timestamp()),
                "level": 99,
                "coins": 0,
                "inventory": {},
                "no_ads": False,
            },
        )
        assert res_rogue.status_code == 403
        assert "not bound" in res_rogue.json()["detail"]

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_historical_purchase_missing_and_invalid_records_not_invented(db_session):
    """Test 10: Missing/invalid historical purchase quantities are flagged, not guessed or multiplied."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_invalid_purch_test", "device_id": "dev_inv_p", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Wallet has 2000 coins
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_invalid_purch_test")
            .values(coins_balance=2000, gems_balance=0)
        )

        # Purchase 1: Valid recorded coins (500 coins)
        p1 = PurchaseRecord(
            player_id="p_invalid_purch_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_valid_500",
            product_id="custom_coin_pack_500",
            purchase_type="COIN_PACK",
            coins_in_pack=500,
            price_cents=499,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        # Purchase 2: Missing coin quantity (coins_in_pack=None, raw_receipt=None)
        p2 = PurchaseRecord(
            player_id="p_invalid_purch_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_missing_qty",
            product_id="unrecorded_pack_mystery",
            purchase_type="COIN_PACK",
            coins_in_pack=None,
            price_cents=999,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        # Purchase 3: Invalid corrupted coin quantity (negative coins)
        p3 = PurchaseRecord(
            player_id="p_invalid_purch_test",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_corrupt_negative",
            product_id="bad_pack_negative",
            purchase_type="COIN_PACK",
            coins_in_pack=-1000,
            price_cents=999,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        db_session.add_all([p1, p2, p3])
        await db_session.commit()

        # Execute migration
        res = await client.post("/api/v1/migration/migrate", headers=headers)
        assert res.status_code == 200
        data = res.json()

        # Lifetime purchased coins must strictly be 500 (from p1).
        # It must NOT invent 999*10 for p2 or guess negative values for p3!
        assert data["lifetime_purchased_coins"] == 500
        assert data["converted_gems"] == 500
        assert data["converted_coins"] == 1500

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_same_offline_inventory_operation_submitted_repeatedly_from_two_devices(db_session):
    """Test 11: Deduplication ensures the same offline consumption operation cannot be applied twice across devices."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_dedup_test", "device_id": "phone_alpha", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Initialize save with 5 hammers
        init_save = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": 0,
                "level": 10,
                "inventory": {"hammer": 5, "shuffle": 2},
                "game_state": {},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "phone_alpha",
            },
        )
        assert init_save.status_code == 200
        assert init_save.json()["inventory"]["hammer"] == 5

        # Device 1 submits offline consumption operation op_hammer_unique_99 (consumes 1 hammer)
        op_payload = {
            "operation_id": "op_hammer_unique_99",
            "item_id": "hammer",
            "quantity": 1,
            "device_id": "phone_alpha",
        }
        res_device_1 = await client.post("/api/v1/saves/operations/consume", headers=headers, json=op_payload)
        assert res_device_1.status_code == 200
        data1 = res_device_1.json()
        assert data1["status"] == "APPLIED"
        assert data1["inventory"]["hammer"] == 4

        # Device 2 (e.g. tablet) syncs and re-submits the exact same operation_id op_hammer_unique_99
        op_payload_dup = {
            "operation_id": "op_hammer_unique_99",
            "item_id": "hammer",
            "quantity": 1,
            "device_id": "tablet_beta",
        }
        res_device_2 = await client.post("/api/v1/saves/operations/consume", headers=headers, json=op_payload_dup)
        assert res_device_2.status_code == 200
        data2 = res_device_2.json()
        # Deduplicated! Must be ignored and NOT deduct another hammer!
        assert data2["status"] == "DUPLICATE_IGNORED"
        assert data2["inventory"]["hammer"] == 4

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_concurrent_simultaneous_migration_requests(db_session):
    """Test 12: Two simultaneous migration requests cannot double-convert the balance."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_concurrent_mig", "device_id": "dev_cm_1", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Wallet has 3000 coins
        await db_session.execute(
            Wallet.__table__.update()
            .where(Wallet.player_id == "p_concurrent_mig")
            .values(coins_balance=3000, gems_balance=0)
        )
        # Purchase record for 1000 coins
        rec = PurchaseRecord(
            player_id="p_concurrent_mig",
            store_platform="GOOGLE_PLAY",
            store_transaction_id="gpa_cm_rec_01",
            product_id="coin_pack_1000",
            purchase_type="COIN_PACK",
            coins_in_pack=1000,
            price_cents=999,
            verification_status="VERIFIED",
            purchased_at=utc_now(),
        )
        db_session.add(rec)
        await db_session.commit()

        # Fire two migration requests simultaneously
        req1 = client.post("/api/v1/migration/migrate", headers=headers)
        req2 = client.post("/api/v1/migration/migrate", headers=headers)

        res1, res2 = await asyncio.gather(req1, req2)

        assert res1.status_code == 200
        assert res2.status_code == 200

        # Both responses must agree on the converted numbers
        assert res1.json()["converted_gems"] == 1000
        assert res2.json()["converted_gems"] == 1000
        assert res1.json()["converted_coins"] == 2000
        assert res2.json()["converted_coins"] == 2000

        # Verify wallet balance in DB: must be strictly 1000 gems and 2000 coins (NOT double credited!)
        bal_res = await client.get("/api/v1/wallet/balance", headers=headers)
        bal = bal_res.json()
        assert bal["gems_balance"] == 1000
        assert bal["coins_balance"] == 2000

    app.dependency_overrides.clear()

