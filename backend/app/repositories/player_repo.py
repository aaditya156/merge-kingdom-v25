from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from backend.app.models.player import PlayerProfile
from backend.app.models.device import DeviceRegistration
from backend.app.models.wallet import Wallet
from backend.app.models.base import utc_now


class PlayerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, player_id: str, load_devices: bool = False) -> Optional[PlayerProfile]:
        query = select(PlayerProfile).where(PlayerProfile.player_id == player_id)
        if load_devices:
            query = query.options(selectinload(PlayerProfile.devices))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def create_player(self, player_id: str, nickname: Optional[str] = None) -> PlayerProfile:
        player = PlayerProfile(
            player_id=player_id,
            nickname=nickname or f"Player_{player_id[-4:]}",
            highest_level=1,
        )
        self.session.add(player)
        
        # Also initialize an empty wallet
        wallet = Wallet(player_id=player_id, coins_balance=0, gems_balance=0)
        self.session.add(wallet)
        
        await self.session.flush()
        return player

    async def register_device(
        self,
        player_id: str,
        device_id: str,
        platform: str,
        os_version: str,
        app_version: str,
    ) -> DeviceRegistration:
        query = select(DeviceRegistration).where(
            DeviceRegistration.player_id == player_id,
            DeviceRegistration.device_id == device_id,
        )
        result = await self.session.execute(query)
        device = result.scalar_one_or_none()

        if device:
            device.last_seen_at = utc_now()
            device.platform = platform
            device.os_version = os_version
            device.app_version = app_version
            device.is_active = True
        else:
            device = DeviceRegistration(
                player_id=player_id,
                device_id=device_id,
                platform=platform,
                os_version=os_version,
                app_version=app_version,
            )
            self.session.add(device)

        await self.session.flush()
        return device

    async def update_last_active(self, player_id: str):
        player = await self.get_by_id(player_id)
        if player:
            player.last_active_at = utc_now()
            await self.session.flush()
