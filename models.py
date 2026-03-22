from sqlalchemy import Boolean, Column, Integer, String, Float, ForeignKey, DateTime, Text, text
from database import Base, engine
import datetime

# 1. Table des Rôles
class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String(20), unique=True, nullable=False)

# 2. Table des Utilisateurs  ← email column added
class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    email         = Column(String(100), unique=True, nullable=True)   # NEW
    role_id       = Column(Integer, ForeignKey("roles.id"))

# 3. Table des Zones
class Zone(Base):
    __tablename__ = "zones"
    id        = Column(Integer, primary_key=True, index=True)
    nom_zone  = Column(String(100), nullable=False)
    code_zone = Column(String(20), unique=True, nullable=False)

# 4. Table des Capteurs
class Capteur(Base):
    __tablename__ = "capteurs"
    id             = Column(Integer, primary_key=True, index=True)
    code_unique    = Column(String(20), unique=True, nullable=False)
    type_grandeur  = Column(String(50))
    unite          = Column(String(10))
    adresse_ip     = Column(String(15))
    zone_id        = Column(Integer, ForeignKey("zones.id"))
    is_activated   = Column(Boolean, default=True, nullable=False)

# 5. Table des Mesures (Hypertable)
class Mesure(Base):
    __tablename__ = "mesures"
    time       = Column(DateTime(timezone=True), primary_key=True, default=datetime.datetime.utcnow)
    capteur_id = Column(Integer, ForeignKey("capteurs.id"), primary_key=True)
    valeur     = Column(Float, nullable=False)

# 6. Table des Alertes
class Alerte(Base):
    __tablename__ = "alertes"
    id             = Column(Integer, primary_key=True, index=True)
    time           = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    capteur_code   = Column(String(50))
    valeur         = Column(Float, nullable=False)
    seuil_depasse  = Column(Float, nullable=False)
    message        = Column(Text)
    is_resolved    = Column(Boolean, default=False)

# --- DB INIT ---
def init_db():
    print("Création des tables dans PostgreSQL...")
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT create_hypertable('mesures', 'time', if_not_exists => TRUE);"))
            conn.commit()
            print("✅ Tables créées. 'mesures' est une Hypertable TimescaleDB.")
        except Exception as e:
            print(f"Note: {e}")

if __name__ == "__main__":
    init_db()
