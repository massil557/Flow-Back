from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from sqlalchemy.orm import Session
from app.models import Capteur, Mesure, Alerte, Zone
from app.services.ai_analyzer import analyze_with_ai_summary

async def generate_master_report_pdf(period: str, start_date: datetime, end_date: datetime, db: Session) -> BytesIO:
    sensors = db.query(Capteur).filter(Capteur.is_activated == True).all()
    if not sensors:
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        doc.build([Paragraph("Aucun capteur actif trouvé.", getSampleStyleSheet()['Normal'])])
        buffer.seek(0)
        return buffer

    sensor_data = []
    for s in sensors:
        measures = db.query(Mesure).filter(
            Mesure.capteur_id == s.id,
            Mesure.time >= start_date,
            Mesure.time <= end_date
        ).all()
        if not measures:
            continue
        values = [m.valeur for m in measures]
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
            "alert_count": alert_count
        })

    zones = db.query(Zone).all()
    zone_stats = []
    for z in zones:
        zone_sensors = [s for s in sensors if s.zone_id == z.id]
        if not zone_sensors:
            continue
        all_vals = []
        for s in zone_sensors:
            measures = db.query(Mesure).filter(
                Mesure.capteur_id == s.id,
                Mesure.time >= start_date,
                Mesure.time <= end_date
            ).all()
            all_vals.extend([m.valeur for m in measures])
        zone_avg = sum(all_vals)/len(all_vals) if all_vals else 0
        active_alerts = sum(1 for s in zone_sensors if db.query(Alerte).filter(
            Alerte.capteur_code == s.code_unique,
            Alerte.is_resolved == False
        ).count() > 0)
        zone_stats.append({
            "name": z.nom_zone,
            "sensor_count": len(zone_sensors),
            "avg_value": zone_avg,
            "active_alerts": active_alerts
        })

    total_alerts = sum(s["alert_count"] for s in sensor_data)
    worst_zone = max(zone_stats, key=lambda z: z["active_alerts"]) if zone_stats else None
    prompt = f"""Rapport {period} – Période du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}.

Total capteurs actifs: {len(sensor_data)}
Alertes totales durant la période: {total_alerts}
Zone avec le plus d'alertes actives: {worst_zone['name'] if worst_zone else 'aucune'} ({worst_zone['active_alerts'] if worst_zone else 0} alertes)

Donne un résumé concis (3-4 phrases) en français, évaluant la santé générale du système et une recommandation principale.
"""
    ai_summary = await analyze_with_ai_summary(prompt)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=2.5*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=20, textColor=colors.HexColor('#1a2f5e'))
    section_style = ParagraphStyle('Section', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#1a2f5e'), spaceAfter=12)
    normal_style = styles['Normal']
    small_style = ParagraphStyle('Small', parent=styles['Normal'], fontSize=8, textColor=colors.HexColor('#6b7280'))

    elements = []
    elements.append(Paragraph(f"Rapport {period.capitalize()}", title_style))
    elements.append(Paragraph(f"Période: {start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    metrics = [
        ["Capteurs actifs", str(len(sensor_data))],
        ["Alertes totales (période)", str(total_alerts)],
        ["Zone avec le plus d'alertes", worst_zone['name'] if worst_zone else "Aucune"],
        ["Alertes actives dans cette zone", str(worst_zone['active_alerts']) if worst_zone else "0"]
    ]
    metrics_table = Table(metrics, colWidths=[8*cm, 8*cm])
    metrics_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(metrics_table)
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Résumé IA", section_style))
    elements.append(Paragraph(ai_summary, normal_style))
    elements.append(Spacer(1, 0.5*cm))

    elements.append(Paragraph("Performance par zone", section_style))
    zone_table_data = [["Zone", "Capteurs", "Moyenne", "Alertes actives"]]
    for z in zone_stats:
        zone_table_data.append([
            z["name"],
            str(z["sensor_count"]),
            f"{z['avg_value']:.1f}",
            str(z["active_alerts"])
        ])
    zone_table = Table(zone_table_data, colWidths=[5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
    zone_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 12),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
    ]))
    elements.append(zone_table)
    elements.append(Spacer(1, 0.5*cm))

    active_alerts = db.query(Alerte).filter(Alerte.is_resolved == False).limit(5).all()
    if active_alerts:
        elements.append(Paragraph("Alertes actives (les plus récentes)", section_style))
        alerts_data = [["Capteur", "Valeur", "Seuil", "Date"]]
        for a in active_alerts:
            alerts_data.append([
                a.capteur_code,
                f"{a.valeur:.1f}",
                f"{a.seuil_depasse:.1f}",
                a.time.strftime("%d/%m %H:%M")
            ])
        alerts_table = Table(alerts_data, colWidths=[4*cm, 2.5*cm, 2.5*cm, 3*cm])
        alerts_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a2f5e')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#fef2f2') if a.valeur >= a.seuil_depasse else colors.HexColor('#f8fafc')),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(alerts_table)
        elements.append(Spacer(1, 0.5*cm))

    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Document confidentiel – généré automatiquement par Flow · Supervision industrielle Cevital", small_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer