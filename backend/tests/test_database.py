import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from backend.app.models import (
    User,
    PlayerProfile,
    DeviceRegistration,
    GameSave,
    Wallet,
    CurrencyTransaction,
    PurchaseRecord,
    Entitlement,
    MigrationRecord,
    AuditLog,
)


@pytest.mark.asyncio
async def test_create_player_with_wallet_and_save(db_session):
    # 1. Create User & Player
    user = User(email="player1@chaosengine.test")
    db_session.add(user)
    await db_session.flush()

    player = PlayerProfile(player_id="p_8812", user_id=user.id, nickname="PuzzleMaster")
    db_session.add(player)
    await db_session.flush()

    # 2. Register Device
    device = DeviceRegistration(
        player_id=player.player_id,
        device_id="d_pixel_991",
        platform="Android",
        os_version="Android 14",
        app_version="2.5.0",
    )
    db_session.add(device)

    # 3. Create Initial Wallet
    wallet = Wallet(player_id=player.player_id, coins_balance=1000, gems_balance=50)
    db_session.add(wallet)
    await db_session.flush()

    # 4. Create Ledger Entry
    tx = CurrencyTransaction(
        wallet_id=wallet.id,
        player_id=player.player_id,
        currency_type="GEM",
        amount=50,
        balance_before=0,
        balance_after=50,
        transaction_type="IAP_GRANT",
        idempotency_key="tx_test_1001",
    )
    db_session.add(tx)

    # 5. Create Game Save
    save = GameSave(
        player_id=player.player_id,
        revision_id=1,
        level=10,
        inventory={"hammer": 2, "shuffle": 1},
        game_state={"board": [1, 2, 3]},
        state_hash="dummy_hash_abc",
        updated_by_device_id=device.device_id,
        client_saved_at=datetime.now(timezone.utc),
    )
    db_session.add(save)

    # 6. Create Entitlement
    entitlement = Entitlement(
        player_id=player.player_id,
        entitlement_key="no_ads",
        is_active=True,
        granted_by_source="IAP_PURCHASE",
    )
    db_session.add(entitlement)

    await db_session.commit()

    # Query back & verify
    query = await db_session.execute(
        select(PlayerProfile).where(PlayerProfile.player_id == "p_8812")
    )
    fetched_player = query.scalar_one()
    assert fetched_player.player_id == "p_8812"
    assert fetched_player.nickname == "PuzzleMaster"

    wallet_query = await db_session.execute(
        select(Wallet).where(Wallet.player_id == "p_8812")
    )
    fetched_wallet = wallet_query.scalar_one()
    assert fetched_wallet.coins_balance == 1000
    assert fetched_wallet.gems_balance == 50

    save_query = await db_session.execute(
        select(GameSave).where(GameSave.player_id == "p_8812")
    )
    fetched_save = save_query.scalar_one()
    assert fetched_save.revision_id == 1
    assert fetched_save.level == 10
    assert fetched_save.inventory["hammer"] == 2
