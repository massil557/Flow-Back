from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import asyncio
import os
import io
import re
from email.message import EmailMessage
import aiosmtplib
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
    Table, TableStyle, Image as RLImage
)
from datetime import datetime as _dt_now

from app.database import get_db
from app.schemas import ReportRequest, MasterReportRequest, EmailReportRequest
from app.services.ai_analyzer import analyze_with_ai
from app.services.report_generator import generate_master_report_pdf
from app.services.email_service import send_pdf_via_email, send_alert_email
from app.services.scheduler import _send_report_background

router = APIRouter(tags=["Reports"])

# Original per‑sensor AI report (dashboard)
@router.post("/generate-report")
async def generate_report(req: ReportRequest):
    analysis = await analyze_with_ai(req.data, req.sensor_name, req.threshold)

    # Logo path: go up from app/routers/reports.py to project root (3 levels)
    logo_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'cevital.jpg'
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        rightMargin=2*cm, leftMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm,
    )

    # ── Styles ────────────────────────────────────────────────────────────────
    NAVY   = colors.HexColor('#1a2f5e')
    GRAY   = colors.HexColor('#6b7280')
    DARK   = colors.HexColor('#111827')
    BODY   = colors.HexColor('#374151')
    RED    = colors.HexColor('#dc2626')
    GREEN  = colors.HexColor('#16a34a')
    ORANGE = colors.HexColor('#d97706')
    BGRED  = colors.HexColor('#fef2f2')
    BGGRN  = colors.HexColor('#f0fdf4')
    BGBLUE = colors.HexColor('#eff6ff')
    BGGRAY = colors.HexColor('#f8fafc')
    BORDER = colors.HexColor('#e2e8f0')

    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    title_s   = style('T', fontName='Helvetica-Bold', fontSize=20, textColor=NAVY, leading=26)
    section_s = style('S', fontName='Helvetica-Bold', fontSize=11, textColor=NAVY,
                      spaceBefore=14, spaceAfter=4, leading=16)
    body_s    = style('B', fontName='Helvetica', fontSize=10, textColor=BODY,
                      leading=16, spaceAfter=4, alignment=TA_JUSTIFY)
    bold_s    = style('Bo', fontName='Helvetica-Bold', fontSize=10, textColor=DARK, leading=16)
    small_s   = style('Sm', fontName='Helvetica', fontSize=8, textColor=GRAY, leading=12)
    footer_s  = style('F', fontName='Helvetica', fontSize=7, textColor=GRAY, alignment=TA_CENTER)
    alert_s   = style('Al', fontName='Helvetica-Bold', fontSize=11, textColor=RED)
    stable_s  = style('St', fontName='Helvetica-Bold', fontSize=11, textColor=GREEN)
    orange_s  = style('Or', fontName='Helvetica-Bold', fontSize=10, textColor=ORANGE)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def clean(text):
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*\*', '', text)
        text = re.sub(r'\*', '', text)
        text = re.sub(r'##?\s*', '', text)
        text = re.sub(r'^\[(.+?)\]$', r'\1', text, flags=re.MULTILINE)
        return text.strip()

    def extract(text, keys):
        for k in keys:
            m = re.search(rf'{k}\s*[:\-]?\s*\n?(.+?)(?=\n\d\)|\n[A-Z]{{3}}|$)', text, re.IGNORECASE | re.DOTALL)
            if m:
                return clean(m.group(1).strip())
        return None

    def bullet_table(items, bg, border_col):
        rows = []
        for item in items:
            item = clean(item)
            if item:
                rows.append([
                    Paragraph("→", bold_s),
                    Paragraph(item, body_s)
                ])
        if not rows:
            return None
        t = Table(rows, colWidths=[0.6*cm, 15*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), bg),
            ('BOX', (0,0), (-1,-1), 0.5, border_col),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        return t

    # ── Parse sections ────────────────────────────────────────────────────────
    diagnostic  = extract(analysis, ['1\\) DIAGNOSTIC'])
    gravite     = extract(analysis, ['2\\) GRAVITE'])
    tendance    = extract(analysis, ['3\\) TENDANCE'])
    cause       = extract(analysis, ['4\\) CAUSE PROBABLE'])
    actions_raw = extract(analysis, ['5\\) ACTIONS IMMEDIATES'])
    prevention_raw = extract(analysis, ['6\\) PREVENTION LONG TERME'])

    is_alert = diagnostic and any(w in (diagnostic + (gravite or '')).upper()
                                  for w in ['ALERTE', 'CRITIQUE', 'DANGER'])

    actions    = [l.lstrip('-• ').strip() for l in (actions_raw or '').split('\n') if l.strip()]
    prevention = [l.lstrip('-• ').strip() for l in (prevention_raw or '').split('\n') if l.strip()]

    now_str = _dt_now.now().strftime("%d/%m/%Y à %H:%M")

    # ── Build PDF ─────────────────────────────────────────────────────────────
    elements = []

    # Header: title + logo
    logo_cell = RLImage(logo_path, width=3.5*cm, height=3.5*cm, kind='proportional') \
                if os.path.exists(logo_path) else Paragraph("CEVITAL", bold_s)

    header = Table(
        [[Paragraph("RAPPORT D'ANALYSE TECHNIQUE", title_s), logo_cell]],
        colWidths=[12*cm, 4*cm]
    )
    header.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,0), (1,0), 'RIGHT'),
        ('LEFTPADDING', (0,0), (-1,-1), 0),
        ('RIGHTPADDING', (0,0), (-1,-1), 0),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 0.3*cm))
    elements.append(HRFlowable(width="100%", thickness=2, color=NAVY))
    elements.append(Spacer(1, 0.3*cm))

    # Subtitle
    elements.append(Paragraph(
        f"Système de supervision industrielle — Cevital  |  Généré le {now_str}",
        small_s
    ))
    elements.append(Spacer(1, 0.4*cm))

    # Metadata table
    meta = [
        [Paragraph("Capteur analysé", bold_s),    Paragraph(req.sensor_name, body_s)],
        [Paragraph("Seuil critique", bold_s),      Paragraph(f"{req.threshold} unités", body_s)],
        [Paragraph("Mesures analysées", bold_s),   Paragraph(f"{len(req.data)} points", body_s)],
        [Paragraph("Date du rapport", bold_s),     Paragraph(now_str, body_s)],
        [Paragraph("Statut global", bold_s),
         Paragraph("⚠ ALERTE CRITIQUE" if is_alert else "✓ FONCTIONNEMENT NORMAL",
                   alert_s if is_alert else stable_s)],
    ]
    meta_t = Table(meta, colWidths=[5*cm, 11*cm])
    meta_t.setStyle(TableStyle([
        ('ROWBACKGROUNDS', (0,0), (-1,-1), [BGGRAY, colors.white]),
        ('GRID', (0,0), (-1,-1), 0.5, BORDER),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 7),
        ('BOTTOMPADDING', (0,0), (-1,-1), 7),
        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f1f5f9')),
    ]))
    elements.append(meta_t)
    elements.append(Spacer(1, 0.5*cm))

    # Section divider
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elements.append(Paragraph("RÉSULTATS DE L'ANALYSE IA", style(
        'AI', fontName='Helvetica-Bold', fontSize=13, textColor=NAVY,
        spaceBefore=10, spaceAfter=6
    )))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elements.append(Spacer(1, 0.3*cm))

    # 1. Diagnostic box
    if diagnostic:
        diag_bg  = BGRED if is_alert else BGGRN
        diag_br  = colors.HexColor('#fca5a5') if is_alert else colors.HexColor('#86efac')
        diag_p   = Paragraph(diagnostic, alert_s if is_alert else stable_s)
        icon     = "⚠" if is_alert else "✓"
        diag_tbl = Table(
            [[Paragraph(f"{icon}  DIAGNOSTIC", section_s), diag_p]],
            colWidths=[4.5*cm, 11.5*cm]
        )
        diag_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), diag_bg),
            ('BOX', (0,0), (-1,-1), 1.5, diag_br),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ]))
        elements.append(diag_tbl)
        elements.append(Spacer(1, 0.3*cm))

    # 2. Gravite
    if gravite:
        grav_color = RED if 'critique' in gravite.lower() else \
                     ORANGE if 'moder' in gravite.lower() else GREEN
        grav_style = style('G', fontName='Helvetica-Bold', fontSize=10, textColor=grav_color)
        elements.append(Paragraph("NIVEAU DE GRAVITÉ", section_s))
        elements.append(Paragraph(gravite, grav_style))
        elements.append(Spacer(1, 0.25*cm))

    # 3. Tendance
    if tendance:
        elements.append(Paragraph("TENDANCE D'ÉVOLUTION", section_s))
        elements.append(Paragraph(tendance, body_s))
        elements.append(Spacer(1, 0.25*cm))

    # 4. Cause probable
    if cause:
        elements.append(Paragraph("CAUSE PROBABLE", section_s))
        cause_t = Table(
            [[Paragraph("!", style('Ex', fontName='Helvetica-Bold', fontSize=14,
                                   textColor=ORANGE)), Paragraph(cause, body_s)]],
            colWidths=[0.8*cm, 15.2*cm]
        )
        cause_t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#fffbeb')),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#fcd34d')),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        elements.append(cause_t)
        elements.append(Spacer(1, 0.25*cm))

    # 5. Actions immediates
    if actions:
        elements.append(Paragraph("ACTIONS IMMÉDIATES", section_s))
        t = bullet_table(actions, BGRED if is_alert else BGBLUE,
                         colors.HexColor('#fca5a5') if is_alert else colors.HexColor('#93c5fd'))
        if t:
            elements.append(t)
        elements.append(Spacer(1, 0.25*cm))

    # 6. Prevention long terme
    if prevention:
        elements.append(Paragraph("PRÉVENTION LONG TERME", section_s))
        t = bullet_table(prevention, colors.HexColor('#f0fdf4'),
                         colors.HexColor('#86efac'))
        if t:
            elements.append(t)
        elements.append(Spacer(1, 0.4*cm))

    # Footer
    elements.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    elements.append(Spacer(1, 0.2*cm))
    elements.append(Paragraph(
        f"Document confidentiel — généré automatiquement par Flow · Supervision industrielle Cevital · {now_str}",
        footer_s
    ))

    doc.build(elements)
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="application/pdf")

