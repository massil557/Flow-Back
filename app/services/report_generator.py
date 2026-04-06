from io import BytesIO
import os
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session
from app.models import Capteur, Mesure, Alerte, Zone
from app.services.ai_analyzer import analyze_with_ai_summary
import uuid

# Helper to get threshold for a category
def get_threshold_for_category(category: str) -> float:
    thresholds = {
        "Température": 30.0,
        "Pression": 4.0,
        "Humidité": 80.0,
        "Qualité Air": 900.0,
    }
    return thresholds.get(category, 30.0)

# Helper to calculate health score (0-100)
def calculate_health_score(sensor_data, total_alerts, period_days):
    if not sensor_data:
        return 0
    alert_penalty = min(50, total_alerts * 5)
    variances = [s["std_dev"] for s in sensor_data if "std_dev" in s]
    variance_penalty = min(20, sum(variances) / len(variances) / 2) if variances else 0
    score = max(0, 100 - alert_penalty - variance_penalty)
    return round(score)

# Helper to calculate standard deviation
def calculate_std_dev(values):
    if len(values) < 2:
        return 0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return variance ** 0.5

# Page number callback
def add_page_number(canvas_obj, doc):
    page_num = canvas_obj.getPageNumber()
    canvas_obj.saveState()
    canvas_obj.setFont('Helvetica', 8)
    canvas_obj.setFillColor(colors.HexColor('#6b7280'))
    canvas_obj.drawCentredString(doc.width / 2, 0.5 * cm, f"Page {page_num}")
    canvas_obj.restoreState()

