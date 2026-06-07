from sqlalchemy import Column, Integer, String, Float, Boolean, Text, ForeignKey
from app.database import Base


class AlertConfig(Base):
    """
    Règle d'alerte configurable depuis l'UI.
    Une règle surveille un préfixe de capteur (ex: "TEMP") ou un code exact,
    ou un capteur spécifique (via sensor_id).
    Elle définit deux niveaux : warning et danger.
    """
    __tablename__ = "alert_configs"

    id                      = Column(Integer, primary_key=True, index=True)
    sensor_id               = Column(Integer, ForeignKey("capteurs.id"), nullable=True)
    sensor_prefix           = Column(String(50), nullable=False)
    label                   = Column(String(100), nullable=False)
    warning_threshold       = Column(Float, nullable=False)
    danger_threshold        = Column(Float, nullable=False)
    reminder_interval_min   = Column(Integer, default=30, nullable=False)
    email_recipients        = Column(Text, default="", nullable=False)
    custom_message          = Column(Text, default="", nullable=False)
    is_enabled              = Column(Boolean, default=True, nullable=False)