@router.post("/send-report-email")
async def send_report_email(req: EmailReportRequest):
    import base64
    try:
        pdf_bytes = base64.b64decode(req.pdf_base64)
        msg = EmailMessage()
        msg["Subject"] = f"Rapport d'Analyse IA — Capteur {req.sensor_name}"
        msg["From"] = os.getenv("ALERT_EMAIL_SENDER", "mascioul8@gmail.com")
        msg["To"] = req.to_email
        msg.set_content(
            f"Bonjour,\n\n"
            f"Veuillez trouver en pièce jointe :\n"
            f"  - Le rapport d'analyse IA (PDF)\n"
            f"  - Le graphique du capteur {req.sensor_name} (PNG)\n\n"
            f"Cordialement,\nSystème de Monitoring Flow — Cevital"
        )
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"Rapport_IA_{req.sensor_name}.pdf")
        if req.chart_base64:
            chart_bytes = base64.b64decode(req.chart_base64)
            msg.add_attachment(chart_bytes, maintype="image", subtype="png", filename=f"Graphique_{req.sensor_name}.png")
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=465,
            username=os.getenv("ALERT_EMAIL_SENDER", "mascioul8@gmail.com"),
            password=os.getenv("ALERT_EMAIL_PASSWORD"),
            use_tls=True,
            timeout=30,
        )
        return {"success": True}
    except Exception as e:
        print(f"Erreur envoi rapport : {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Master report (manual & scheduled)
@router.post("/api/reports/send")
async def send_master_report(req: MasterReportRequest, db: Session = Depends(get_db)):
    # Determine date range (same as before)
    if req.period:
        end_date = datetime.utcnow()
        if req.period == "daily":
            start_date = end_date - timedelta(days=1)
        elif req.period == "weekly":
            start_date = end_date - timedelta(days=7)
        elif req.period == "monthly":
            start_date = end_date - timedelta(days=30)
        else:
            raise HTTPException(status_code=400, detail="Invalid period")
    elif req.start and req.end:
        start_date = req.start
        end_date = req.end
    else:
        raise HTTPException(status_code=400, detail="Either period or start/end must be provided")

    recipients = req.recipients if req.recipients else [os.getenv("MANAGER_EMAIL", "manager@cevital.dz")]

    # Generate PDF with optional category and zone filters
    pdf_buffer = await generate_master_report_pdf(
       req.period or "custom",
      start_date,
     end_date,
     db,
     category=req.category,
     zone_id=req.zone_id
    )
    pdf_bytes = pdf_buffer.getvalue()
    asyncio.create_task(_send_report_background(pdf_bytes, recipients, req.period or "custom"))
    return {"success": True, "message": "La generation du rapport a commence. Vous recevrez l'email sous peu."}