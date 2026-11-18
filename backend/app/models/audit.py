from sqlalchemy import Column, String, DateTime, JSON
from backend.app.core.database import Base
from backend.app.models.base import generate_uuid, utc_now


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    actor_type = Column(String(32), nullable=False)  # 'SYSTEM', 'ADMIN', 'CLIENT'
    actor_id = Column(String(128), nullable=False)
    action = Column(String(64), nullable=False)
    target_entity = Column(String(64), nullable=False, index=True)
    target_id = Column(String(128), nullable=False, index=True)
    changes = Column(JSON, default=dict, nullable=False)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
