from sqlalchemy import Column, String, Integer, Boolean, ForeignKey, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class GameSave(Base):
    __tablename__ = "game_saves"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    player_id = Column(String(64), ForeignKey("player_profiles.player_id", ondelete="CASCADE"), nullable=False, index=True)
    revision_id = Column(Integer, default=1, nullable=False)
    level = Column(Integer, nullable=False, default=1)
    inventory = Column(JSON, nullable=False, default=lambda: {"hammer": 0, "shuffle": 0})
    game_state = Column(JSON, nullable=False, default=dict)
    state_hash = Column(String(64), nullable=False)
    updated_by_device_id = Column(String(128), nullable=False)
    client_saved_at = Column(DateTime(timezone=True), nullable=False)
    server_saved_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    is_latest = Column(Boolean, default=True, nullable=False, index=True)

    player = relationship("PlayerProfile", back_populates="saves")

    __table_args__ = (
        UniqueConstraint("player_id", "revision_id", name="uq_player_revision"),
    )
