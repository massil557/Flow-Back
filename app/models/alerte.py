from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text
from app.database import Base
import datetime

class Alerte(Base):
    __tablename__ = "alertes"
    id = Column(Integer, primary_key=True, index=True)
    time = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    capteur_code = Column(String(50))
    valeur = Column(Float, nullable=False)
    seuil_depasse = Column(Float, nullable=False)
    message = Column(Text)
    is_resolved = Column(Boolean, default=False)