from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from app.database import Base
import datetime

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id              = Column(Integer, primary_key=True, index=True)
    sensor_id       = Column(Integer, ForeignKey("capteurs.id"), nullable=False)
    condition       = Column(String(10), nullable=False)
    threshold       = Column(Float, nullable=False)
    severity        = Column(String(10), nullable=False)
    cooldown_seconds = Column(Integer, default=0)
    active          = Column(Boolean, default=True)
    created_at      = Column(DateTime, default=datetime.datetime.utcnow)
