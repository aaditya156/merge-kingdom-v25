from sqlalchemy import Column, String, BigInteger, ForeignKey, DateTime, JSON
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class CurrencyTransaction(Base):
    __tablename__ = "currency_transactions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    wallet_id = Column(String(36), ForeignKey("wallets.id", ondelete="RESTRICT"), nullable=False, index=True)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    currency_type = Column(String(16), nullable=False)  # 'COIN', 'GEM'
    amount = Column(BigInteger, nullable=False)  # positive credit, negative debit
    balance_before = Column(BigInteger, nullable=False)
    balance_after = Column(BigInteger, nullable=False)
    transaction_type = Column(String(32), nullable=False)  # 'LEVEL_REWARD', 'CHEST_REWARD', 'IAP_GRANT', 'STORE_SPEND', 'MIGRATION_CONVERSION', 'ADMIN_ADJUSTMENT'
    reference_id = Column(String(128), nullable=True)  # level_id, product_id, or iap_transaction_id
    idempotency_key = Column(String(128), unique=True, nullable=True, index=True)
    metadata_info = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)

    wallet = relationship("Wallet", back_populates="transactions")
    player = relationship("PlayerProfile", back_populates="transactions")
