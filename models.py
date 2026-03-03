from sqlalchemy import Boolean, Column, Integer, String, Float, ForeignKey, DateTime, Text, text
from database import Base, engine
import datetime

# 1. Table des Rôles
class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True, index=True)
    nom = Column(String(20), unique=True, nullable=False)

# 2. Table des Utilisateurs
class Utilisateur(Base):
    __tablename__ = "utilisateurs"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"))

# 3. Table des Zones
class Zone(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True, index=True)
    nom_zone = Column(String(100), nullable=False)
    code_zone = Column(String(20), unique=True, nullable=False)

# 4. Table des Capteurs (avec IP)
class Capteur(Base):
    __tablename__ = "capteurs"
    id = Column(Integer, primary_key=True, index=True)
    code_unique = Column(String(20), unique=True, nullable=False)
    type_grandeur = Column(String(50)) # Température, Pression, etc.
    unite = Column(String(10))        # °C, Bar, etc.
    adresse_ip = Column(String(15))   # Ton attribut IP
    zone_id = Column(Integer, ForeignKey("zones.id"))
    is_activated = Column(Boolean, default=True, nullable=False)

# 5. Table des Mesures (Hypertable)
class Mesure(Base):
    __tablename__ = "mesures"
    # Pour TimescaleDB, time doit être une clé primaire ou faire partie d'une clé composée
    time = Column(DateTime(timezone=True), primary_key=True, default=datetime.datetime.utcnow)
    capteur_id = Column(Integer, ForeignKey("capteurs.id"), primary_key=True)
    valeur = Column(Float, nullable=False)

    # 6. Table des Alertes
class Alerte(Base):
    __tablename__ = "alertes"
    id = Column(Integer, primary_key=True, index=True)
    time = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    capteur_code = Column(String(50)) # Vérifie que c'est bien capteur_code et non code_unique
    valeur = Column(Float, nullable=False)
    seuil_depasse = Column(Float, nullable=False)
    message = Column(Text)
    is_resolved = Column(Boolean, default=False)

# --- FONCTION DE CRÉATION AUTOMATIQUE ---
def init_db():
    print("Création des tables dans PostgreSQL...")
    # Crée les tables classiques
    Base.metadata.create_all(bind=engine)
    
    # Transformation en Hypertable (Spécifique TimescaleDB)
    with engine.connect() as conn:
        try:
            # On utilise text() pour que SQLAlchemy accepte la commande SQL brute
            conn.execute(text("SELECT create_hypertable('mesures', 'time', if_not_exists => TRUE);"))
            conn.commit()
            print(" Toutes les tables ont été créées avec succès !")
            print(" La table 'mesures' est maintenant une Hypertable TimescaleDB.")
        except Exception as e:
            print(f"Note: {e}")

if __name__ == "__main__":
    init_db()