from sqlalchemy import Column, String, Text, DateTime
from app.database import Base
import datetime


class AppSetting(Base):
    __tablename__ = "app_settings"

    key        = Column(String(100), primary_key=True)
    value      = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
