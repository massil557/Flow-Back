from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey
from app.database import Base

class Capteur(Base):
    __tablename__ = "capteurs"
    id = Column(Integer, primary_key=True, index=True)
    code_unique = Column(String(20), unique=True, nullable=False)
    type_grandeur = Column(String(50))
    unite = Column(String(10))
    adresse_ip = Column(String(15))
    zone_id = Column(Integer, ForeignKey("zones.id"))
    is_activated = Column(Boolean, default=True, nullable=False)