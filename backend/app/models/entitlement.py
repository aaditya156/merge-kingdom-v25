from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class Entitlement(Base):
    __tablename__ = "entitlements"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    entitlement_key = Column(String(64), nullable=False)  # 'no_ads', 'vip_season_1'
    is_active = Column(Boolean, default=True, nullable=False)
    granted_by_source = Column(String(64), nullable=False)  # 'IAP_PURCHASE', 'LEGACY_SAVE_RESTORE', 'ADMIN_SUPPORT'
    purchase_record_id = Column(String(36), ForeignKey("purchase_records.id", ondelete="SET NULL"), nullable=True)
    granted_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # None for permanent

    player = relationship("PlayerProfile", back_populates="entitlements")
    purchase_record = relationship("PurchaseRecord", back_populates="entitlements")

    __table_args__ = (
        UniqueConstraint("player_id", "entitlement_key", name="uq_player_entitlement"),
    )
