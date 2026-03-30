from pydantic import BaseModel

class AlertTrigger(BaseModel):
    capteur_code: str
    valeur: float
    seuil_depasse: float
    message: str