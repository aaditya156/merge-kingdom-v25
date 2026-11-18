import secrets
from typing import Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.security import create_access_token
from backend.app.core.config import settings
from backend.app.repositories.player_repo import PlayerRepository
from backend.app.schemas.auth import DeviceLoginRequest, TokenResponse
from backend.app.models.migration import MigrationRecord
from backend.app.models.save import GameSave
from sqlalchemy import select


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.player_repo = PlayerRepository(session)

    async def device_login(self, request: DeviceLoginRequest) -> TokenResponse:
        is_new = False
        player_id = request.player_id

        if not player_id:
            player_id = f"p_{secrets.token_hex(4)}"
            player = await self.player_repo.create_player(player_id=player_id)
            is_new = True
        else:
            player = await self.player_repo.get_by_id(player_id)
            if not player:
                player = await self.player_repo.create_player(player_id=player_id)
                is_new = True

        # Register/update device
        await self.player_repo.register_device(
            player_id=player_id,
            device_id=request.device_id,
            platform=request.platform,
            os_version=request.os_version,
            app_version=request.app_version,
        )

        # Check if migration is required:
        # If player has legacy save data or legacy purchases, but no completed migration record
        migration_required = False
        if not is_new:
            mig_query = await self.session.execute(
                select(MigrationRecord).where(
                    MigrationRecord.player_id == player_id,
                    MigrationRecord.status == "COMPLETED"
                )
            )
            mig_record = mig_query.scalar_one_or_none()
            if not mig_record:
                # Check if they have an existing save
                save_query = await self.session.execute(
                    select(GameSave).where(GameSave.player_id == player_id)
                )
                if save_query.first():
                    migration_required = True

        access_token = create_access_token(subject=player_id)

        return TokenResponse(
            access_token=access_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            player_id=player_id,
            is_new_player=is_new,
            migration_required=migration_required,
        )
