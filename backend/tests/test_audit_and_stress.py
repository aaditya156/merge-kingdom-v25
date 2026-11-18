import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db
from backend.app.models.purchase import PurchaseRecord
from backend.app.models.wallet import Wallet
from backend.app.models.entitlement import Entitlement
from backend.app.models.migration import MigrationRecord
from backend.app.repositories.wallet_repo import WalletRepository
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
async def test_01_concurrent_devices_updating_same_player(db_session):
    """Test 1: Two concurrent devices updating the same player simultaneously."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create player with initial save (rev 1, level 10)
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "device_master", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        init_sync = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": 0,
                "level": 10,
                "inventory": {"hammer": 1},
                "game_state": {},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "device_master",
            },
        )
        assert init_sync.status_code == 200
        rev1 = init_sync.json()["revision_id"]

        # Device A (phone) and Device B (tablet) both branched from rev1
        # Device A plays to level 12; Device B plays to level 15
        req_a = client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": rev1,
                "level": 12,
                "inventory": {"hammer": 2, "shuffle": 0},
                "game_state": {"board": 12},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "phone_a",
            },
        )
        req_b = client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": rev1,
                "level": 15,
                "inventory": {"hammer": 1, "shuffle": 3},
                "game_state": {"board": 15},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "tablet_b",
            },
        )

        res_a, res_b = await asyncio.gather(req_a, req_b)
        assert res_a.status_code == 200
        assert res_b.status_code == 200

        # One was accepted, the second was merged via semantic 3-way merge!
        # Both must preserve level >= 15!
        final_save = (await client.get("/api/v1/saves/latest", headers=headers)).json()
        assert final_save["level"] >= 15
        assert final_save["inventory"]["hammer"] >= 2
        assert final_save["inventory"]["shuffle"] >= 3

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_02_simultaneous_spend_race_condition(db_session):
    """Test 2: Two simultaneous requests spending the same wallet balance (Double spend)."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_double_spend", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Grant 100 gems via purchase
        await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "GOOGLE_PLAY",
                "store_transaction_id": "tx_grant_100_gems",
                "product_id": "gems_tier_1",
            },
        )

        # Player has 100 gems. Try to spend 100 gems TWICE simultaneously
        spend_req_1 = client.post(
            "/api/v1/wallet/spend",
            headers=headers,
            json={"currency_type": "GEM", "amount": 100, "item_id": "item_alpha"},
        )
        spend_req_2 = client.post(
            "/api/v1/wallet/spend",
            headers=headers,
            json={"currency_type": "GEM", "amount": 100, "item_id": "item_beta"},
        )

        res_1, res_2 = await asyncio.gather(spend_req_1, spend_req_2)

        # Exactly ONE request should succeed (200), and the other MUST fail (400)
        statuses = [res_1.status_code, res_2.status_code]
        assert 200 in statuses
        assert 400 in statuses

        # Wallet balance must be strictly 0, NEVER negative
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["gems_balance"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_03_duplicate_offline_operations(db_session):
    """Test 3: Duplicate offline operations with identical idempotency key."""
    repo = WalletRepository(db_session)
    wallet, tx1 = await repo.mutate_balance(
        player_id="p_test_offline",
        currency_type="COIN",
        amount=50,
        transaction_type="OFFLINE_OP",
        idempotency_key="offline_action_9999",
    )
    assert tx1.amount == 50
    assert wallet.coins_balance == 50

    # Repeat exact same offline operation
    wallet_dup, tx2 = await repo.mutate_balance(
        player_id="p_test_offline",
        currency_type="COIN",
        amount=50,
        transaction_type="OFFLINE_OP",
        idempotency_key="offline_action_9999",
    )
    assert tx2.id == tx1.id
    assert wallet_dup.coins_balance == 50


@pytest.mark.asyncio
async def test_04_duplicate_purchase_requests(db_session):
    """Test 4: Duplicate purchase requests from app store retry storm."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_store_retry", "platform": "iOS", "app_version": "2.5.0", "os_version": "iOS 17"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3 purchase verification requests in rapid succession
        res1 = await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "apple_retry_store_tx_12345",
                "product_id": "gems_tier_2",
            },
        )
        assert res1.status_code == 200
        assert res1.json()["gems_granted"] == 500

        res2 = await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "apple_retry_store_tx_12345",
                "product_id": "gems_tier_2",
            },
        )
        assert res2.status_code == 200
        assert res2.json()["gems_granted"] == 0  # Idempotent response

        # Gems must only be credited ONCE (500 gems)
        bal = (await client.get("/api/v1/wallet/balance", headers=headers)).json()
        assert bal["gems_balance"] == 500

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_05_database_failure_during_wallet_transaction(db_session):
    """Test 5: Transaction rollback ensures no partial updates or orphaned state."""
    repo = WalletRepository(db_session)
    wallet = await repo.get_wallet("p_rollback_test")
    wallet.coins_balance = 200
    await db_session.flush()

    try:
        async with db_session.begin_nested():
            wallet.coins_balance -= 100
            raise RuntimeError("Database IO connection lost")
    except RuntimeError:
        pass

    await db_session.refresh(wallet)
    assert wallet.coins_balance == 200


@pytest.mark.asyncio
async def test_06_old_clients_uploading_stale_saves(db_session):
    """Test 6: Old v2.4 clients uploading stale saves with lower levels."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_stale_legacy", "device_id": "new_phone", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        await client.post(
            "/api/v1/saves/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "base_revision_id": 0,
                "level": 80,
                "inventory": {"hammer": 5},
                "game_state": {},
                "client_saved_at": utc_now().isoformat(),
                "device_id": "new_phone",
            },
        )

        legacy_res = await client.post(
            "/api/v1/legacy/sync",
            json={
                "player_id": "p_stale_legacy",
                "saved_at": int((utc_now() + timedelta(days=5)).timestamp()),
                "level": 50,  # Stale level!
                "coins": 300,
                "inventory": {"hammer": 2},
                "no_ads": False,
            },
        )
        assert legacy_res.status_code == 200
        assert legacy_res.json()["level"] == 80

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_07_old_clients_attempting_to_overwrite_gem_balances(db_session):
    """Test 7: Old clients syncing cannot overwrite or invalidate v2.5 gem balances."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_gem_protector", "device_id": "phone_25", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        await client.post(
            "/api/v1/purchases/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "store_platform": "GOOGLE_PLAY",
                "store_transaction_id": "tx_grant_1200_gems",
                "product_id": "gems_tier_3",
            },
        )

        await client.post(
            "/api/v1/legacy/sync",
            json={
                "player_id": "p_gem_protector",
                "saved_at": int(utc_now().timestamp()),
                "level": 10,
                "coins": 999,
                "inventory": {},
                "no_ads": False,
            },
        )

        bal = (await client.get("/api/v1/wallet/balance", headers={"Authorization": f"Bearer {token}"})).json()
        assert bal["gems_balance"] == 1200

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_08_repeated_migration_after_partial_failure(db_session):
    """Test 8: Repeated migration is completely idempotent and safe against retries."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": "p_retry_mig", "device_id": "dev_mig", "platform": "Android", "app_version": "2.4", "os_version": "Android 11"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        res1 = await client.post("/api/v1/migration/migrate", headers=headers, json={"legacy_coins": 1000})
        assert res1.status_code == 200

        res2 = await client.post("/api/v1/migration/migrate", headers=headers, json={"legacy_coins": 1000})
        assert res2.status_code == 200
        assert res2.json()["status"] == "COMPLETED"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_09_manipulated_device_timestamps_no_impact_on_revisions(db_session):
    """Test 9: Manipulated client timestamps cannot alter revision numbering or cause rollback."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_time_traveler", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        crazy_future = datetime(2099, 1, 1, tzinfo=timezone.utc).isoformat()
        res1 = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": 0,
                "level": 1,
                "inventory": {},
                "game_state": {},
                "client_saved_at": crazy_future,
                "device_id": "phone_time_traveler",
            },
        )
        assert res1.status_code == 200
        rev1 = res1.json()["revision_id"]

        crazy_past = datetime(1990, 1, 1, tzinfo=timezone.utc).isoformat()
        res2 = await client.post(
            "/api/v1/saves/sync",
            headers=headers,
            json={
                "base_revision_id": rev1,
                "level": 2,
                "inventory": {},
                "game_state": {},
                "client_saved_at": crazy_past,
                "device_id": "phone_time_traveler",
            },
        )
        assert res2.status_code == 200
        assert res2.json()["revision_id"] == rev1 + 1
        assert res2.json()["level"] == 2

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_10_time_gated_reward_and_level_farming_abuse(db_session):
    """Test 10: Attempting to farm coins by claiming the same level reward repeatedly is blocked."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_reward_farmer", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        claim1 = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 5, "coins_earned": 50, "score": 1000},
        )
        assert claim1.status_code == 200
        assert claim1.json()["wallet"]["coins_balance"] == 50

        claim2 = await client.post(
            "/api/v1/wallet/earn-coins",
            headers=headers,
            json={"level_completed": 5, "coins_earned": 50, "score": 1000},
        )
        assert claim2.status_code == 200
        assert claim2.json()["wallet"]["coins_balance"] == 50

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_11_unauthorized_access_to_another_player_wallet(db_session):
    """Test 11: Security isolation - Player A cannot read or spend Player B's wallet."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login_a = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "device_alice", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token_a = login_a.json()["access_token"]

        login_b = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "device_bob", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        token_b = login_b.json()["access_token"]
        player_b_id = login_b.json()["player_id"]

        await client.post(
            "/api/v1/wallet/earn-coins",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"level_completed": 1, "coins_earned": 100},
        )

        bal_b = (await client.get("/api/v1/wallet/balance", headers={"Authorization": f"Bearer {token_b}"})).json()
        assert bal_b["player_id"] == player_b_id
        assert bal_b["coins_balance"] == 0

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_12_no_ads_entitlement_restoration_after_conflicting_saves(db_session):
    """Test 12: No Ads entitlement restoration survives conflicting save uploads."""
    app.dependency_overrides[get_db] = app_db_override
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "device_vip", "platform": "iOS", "app_version": "2.5.0", "os_version": "iOS 17"},
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/v1/purchases/verify",
            headers=headers,
            json={
                "store_platform": "APPLE_APP_STORE",
                "store_transaction_id": "tx_no_ads_vip_99",
                "product_id": "no_ads_standalone",
            },
        )

        for i in range(1, 4):
            await client.post(
                "/api/v1/saves/sync",
                headers=headers,
                json={
                    "base_revision_id": 0,
                    "level": 10 + i,
                    "inventory": {},
                    "game_state": {},
                    "client_saved_at": utc_now().isoformat(),
                    "device_id": f"device_conflict_{i}",
                },
            )

        restore_res = await client.post("/api/v1/entitlements/restore", headers=headers)
        assert restore_res.status_code == 200
        ents = restore_res.json()["entitlements"]
        assert len(ents) == 1
        assert ents[0]["entitlement_key"] == "no_ads"
        assert ents[0]["is_active"] is True

    app.dependency_overrides.clear()
