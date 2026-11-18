from sqlalchemy import Column, String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import TimestampMixin, utc_now


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    player_id = Column(String(64), primary_key=True, index=True)  # e.g. "p_8812"
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    nickname = Column(String(64), nullable=True)
    highest_level = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_active_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    user = relationship("User", back_populates="player_profile")
    devices = relationship("DeviceRegistration", back_populates="player", cascade="all, delete-orphan")
    saves = relationship("GameSave", back_populates="player", cascade="all, delete-orphan")
    wallet = relationship("Wallet", back_populates="player", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("CurrencyTransaction", back_populates="player", cascade="all, delete-orphan")
    purchases = relationship("PurchaseRecord", back_populates="player", cascade="all, delete-orphan")
    entitlements = relationship("Entitlement", back_populates="player", cascade="all, delete-orphan")
    migration_record = relationship("MigrationRecord", back_populates="player", uselist=False, cascade="all, delete-orphan")
    offline_operations = relationship("OfflineOperation", back_populates="player", cascade="all, delete-orphan")
