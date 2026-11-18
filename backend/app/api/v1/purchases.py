from typing import Annotated
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.database import get_db
from backend.app.api.deps import get_current_player_id
from backend.app.schemas.purchase import VerifyPurchaseRequest, VerifyPurchaseResponse
from backend.app.services.purchase_service import PurchaseService

router = APIRouter(prefix="/purchases", tags=["In-App Purchases"])


@router.post("/verify", response_model=VerifyPurchaseResponse, status_code=status.HTTP_200_OK)
async def verify_purchase(
    request: VerifyPurchaseRequest,
    player_id: Annotated[str, Depends(get_current_player_id)],
    session: Annotated[AsyncSession, Depends(get_db)],
):
    service = PurchaseService(session)
    return await service.verify_purchase(player_id, request)
