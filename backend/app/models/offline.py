from sqlalchemy import Column, String, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class OfflineOperation(Base):
    __tablename__ = "offline_operations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(128), nullable=False)
    operation_type = Column(String(64), nullable=False)  # 'LEVEL_COMPLETE', 'ITEM_USE', 'CHEST_OPEN'
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), default="PENDING", nullable=False)  # 'PENDING', 'APPLIED', 'REJECTED'
    client_timestamp = Column(DateTime(timezone=True), nullable=False)
    processed_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    player = relationship("PlayerProfile", back_populates="offline_operations")
