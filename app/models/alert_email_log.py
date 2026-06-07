from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from app.database import Base
import datetime


class AlertEmailLog(Base):
    __tablename__ = "alert_email_log"

    id            = Column(Integer, primary_key=True, index=True)
    rule_id       = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True, index=True)
    config_id     = Column(Integer, ForeignKey("alert_configs.id", ondelete="SET NULL"), nullable=True, index=True)
    sensor_code   = Column(String(50), nullable=False)
    level         = Column(String(10), nullable=False)
    recipient     = Column(String(255), nullable=False)
    success       = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    attempt_count = Column(Integer, default=0)
    last_sent_at  = Column(DateTime, default=datetime.datetime.utcnow)
