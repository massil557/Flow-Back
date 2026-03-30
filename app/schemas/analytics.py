from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class TimeSeriesRequest(BaseModel):
    category: str
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    hours: Optional[float] = None
    interval: str = "hour"
    zone_id: Optional[int] = None