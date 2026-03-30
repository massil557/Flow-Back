from sqlalchemy import Column, Integer, String, Text, ForeignKey
from app.database import Base

class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    email = Column(String(100), unique=True, nullable=True)
    role_id = Column(Integer, ForeignKey("roles.id"))