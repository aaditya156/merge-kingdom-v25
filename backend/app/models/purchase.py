from sqlalchemy import Column, String, BigInteger, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class PurchaseRecord(Base):
    __tablename__ = "purchase_records"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    store_platform = Column(String(32), nullable=False)  # 'GOOGLE_PLAY', 'APPLE_APP_STORE', 'LEGACY_MIGRATED'
    store_transaction_id = Column(String(255), unique=True, nullable=False, index=True)
    product_id = Column(String(128), nullable=False)
    purchase_type = Column(String(32), nullable=False)  # 'COIN_PACK', 'CURRENCY', 'ENTITLEMENT', 'HYBRID'
    coins_in_pack = Column(BigInteger, nullable=True)  # Fact 4: Server record of number of coins in the pack
    price_cents = Column(BigInteger, default=0, nullable=False)
    currency_code = Column(String(8), default="USD", nullable=False)
    verification_status = Column(String(32), default="VERIFIED", nullable=False)  # 'VERIFIED', 'FAILED', 'REFUNDED', 'LEGACY'
    raw_receipt = Column(JSON, nullable=True)
    purchased_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    verified_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    player = relationship("PlayerProfile", back_populates="purchases")
    entitlements = relationship("Entitlement", back_populates="purchase_record")
