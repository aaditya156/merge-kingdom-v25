from typing import Annotated
from fastapi import APIRouter, Depends, status
from backend.app.api.deps import get_current_player
from backend.app.schemas.player import PlayerProfileResponse
from backend.app.models.player import PlayerProfile

router = APIRouter(prefix="/players", tags=["Players"])


@router.get("/me", response_model=PlayerProfileResponse, status_code=status.HTTP_200_OK)
async def get_my_profile(
    current_player: Annotated[PlayerProfile, Depends(get_current_player)],
):
    return current_player
