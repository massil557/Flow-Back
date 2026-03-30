from pydantic import BaseModel
from typing import Optional, List, Dict

class ZoneCreate(BaseModel):
    nom_zone: str
    code_zone: str
    type: str = "Process"
    x: float = 100
    y: float = 100
    w: float = 120
    h: float = 100

class ZoneUpdate(BaseModel):
    nom_zone: Optional[str] = None
    code_zone: Optional[str] = None
    type: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None

class ZoneStatsResponse(BaseModel):
    zone_id: int
    sensor_count: int
    active_alerts: int
    sensors: List[dict]
    latest_values: dict