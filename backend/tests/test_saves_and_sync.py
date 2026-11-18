import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db


@pytest.mark.asyncio
async def test_support_incident_1_airplane_mode_conflict(db_session):
    """Incident 1: Tablet reaches level 160. Phone in airplane mode reaches level 151.

    When phone reconnects, level 160 MUST NOT be lost.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login on Tablet
        tab_login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "tablet_mom", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 13"},
        )
        player_id = tab_login.json()["player_id"]
        token_tablet = tab_login.json()["access_token"]

        # 2. Tablet plays to level 160
        sync_1 = await client.post(
            "/api/v1/saves/sync",
            headers={"Authorization": f"Bearer {token_tablet}"},
            json={
                "base_revision_id": 0,
                "level": 160,
                "inventory": {"hammer": 3, "shuffle": 1},
                "game_state": {"zone": 5},
                "client_saved_at": datetime.now(timezone.utc).isoformat(),
                "device_id": "tablet_mom",
            },
        )
        assert sync_1.status_code == 200
        assert sync_1.json()["level"] == 160
        rev_after_tablet = sync_1.json()["revision_id"]

        # 3. Son's phone was offline (started at base_revision_id=0, reached level 151)
        phone_login = await client.post(
            "/api/v1/auth/device-login",
            json={"player_id": player_id, "device_id": "phone_son", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 10"},
        )
        token_phone = phone_login.json()["access_token"]

        # 4. Phone comes online and flushes upload queue with level 151
        sync_2 = await client.post(
            "/api/v1/saves/sync",
            headers={"Authorization": f"Bearer {token_phone}"},
            json={
                "base_revision_id": 0,  # Stale revision!
                "level": 151,
                "inventory": {"hammer": 2, "shuffle": 1},
                "game_state": {"zone": 4},
                "client_saved_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),  # Even with later timestamp!
                "device_id": "phone_son",
            },
        )
        assert sync_2.status_code == 200
        data_2 = sync_2.json()
        assert data_2["status"] == "MERGED"
        # Progress MUST be preserved at level 160!
        assert data_2["level"] == 160
        assert data_2["revision_id"] > rev_after_tablet

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_support_incident_2_device_clock_manipulation(db_session):
    """Incident 2: Date changed to tomorrow, played 1 level.

    Date changed back to today, played offline. Valid progress must NOT be lost.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_clock_hacker", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 12"},
        )
        token = login.json()["access_token"]

        # 1. Player sets clock to tomorrow
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        res_future = await client.post(
            "/api/v1/saves/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "base_revision_id": 0,
                "level": 50,
                "inventory": {"hammer": 1},
                "game_state": {},
                "client_saved_at": tomorrow.isoformat(),
                "device_id": "phone_clock_hacker",
            },
        )
        assert res_future.status_code == 200
        rev_future = res_future.json()["revision_id"]

        # 2. Player changes date back to today (real time) and beats 5 levels offline
        real_time_now = datetime.now(timezone.utc)  # timestamp is in the past relative to tomorrow!
        res_current = await client.post(
            "/api/v1/saves/sync",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "base_revision_id": rev_future,
                "level": 55,
                "inventory": {"hammer": 2},
                "game_state": {},
                "client_saved_at": real_time_now.isoformat(),
                "device_id": "phone_clock_hacker",
            },
        )
        assert res_current.status_code == 200
        # In v2.5, server uses revision_id, so the save is accepted and not reverted!
        assert res_current.json()["level"] == 55
        assert res_current.json()["revision_id"] == rev_future + 1

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_support_incident_3_no_ads_preservation(db_session):
    """Incident 3: Paid for No Ads on phone. Old tablet uploads stale save without No Ads.

    No Ads entitlement must NEVER be stripped.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login on phone and buy No Ads bundle
        login = await client.post(
            "/api/v1/auth/device-login",
            json={"device_id": "phone_user", "platform": "Android", "app_version": "2.5.0", "os_version": "Android 14"},
        )
        player_id = login.json()["player_id"]
        token = login.json()["access_token"]

        purchase_res = await client.post(
            "/api/v1/purchases/verify",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "store_platform": "GOOGLE_PLAY",
                "store_transaction_id": "GPA.331-442-551",
                "product_id": "no_ads_bundle",
            },
        )
        assert purchase_res.status_code == 200
        assert "no_ads" in purchase_res.json()["entitlements_granted"]

        # 2. Old tablet using legacy v2.4 sync with no_ads: false
        legacy_res = await client.post(
            "/api/v1/legacy/sync",
            json={
                "player_id": player_id,
                "saved_at": int(datetime.now(timezone.utc).timestamp()),
                "level": 40,
                "coins": 500,
                "inventory": {"hammer": 1, "shuffle": 1},
                "no_ads": False,  # Old tablet thinks no_ads is false!
            },
        )
        assert legacy_res.status_code == 200
        # Server MUST return no_ads: true to old tablet and protect the entitlement
        assert legacy_res.json()["no_ads"] is True

        # 3. Verify server entitlement table remains active
        ent_res = await client.get("/api/v1/entitlements", headers={"Authorization": f"Bearer {token}"})
        assert ent_res.status_code == 200
        ents = ent_res.json()["entitlements"]
        assert len(ents) == 1
        assert ents[0]["entitlement_key"] == "no_ads"
        assert ents[0]["is_active"] is True

    app.dependency_overrides.clear()
