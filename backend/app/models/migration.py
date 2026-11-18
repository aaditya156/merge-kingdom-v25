from sqlalchemy import Column, String, BigInteger, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class MigrationRecord(Base):
    __tablename__ = "migration_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    source_version = Column(String(16), default="2.4", nullable=False)
    target_version = Column(String(16), default="2.5", nullable=False)
    original_coins = Column(BigInteger, nullable=False)
    lifetime_purchased_coins = Column(BigInteger, default=0, nullable=False)
    converted_coins = Column(BigInteger, nullable=False)
    converted_gems = Column(BigInteger, nullable=False)
    policy_applied = Column(String(64), default="PURCHASED_FIRST_PROTECTION", nullable=False)
    original_save_snapshot = Column(JSON, nullable=False)
    status = Column(String(32), default="COMPLETED", nullable=False)  # 'PENDING', 'COMPLETED', 'FAILED', 'ROLLED_BACK'
    migrated_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    player = relationship("PlayerProfile", back_populates="migration_record")