async def generate_master_report_pdf(
    period: str,
    start_date: datetime,
    end_date: datetime,
    db: Session,
    category: str = None,
    zone_id: int = None
) -> BytesIO:
    # Base query for sensors
    query = db.query(Capteur).filter(Capteur.is_activated == True)
    if category:
        query = query.filter(Capteur.type_grandeur == category)
    if zone_id:
        query = query.filter(Capteur.zone_id == zone_id)
    sensors = query.all()

    if not sensors:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        doc.build([Paragraph("Aucun capteur actif trouvé pour ces filtres.", getSampleStyleSheet()['Normal'])])
        buffer.seek(0)
        return buffer

    # Prepare data for each sensor
    sensor_data = []
    all_values = []
    for s in sensors:
        measures = db.query(Mesure).filter(
            Mesure.capteur_id == s.id,
            Mesure.time >= start_date,
            Mesure.time <= end_date
        ).all()
        if not measures:
            continue
        values = [m.valeur for m in measures]
        all_values.extend(values)
        alert_count = db.query(Alerte).filter(
            Alerte.capteur_code == s.code_unique,
            Alerte.time >= start_date,
            Alerte.time <= end_date
        ).count()
        sensor_data.append({
            "code": s.code_unique,
            "type": s.type_grandeur,
            "unit": s.unite,
            "min": min(values),
            "max": max(values),
            "avg": sum(values)/len(values),
            "std_dev": calculate_std_dev(values),
            "alert_count": alert_count,
            "values": values
        })

    # Calculate period in days for comparison
    period_days = (end_date - start_date).days or 1

    # Get previous period data for comparison
    prev_end_date = start_date
    prev_start_date = start_date - timedelta(days=period_days)
    prev_sensor_data = []
    for s in sensors:
        measures = db.query(Mesure).filter(
            Mesure.capteur_id == s.id,
            Mesure.time >= prev_start_date,
            Mesure.time <= prev_end_date
        ).all()
        if measures:
            values = [m.valeur for m in measures]
            alert_count = db.query(Alerte).filter(
                Alerte.capteur_code == s.code_unique,
                Alerte.time >= prev_start_date,
                Alerte.time <= prev_end_date
            ).count()
            prev_sensor_data.append({
                "code": s.code_unique,
                "avg": sum(values)/len(values),
                "alert_count": alert_count
            })

    # Calculate comparison metrics
    current_avg = sum(s["avg"] for s in sensor_data) / len(sensor_data) if sensor_data else 0
    prev_avg = sum(s["avg"] for s in prev_sensor_data) / len(prev_sensor_data) if prev_sensor_data else current_avg
    avg_change = ((current_avg - prev_avg) / prev_avg * 100) if prev_avg != 0 else 0

    current_alerts = sum(s["alert_count"] for s in sensor_data)
    prev_alerts = sum(s["alert_count"] for s in prev_sensor_data) if prev_sensor_data else current_alerts
    alert_change = ((current_alerts - prev_alerts) / prev_alerts * 100) if prev_alerts > 0 else (100 if current_alerts > 0 else 0)

    # Zone name
    zone_name = None
    if zone_id:
        zone = db.query(Zone).filter(Zone.id == zone_id).first()
        if zone:
            zone_name = zone.nom_zone

    # Calculate health score
    health_score = calculate_health_score(sensor_data, current_alerts, period_days)

    # Build AI prompt
    threshold = get_threshold_for_category(category) if category else None
    prompt = f"""Rapport {period} – Periode du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}.

Filtres:
- Type de capteur: {category if category else 'Tous'}
- Zone: {zone_name if zone_name else 'Toutes les zones'}

Statistiques:
- Capteurs actifs: {len(sensor_data)}
- Alertes totales: {current_alerts}
- Valeur moyenne generale: {current_avg:.1f}
- Evolution par rapport a la periode precedente: {'hausse' if avg_change > 0 else 'baisse'} de {abs(avg_change):.1f}%
- Score de sante general: {health_score}/100

Donne un resume concis (3-4 phrases) en francais, evaluant la sante generale du systeme, les tendances importantes, et une recommandation principale.
"""
    ai_summary = await analyze_with_ai_summary(prompt)

    # Build PDF
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, textColor=colors.HexColor('#1a2f5e'), alignment=TA_CENTER)
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#1a2f5e'), spaceAfter=12, spaceBefore=12)
    subsection_style = ParagraphStyle('Subsection', parent=styles['Heading3'], fontSize=12, textColor=colors.HexColor('#1a2f5e'), spaceAfter=8, spaceBefore=8)
    normal_style = styles['Normal']
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'))
    bold_s = ParagraphStyle('Bold', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#111827'), fontName='Helvetica-Bold')
    highlight_style = ParagraphStyle('Highlight', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#dc2626'), fontName='Helvetica-Bold')

    # Logo path
    logo_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'cevital.jpg')
    logo_cell = RLImage(logo_path, width=3.5*cm, height=3.5*cm, kind='proportional') if os.path.exists(logo_path) else Paragraph("CEVITAL", bold_s)

    # Generate unique report ID
    report_id = f"REP-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"

    elements = []

    # ========== HEADER ==========
    header = Table(
        [[Paragraph(f"Rapport {period.capitalize()}", title_style), logo_cell]],
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

    # ========== EXECUTIVE SUMMARY TABLE ==========
    elements.append(Paragraph("Resume Executif", section_style))
    summary_data = [
        ["Periode", f"{start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}"],
        ["Type de capteur", category if category else "Tous"],
        ["Zone", zone_name if zone_name else "Toutes les zones"],
        ["Capteurs analyses", str(len(sensor_data))],
        ["Alertes totales", str(current_alerts)],
        ["Score de sante", f"{health_score}/100"],
        ["ID du rapport", report_id],
    ]
    summary_table = Table(summary_data, colWidths=[5*cm, 11*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.5*cm))

    # ========== COMPARISON WITH PREVIOUS PERIOD ==========
    elements.append(Paragraph("Evolution par rapport a la periode precedente", section_style))
    comparison_data = [
        ["Metrique", "Periode actuelle", "Periode precedente", "Evolution"],
        ["Valeur moyenne", f"{current_avg:.1f}", f"{prev_avg:.1f}", f"{avg_change:+.1f}%"],
        ["Alertes", str(current_alerts), str(prev_alerts), f"{alert_change:+.1f}%"],
    ]
    comp_table = Table(comparison_data, colWidths=[5*cm, 3.5*cm, 3.5*cm, 4*cm])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('ALIGN', (2,1), (3,-1), 'CENTER'),
    ]))
    elements.append(comp_table)
    elements.append(Spacer(1, 0.5*cm))

    # ========== TOP 3 WORST SENSORS (only sensors with alerts) ==========
    sensors_with_alerts = [s for s in sensor_data if s["alert_count"] > 0]
    if sensors_with_alerts:
        worst_sensors = sorted(sensors_with_alerts, key=lambda x: x["alert_count"], reverse=True)[:3]
        elements.append(Paragraph("Capteurs les plus critiques", section_style))
        worst_data = [["Capteur", "Valeur moyenne", "Alertes", "Severite"]]
        for s in worst_sensors:
            severity = "Critique" if s["alert_count"] > 5 else "Elevee" if s["alert_count"] > 2 else "Moderee"
            worst_data.append([s["code"], f"{s['avg']:.1f} {s['unit']}", str(s["alert_count"]), severity])
        worst_table = Table(worst_data, colWidths=[5*cm, 3.5*cm, 3*cm, 4*cm])
        worst_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#dc2626')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#fef2f2')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#fca5a5')),
        ]))
        elements.append(worst_table)
        elements.append(Spacer(1, 0.5*cm))

    # ========== ALERT SEVERITY PIE CHART (only if alerts exist) ==========
    if current_alerts > 0:
        elements.append(Paragraph("Distribution des alertes", section_style))
        critical = sum(1 for s in sensor_data if s["alert_count"] > 5)
        high = sum(1 for s in sensor_data if 2 < s["alert_count"] <= 5)
        medium = sum(1 for s in sensor_data if 0 < s["alert_count"] <= 2)
        no_alerts = sum(1 for s in sensor_data if s["alert_count"] == 0)
        
        drawing = Drawing(400, 200)
        pie = Pie()
        pie.x = 150
        pie.y = 50
        pie.width = 100
        pie.height = 100
        pie.data = [critical, high, medium, no_alerts]
        pie.labels = [f'Critique ({critical})', f'Elevee ({high})', f'Moderee ({medium})', f'Sans alerte ({no_alerts})']
        pie.slices.strokeWidth = 0.5
        if no_alerts > 0:
            pie.slices[3].popout = 5
        drawing.add(pie)
        elements.append(drawing)
        elements.append(Spacer(1, 0.3*cm))

    # ========== AI SUMMARY ==========
    elements.append(Paragraph("Analyse IA", section_style))
    elements.append(Paragraph(ai_summary, normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # ========== ACTIONABLE RECOMMENDATIONS ==========
    elements.append(Paragraph("Recommandations", section_style))
    recommendations = []
    if current_alerts > 0:
        recommendations.append(["Haute", "Traiter les alertes critiques immediatement", "Maintenance"])
        recommendations.append(["Moyenne", "Planifier une inspection des capteurs les plus sollicites", "Inspection"])
    if avg_change > 5:
        recommendations.append(["Moyenne", "Surveiller la tendance a la hausse des valeurs", "Surveillance"])
    if health_score < 50:
        recommendations.append(["Critique", "Intervention urgente requise", "Action immediate"])
    if not recommendations:
        recommendations.append(["Basse", "Maintenance preventive normale", "Routine"])
    
    rec_data = [["Priorite", "Action recommandee", "Type"]]
    rec_data.extend(recommendations)
    rec_table = Table(rec_data, colWidths=[3*cm, 10*cm, 4*cm])
    rec_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f0fdf4')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#86efac')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(rec_table)
    elements.append(Spacer(1, 0.5*cm))

    # ========== SENSOR DETAILS TABLE ==========
    if sensor_data:
        elements.append(Paragraph("Details par capteur", section_style))
        sensor_table_data = [["Capteur", "Min", "Max", "Moyenne", "Ecart-type", "Alertes"]]
        for s in sensor_data[:20]:
            sensor_table_data.append([
                s["code"],
                f"{s['min']:.1f} {s['unit']}",
                f"{s['max']:.1f} {s['unit']}",
                f"{s['avg']:.1f} {s['unit']}",
                f"{s['std_dev']:.2f}",
                str(s["alert_count"])
            ])
        if len(sensor_data) > 20:
            sensor_table_data.append(["", "", "", f"... et {len(sensor_data)-20} autres capteurs", "", ""])
        
        sensor_table = Table(sensor_table_data, colWidths=[4*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        sensor_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(sensor_table)
        elements.append(Spacer(1, 0.5*cm))

    # ========== ANOMALY DETECTION HIGHLIGHTS ==========
    if all_values:
        mean = sum(all_values) / len(all_values)
        std = calculate_std_dev(all_values)
        anomalies = [v for v in all_values if abs(v - mean) > 2 * std]
        elements.append(Paragraph("Detection d'anomalies", section_style))
        if anomalies:
            anomaly_text = f"Detection de {len(anomalies)} valeurs anormales sur {len(all_values)} mesures (ecart type > 2). Ces valeurs meritent une attention particuliere."
            elements.append(Paragraph(anomaly_text, highlight_style))
        else:
            elements.append(Paragraph("Aucune anomalie significative detectee durant la periode.", normal_style))
        elements.append(Spacer(1, 0.5*cm))

    # ========== FOOTER ==========
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Document confidentiel – genere automatiquement par Flow · Supervision industrielle Cevital", small_style))
    elements.append(Paragraph(f"Genere le {datetime.now().strftime('%d/%m/%Y a %H:%M')} | ID: {report_id}", small_style))

    # Build PDF with page numbers
    doc.build(elements, onFirstPage=add_page_number, onLaterPages=add_page_number)
    buffer.seek(0)
    return buffer