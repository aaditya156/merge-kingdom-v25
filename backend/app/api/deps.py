from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.core.security import decode_access_token
from backend.app.repositories.player_repo import PlayerRepository
from backend.app.models.player import PlayerProfile

security_scheme = HTTPBearer(auto_error=False)


async def get_current_player_id(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
) -> str:
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    payload = decode_access_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return str(payload["sub"])


async def get_current_player(
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PlayerProfile:
    repo = PlayerRepository(session)
    player = await repo.get_by_id(player_id, load_devices=True)
    if not player:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Player profile not found",
        )
    return player


def verify_player_authorization(target_player_id: str, authenticated_player_id: str):
    """Enforces that a player cannot read or modify another player's data."""
    if target_player_id != authenticated_player_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: You cannot access or modify another player's data.",
        )
