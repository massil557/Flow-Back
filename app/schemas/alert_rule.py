from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AlertRuleCreate(BaseModel):
    sensor_id:       int
    condition:       str = Field(..., pattern="^(>|<|>=|<=|==)$")
    threshold:       float
    severity:        str = Field(..., pattern="^(danger|warning)$")
    cooldown_seconds: int = 0

class AlertRuleUpdate(BaseModel):
    condition:        Optional[str] = None
    threshold:        Optional[float] = None
    severity:         Optional[str] = None
    cooldown_seconds: Optional[int] = None
    active:           Optional[bool] = None

class AlertRuleOut(BaseModel):
    id:              int
    sensor_id:       int
    condition:       str
    threshold:       float
    severity:        str
    cooldown_seconds: int
    active:          bool
    created_at:      datetime

    class Config:
        from_attributes = True
