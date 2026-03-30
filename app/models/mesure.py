from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey
from app.database import Base
import datetime

class Mesure(Base):
    __tablename__ = "mesures"
    time = Column(DateTime(timezone=True), primary_key=True, default=datetime.datetime.utcnow)
    capteur_id = Column(Integer, ForeignKey("capteurs.id"), primary_key=True)
    valeur = Column(Float, nullable=False)