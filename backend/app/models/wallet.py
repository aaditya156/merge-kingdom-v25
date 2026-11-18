from sqlalchemy import Column, String, BigInteger, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    coins_balance = Column(BigInteger, default=0, nullable=False)
    gems_balance = Column(BigInteger, default=0, nullable=False)
    lock_version = Column(BigInteger, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)

    player = relationship("PlayerProfile", back_populates="wallet")
    transactions = relationship("CurrencyTransaction", back_populates="wallet", cascade="all, delete-orphan")
