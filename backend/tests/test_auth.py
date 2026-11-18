import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.database import get_db


@pytest.mark.asyncio
async def test_device_login_and_player_profile(db_session):
    # Override get_db to use test db_session
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Anonymous Device Login
        login_res = await client.post(
            "/api/v1/auth/device-login",
            json={
                "device_id": "phone_12345",
                "platform": "Android",
                "os_version": "Android 14",
                "app_version": "2.5.0",
            },
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert "access_token" in data
        assert data["is_new_player"] is True
        player_id = data["player_id"]
        token = data["access_token"]

        # 2. Access Protected /players/me with token
        headers = {"Authorization": f"Bearer {token}"}
        profile_res = await client.get("/api/v1/players/me", headers=headers)
        assert profile_res.status_code == 200
        profile = profile_res.json()
        assert profile["player_id"] == player_id
        assert len(profile["devices"]) == 1
        assert profile["devices"][0]["device_id"] == "phone_12345"

        # 3. Access Protected /players/me without token -> 401
        unauth_res = await client.get("/api/v1/players/me")
        assert unauth_res.status_code == 401

        # 4. Access Protected /players/me with invalid token -> 401
        invalid_res = await client.get("/api/v1/players/me", headers={"Authorization": "Bearer badtoken123"})
        assert invalid_res.status_code == 401

        # 5. Device login from a second device for same player
        second_device_res = await client.post(
            "/api/v1/auth/device-login",
            json={
                "player_id": player_id,
                "device_id": "tablet_99999",
                "platform": "iOS",
                "os_version": "iOS 17.4",
                "app_version": "2.5.0",
            },
        )
        assert second_device_res.status_code == 200
        second_data = second_device_res.json()
        assert second_data["player_id"] == player_id
        assert second_data["is_new_player"] is False

        # Verify profile now reflects 2 registered devices
        profile_res2 = await client.get("/api/v1/players/me", headers={"Authorization": f"Bearer {second_data['access_token']}"})
        assert profile_res2.status_code == 200
        profile2 = profile_res2.json()
        assert len(profile2["devices"]) == 2

    app.dependency_overrides.clear()
