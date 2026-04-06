from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# For single-sensor AI report (dashboard)
class ReportRequest(BaseModel):
    data: List['GraphPoint']  # forward ref to avoid circular import
    sensor_name: Optional[str] = "Capteur"
    threshold: float = 30

# For master report (daily/weekly/monthly)
class MasterReportRequest(BaseModel):
    period: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    recipients: Optional[List[str]] = None
    category: Optional[str] = None      # "Température", "Pression", "Humidité", "Qualité Air"
    zone_id: Optional[int] = None

# For email sending of report (used by send-report-email endpoint)
class EmailReportRequest(BaseModel):
    to_email: str
    sensor_name: str
    pdf_base64: str
    chart_base64: Optional[str] = None

# Forward reference fix
from .sensor import GraphPoint
ReportRequest.model_rebuild()