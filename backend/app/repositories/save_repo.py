import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.save import GameSave
from backend.app.models.player import PlayerProfile
from backend.app.models.base import utc_now


class SaveRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest_save(self, player_id: str) -> Optional[GameSave]:
        query = (
            select(GameSave)
            .where(GameSave.player_id == player_id, GameSave.is_latest == True)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_revision(self, player_id: str, revision_id: int) -> Optional[GameSave]:
        query = select(GameSave).where(
            GameSave.player_id == player_id,
            GameSave.revision_id == revision_id,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    def compute_hash(self, level: int, inventory: dict, game_state: dict) -> str:
        serialized = json.dumps(
            {"level": level, "inventory": inventory, "game_state": game_state},
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    async def create_or_update_save(
        self,
        player_id: str,
        revision_id: int,
        level: int,
        inventory: dict,
        game_state: dict,
        device_id: str,
        client_saved_at: datetime,
    ) -> GameSave:
        # 1. Demote any current latest save
        await self.session.execute(
            update(GameSave)
            .where(GameSave.player_id == player_id, GameSave.is_latest == True)
            .values(is_latest=False)
        )

        state_hash = self.compute_hash(level, inventory, game_state)

        # 2. Insert new latest save
        new_save = GameSave(
            player_id=player_id,
            revision_id=revision_id,
            level=level,
            inventory=inventory,
            game_state=game_state,
            state_hash=state_hash,
            updated_by_device_id=device_id,
            client_saved_at=client_saved_at,
            server_saved_at=utc_now(),
            is_latest=True,
        )
        self.session.add(new_save)

        # 3. Update player highest_level if increased
        player_query = await self.session.execute(
            select(PlayerProfile).where(PlayerProfile.player_id == player_id)
        )
        player = player_query.scalar_one_or_none()
        if player and level > player.highest_level:
            player.highest_level = level

        await self.session.flush()
        return new_save
