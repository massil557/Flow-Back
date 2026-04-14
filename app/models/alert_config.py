from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from app.database import Base


class AlertConfig(Base):
    """
    Règle d'alerte configurable depuis l'UI.
    Une règle surveille un préfixe de capteur (ex: "TEMP") ou un code exact.
    Elle définit deux niveaux : warning et danger.
    """
    __tablename__ = "alert_configs"

    id                      = Column(Integer, primary_key=True, index=True)
    # Identifiant du capteur ou préfixe (ex: "TEMP", "TEMP-01", "PRES")
    sensor_prefix           = Column(String(50), nullable=False)
    label                   = Column(String(100), nullable=False)          # Nom affiché
    # Niveaux de seuil
    warning_threshold       = Column(Float, nullable=False)                # seuil avertissement
    danger_threshold        = Column(Float, nullable=False)                # seuil danger/critique
    # Intervalle de rappel (évite le spam email)
    reminder_interval_min   = Column(Integer, default=30, nullable=False)  # minutes
    # Destinataires email (séparés par virgule)
    email_recipients        = Column(Text, default="", nullable=False)
    # Message personnalisé (optionnel)
    custom_message          = Column(Text, default="", nullable=False)
    # Activation
    is_enabled              = Column(Boolean, default=True, nullable=False)
