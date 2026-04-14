from pydantic import BaseModel, Field
from typing import Optional


class AlertConfigCreate(BaseModel):
    sensor_prefix:         str   = Field(..., min_length=1, max_length=50)
    label:                 str   = Field(..., min_length=1, max_length=100)
    warning_threshold:     float
    danger_threshold:      float
    reminder_interval_min: int   = Field(default=30, ge=1, le=1440)
    email_recipients:      str   = ""      # "a@b.com, c@d.com"
    custom_message:        str   = ""
    is_enabled:            bool  = True


class AlertConfigUpdate(BaseModel):
    sensor_prefix:         Optional[str]   = None
    label:                 Optional[str]   = None
    warning_threshold:     Optional[float] = None
    danger_threshold:      Optional[float] = None
    reminder_interval_min: Optional[int]   = None
    email_recipients:      Optional[str]   = None
    custom_message:        Optional[str]   = None
    is_enabled:            Optional[bool]  = None


class AlertConfigOut(BaseModel):
    id:                    int
    sensor_prefix:         str
    label:                 str
    warning_threshold:     float
    danger_threshold:      float
    reminder_interval_min: int
    email_recipients:      str
    custom_message:        str
    is_enabled:            bool

    class Config:
        from_attributes = True
