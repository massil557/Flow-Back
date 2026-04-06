from ast import List
import asyncio
import os
from datetime import datetime, timedelta
from app.database import SessionLocal
from app.services.report_generator import generate_master_report_pdf
from app.services.email_service import send_pdf_via_email
from typing import List

async def _send_report_background(pdf_bytes: bytes, recipients: List[str], period: str):
    """Send a pre-generated PDF report via email."""
    await send_pdf_via_email(
        recipients,
        f"Rapport {period} – Cevital",
        pdf_bytes,
        f"rapport_{period}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    )

async def send_scheduled_report(period: str):
    db = SessionLocal()
    try:
        end_date = datetime.utcnow()
        if period == "daily":
            start_date = end_date - timedelta(days=1)
        elif period == "weekly":
            start_date = end_date - timedelta(days=7)
        elif period == "monthly":
            start_date = end_date - timedelta(days=30)
        else:
            return
        recipients = [os.getenv("MANAGER_EMAIL", "manager@cevital.dz")]
        pdf_buffer = await generate_master_report_pdf(period, start_date, end_date, db)
        pdf_bytes = pdf_buffer.getvalue()
        await send_pdf_via_email(recipients, f"Rapport {period.capitalize()} – Cevital", pdf_bytes, f"rapport_{period}_{end_date.strftime('%Y%m%d')}.pdf")
        print(f"Scheduled {period} report sent.")
    except Exception as e:
        print(f"Failed to send scheduled {period} report: {e}")
    finally:
        db.close()