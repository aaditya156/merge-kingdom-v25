from sqlalchemy import Column, String, Boolean, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class DeviceRegistration(Base):
    __tablename__ = "device_registrations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(128), nullable=False)
    platform = Column(String(32), nullable=False)  # iOS, Android
    os_version = Column(String(64), nullable=False)  # "Android 7.0", "iOS 17.4"
    app_version = Column(String(32), nullable=False)  # "2.4", "2.5"
    last_seen_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    player = relationship("PlayerProfile", back_populates="devices")

    __table_args__ = (
        UniqueConstraint("player_id", "device_id", name="uq_player_device"),
    )
