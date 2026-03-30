from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class SensorCreate(BaseModel):
    code_unique: str
    type_grandeur: str
    unite: str
    adresse_ip: str
    zone_id: int

class TogglePayload(BaseModel):
    activate: bool

class GraphPoint(BaseModel):
    x: datetime
    y: float