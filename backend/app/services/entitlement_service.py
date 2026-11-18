from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.entitlement import Entitlement
from backend.app.schemas.entitlement import EntitlementResponse, PlayerEntitlementsResponse


class EntitlementService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_player_entitlements(self, player_id: str) -> PlayerEntitlementsResponse:
        query = select(Entitlement).where(
            Entitlement.player_id == player_id,
            Entitlement.is_active == True,
        )
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return PlayerEntitlementsResponse(
            player_id=player_id,
            entitlements=[EntitlementResponse.model_validate(e) for e in items],
        )

    async def restore_entitlements(self, player_id: str) -> PlayerEntitlementsResponse:
        # In a real store environment, this would query Apple/Google purchase history
        # Here it ensures all active entitlements linked to this player are returned
        return await self.get_player_entitlements(player_id)
