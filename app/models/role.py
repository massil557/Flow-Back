from sqlalchemy import Column, Integer, String
from app.database import Base

class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String(20), unique=True, nullable=False)