from sqlalchemy import Column, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from backend.app.core.database import Base
from backend.app.models.base import TimestampMixin, generate_uuid, utc_now


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    status = Column(String(32), default="ACTIVE", nullable=False)  # ACTIVE, SUSPENDED, BANNED

    player_profile = relationship("PlayerProfile", back_populates="user", uselist=False)
