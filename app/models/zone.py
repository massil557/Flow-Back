from sqlalchemy import Column, Integer, String, Float
from app.database import Base

class Zone(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True, index=True)
    nom_zone = Column(String(100), nullable=False)
    code_zone = Column(String(20), unique=True, nullable=False)
    type = Column(String(50), default="Process")
    x = Column(Float, default=100)
    y = Column(Float, default=100)
    w = Column(Float, default=120)
    h = Column(Float, default=100)