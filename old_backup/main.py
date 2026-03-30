import asyncio
import os
from datetime import datetime, timedelta
from collections import deque
import math

from dotenv import load_dotenv
from sqlalchemy import func
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from asyncua import Client
from datetime import datetime
from pydantic import BaseModel
# --- GOOGLE AI IMPORT ---

# Importation de tes fichiers locaux
from database import SessionLocal, engine, Base
import models
from models import Alerte, Utilisateur, Role


# ── Auth imports ──────────────────────────────────────────────────────────────
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from auth import hash_password, verify_password, create_access_token, decode_access_token

#----------
import secrets
import string

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import cm
from io import BytesIO
import base64

from typing import Optional
# --- INITIALISATION ---
app = FastAPI(title="Industrial IoT Gateway - Master 2")

# CORS
origins_allowed = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins_allowed, 
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

ALERT_EMAIL_SENDER    = os.getenv("ALERT_EMAIL_SENDER", "mascioul8@gmail.com")
ALERT_EMAIL_PASSWORD  = os.getenv("ALERT_EMAIL_PASSWORD")
ALERT_EMAIL_RECIPIENT = os.getenv("ALERT_EMAIL_RECIPIENT", "ademoulhaci123@gmail.com")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Configuration de l'URL OPC UA
OPC_URL = "opc.tcp://127.0.0.1:4840/freeopcua/server/"

# Cache en mémoire vive
live_cache = {}
last_two = {}

from collections import deque as _dq
alerts = _dq(maxlen=200)

# Per-sensor-type thresholds (matches simulator danger ranges)
SENSOR_THRESHOLDS = {
    'TEMP': 30.0,   # °C
    'PRES': 4.0,    # bar
    'HUMI': 80.0,   # %
    'CO2':  900.0,  # ppm
}
DEFAULT_THRESHOLD = 30.0

def get_threshold(code_unique: str) -> float:
    for prefix, val in SENSOR_THRESHOLDS.items():
        if prefix in code_unique.upper():
            return val
    return DEFAULT_THRESHOLD

_email_cooldown = {}
EMAIL_COOLDOWN_SECONDS = 300
from email.message import EmailMessage
import aiosmtplib




# helper asynchrone pour envoyer le mail d'alerte
async def send_alert_email(sensor_code: str, value: float, timestamp: str, message: str):
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return

    msg = EmailMessage()
    msg["Subject"] = f"ALERTE : {sensor_code} ({value})"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ALERT_EMAIL_RECIPIENT
    msg.set_content(f"Capteur: {sensor_code}\nValeur: {value}\nTemps: {timestamp}\n{message}")

    for attempt in range(3):
        try:
            await asyncio.sleep(attempt * 5)
            await aiosmtplib.send(
                msg,
                hostname="smtp.gmail.com",
                port=465,
                username=ALERT_EMAIL_SENDER,
                password=ALERT_EMAIL_PASSWORD,
                use_tls=True,
                timeout=30
            )
            print(f"Mail envoye pour {sensor_code}")
            return
        except Exception as exc:
            print(f"Erreur mail tentative {attempt+1}/3 : {exc}")
            if attempt == 2:
                print(f"Email abandonne pour {sensor_code} apres 3 tentatives")
# tâche de fond principale
async def log_and_cache_forever():
    global live_cache
    while True:
        db = SessionLocal()
        try:
            async with Client(url=OPC_URL) as client:
                sensors = db.query(models.Capteur).all()
                if not sensors:
                    print("Aucun capteur trouvé en BDD. Lance seed_db.py.")
                for s in sensors:
                    if not s.is_activated:
                        continue
                    try:
                        path = ["0:Objects", "2:Machine_Alpha", f"2:{s.code_unique}"]
                        node = await client.nodes.root.get_child(path)
                        val_brute = await node.read_value()
                        val = round(float(val_brute), 2)
                        current_time = datetime.now().strftime("%H:%M:%S")

                        if s.code_unique not in live_cache:
                            live_cache[s.code_unique] = deque(maxlen=20)
                        live_cache[s.code_unique].append({"v": val, "t": current_time})

                        if s.code_unique not in last_two:
                            last_two[s.code_unique] = []
                        last_two[s.code_unique].append(val)
                        if len(last_two[s.code_unique]) > 2:
                            last_two[s.code_unique].pop(0)

                        sensor_threshold = get_threshold(s.code_unique)
                        if val >= sensor_threshold:
                            prev_vals = last_two.get(s.code_unique, [])
                            prev_val = prev_vals[-2] if len(prev_vals) > 1 else None
                            if prev_val is None or prev_val < sensor_threshold:
                                alert_msg = f"Valeur {val} >= seuil {sensor_threshold}"
                                # Save to DB
                                db_alert = models.Alerte(
                                    capteur_code=s.code_unique,
                                    valeur=val,
                                    seuil_depasse=sensor_threshold,
                                    message=alert_msg,
                                    time=datetime.utcnow(),
                                    is_resolved=False
                                )
                                db.add(db_alert)
                                # now_ts = datetime.utcnow().timestamp()
                                # if now_ts - _email_cooldown.get(s.code_unique, 0) > EMAIL_COOLDOWN_SECONDS:
                                #     _email_cooldown[s.code_unique] = now_ts
                                #     asyncio.create_task(send_alert_email(s.code_unique, val, current_time, alert_msg))

                        new_measure = models.Mesure(
                            capteur_id=s.id,
                            valeur=val,
                            time=datetime.utcnow(),
                        )
                        db.add(new_measure)
                    except Exception:
                        continue
                db.commit()
        except Exception as e:
            print(f"Erreur de connexion OPC UA : {e}")
        finally:
            db.close()
        await asyncio.sleep(1)

# --- API UTILITAIRES ---
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime as _dt

class SensorCreate(BaseModel):
    code_unique: str
    type_grandeur: str
    unite: str
    adresse_ip: str
    zone_id: int

class TogglePayload(BaseModel):
    activate: bool

class GraphPoint(BaseModel):
    x: _dt
    y: float

class ReportRequest(BaseModel):
    data: List[GraphPoint]
    sensor_name: Optional[str] = "Capteur"
    threshold: float = 30  # Ajoute cette ligne pour accepter la donnée de React

# Zone CRUD models
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

# Renamed class to avoid conflict
class MasterReportRequest(BaseModel):
    period: Optional[str] = None          # "daily", "weekly", "monthly"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    recipients: Optional[List[str]] = None   # if not provided, use configured emails

class ZoneStatsResponse(BaseModel):
    zone_id: int
    sensor_count: int
    active_alerts: int
    sensors: List[dict]
    latest_values: dict    

# --- AI ANALYSIS HELPER ---
# async def _analyze_with_ai(points: list[GraphPoint], sensor_name: str) -> str:
#     try:
#         # 1. Prepare data
#         recent_values = [p.y for p in points[-30:]]
#         if not recent_values:
#             return "Pas de données."

#         prompt = (
#     f"En tant qu'expert en maintenance prédictive IoT, analyse le capteur {sensor_name}.\n"
#     f"Données récentes : {recent_values}\n"
#     f"Seuil de sécurité : {DANGER_THRESHOLD}°C\n\n"
#     "Structure ton rapport ainsi :\n"
#     "1. DIAGNOSTIC : (Stable, Fluctuation ou Alerte)\n"
#     "2. ANALYSE : (Explique la tendance en une phrase)\n"
#     "3. RECOMMANDATION : (Action immédiate ou surveillance normale)\n"
#     "Sois précis, technique et utilise un ton formel."
# )

#         # 2. DYNAMIC DISCOVERY: Find a model that actually exists for your key
#         def get_available_analysis():
#             # Get list of models and find the first one that supports 'generateContent'
#             available_models = [m.name for m in genai.list_models() 
#                                if 'generateContent' in m.supported_generation_methods]
            
#             if not available_models:
#                 raise Exception("Aucun modèle trouvé pour cette clé API.")
            
#             # Pick the best available (prefer flash, then pro, then whatever is first)
#             selected_model = available_models[0]
#             for m in available_models:
#                 if "flash" in m:
#                     selected_model = m
#                     break
            
#             print(f"[IA] Utilisation du modèle détecté : {selected_model}")
#             model_instance = genai.GenerativeModel(selected_model)
#             return model_instance.generate_content(prompt)

#         # 3. Run in thread
#         loop = asyncio.get_event_loop()
#         response = await loop.run_in_executor(None, get_available_analysis)
        
#         return response.text.strip()

#     except Exception as e:
#         print(f"--- ERREUR CRITIQUE IA ---: {e}")
#         return f"Échec de l'analyse dynamique (Détail: {str(e)[:40]}...)"

def save_alert_to_db(db: Session, code: str, value: float, threshold: float):
    new_alert = Alerte(
        capteur_code=code,
        valeur=value,
        seuil_depasse=threshold,
        message=f"Dépassement critique : {value} mesuré (Seuil : {threshold})",
        time=datetime.datetime.utcnow()
    )
    db.add(new_alert)
    db.commit()
    print(f"⚠️ Alerte enregistrée en BDD pour {code}")


# async def _analyze_with_ai(points: list[GraphPoint], sensor_name: str, threshold: float) -> str:
#     try:
#         import httpx
#         recent_values = [p.y for p in points[-30:]]
#         if not recent_values:
#             return "1) DIAGNOSTIC: Aucune donnee disponible.\n2) TENDANCE: Aucune donnee.\n3) RECOMMANDATION: Verifier la connexion du capteur."

#         min_val = round(min(recent_values), 2)
#         max_val = round(max(recent_values), 2)
#         avg_val = round(sum(recent_values) / len(recent_values), 2)
#         over_threshold = len([v for v in recent_values if v >= threshold])

#         code = sensor_name.upper()
#         if "TEMP" in code:
#             sensor_type = "temperature (C)"
#             context = "surchauffe moteur, panne refroidissement, isolation defectueuse"
#         elif "PRES" in code:
#             sensor_type = "pression (bar)"
#             context = "surpression, fuite de circuit, obstruction conduite"
#         elif "HUMI" in code:
#             sensor_type = "humidite (%)"
#             context = "condensation, corrosion equipements, infiltration eau"
#         elif "CO2" in code:
#             sensor_type = "qualite air CO2 (ppm)"
#             context = "ventilation insuffisante, accumulation gaz, danger respiratoire"
#         else:
#             sensor_type = "grandeur industrielle"
#             context = "anomalie capteur, derive mesure, dysfonctionnement equipement"

#         is_alert = over_threshold > 0

#         # Ask model ONLY for the diagnostic text — short and focused
#         async with httpx.AsyncClient(timeout=300.0) as client:

#             # Call 1: diagnostic
#             r1 = await client.post("http://localhost:11434/api/generate", json={
#                 "model": "gemma2:2b",
#                 "prompt": (
#                     f"Capteur {sensor_type} '{sensor_name}'. "
#                     f"Min={min_val} Max={max_val} Moy={avg_val} Seuil={threshold} Depassements={over_threshold}/{len(recent_values)}. "
#                     f"Etat: {'ALERTE CRITIQUE' if is_alert else 'STABLE'}. "
#                     f"Ecris UNE seule phrase de diagnostic technique en francais."
#                 ),
#                 "stream": False,
#                 "options": {"num_predict": 80, "temperature": 0.2}
#             })
#             diagnostic = r1.json()["response"].strip()

#             # Call 2: tendance
#             r2 = await client.post("http://localhost:11434/api/generate", json={
#                 "model": "gemma2:2b",
#                 "prompt": (
#                     f"Capteur {sensor_type} '{sensor_name}'. "
#                     f"Min={min_val} Max={max_val} Moy={avg_val} Seuil={threshold}. "
#                     f"Decris en UNE seule phrase la tendance d evolution des valeurs en francais."
#                 ),
#                 "stream": False,
#                 "options": {"num_predict": 80, "temperature": 0.2}
#             })
#             tendance = r2.json()["response"].strip()

#             # Call 3: recommandation
#            # Call 3: recommandation
#             r3 = await client.post("http://localhost:11434/api/generate", json={
#                 "model": "gemma2:2b",
#                 "prompt": (
#                     f"Donne 3 actions de maintenance pour un capteur {sensor_type} en {'ALERTE' if is_alert else 'surveillance normale'}. "
#                     f"Contexte: {context}. "
#                     f"Reponds uniquement avec:\n"
#                     f"- [action courte 1]\n"
#                     f"- [action courte 2]\n"
#                     f"- [action courte 3]\n"
#                     f"Chaque action maximum 10 mots. Rien d autre."
#                 ),
#                 "stream": False,
#                 "options": {"num_predict": 150, "temperature": 0.1}
#             })
#             recommandation = r3.json()["response"].strip()

#         return (
#             f"1) DIAGNOSTIC:\n{diagnostic}\n\n"
#             f"2) TENDANCE:\n{tendance}\n\n"
#             f"3) RECOMMANDATION:\n{recommandation}"
#         )

#     except Exception as e:
#         print(f"--- ERREUR IA COMPLETE ---: {repr(e)}")
#         return (
#             f"1) DIAGNOSTIC:\nImpossible de contacter Ollama.\n\n"
#             f"2) TENDANCE:\nVerifiez qu Ollama est lance.\n\n"
#             f"3) RECOMMANDATION:\n- Lancer ollama serve\n- Verifier gemma2:2b est installe\n- Relancer uvicorn"
#         )    

async def _analyze_with_ai(points: list[GraphPoint], sensor_name: str, threshold: float) -> str:
    try:
        import httpx
        all_values = [p.y for p in points]
        if not all_values:
            return "1) DIAGNOSTIC: Aucune donnee disponible.\n2) TENDANCE: Aucune donnee.\n3) RECOMMANDATION: Verifier la connexion du capteur."

        # Smart sampling: keep all stats from full dataset, but limit prompt size for 8GB RAM
        # Use representative sample: first + last + evenly spaced points (max 60 values)
        MAX_SAMPLE = 60
        if len(all_values) <= MAX_SAMPLE:
            sampled = all_values
        else:
            step = len(all_values) / MAX_SAMPLE
            sampled = [all_values[int(i * step)] for i in range(MAX_SAMPLE)]

        # Stats always from FULL dataset
        min_val   = round(min(all_values), 2)
        max_val   = round(max(all_values), 2)
        avg_val   = round(sum(all_values) / len(all_values), 2)
        over_threshold = len([v for v in all_values if v >= threshold])
        # Trend from sampled (first third vs last third)
        third = max(1, len(sampled) // 3)
        avg_start = sum(sampled[:third]) / third
        avg_end   = sum(sampled[-third:]) / third
        trend_hint = "montee" if avg_end > avg_start * 1.05 else "descente" if avg_end < avg_start * 0.95 else "stable"
        recent_values = sampled  # used for prompt context
        is_alert  = over_threshold > 0

        code = sensor_name.upper()
        if "TEMP" in code:
            sensor_type = "temperature (C)"
            context     = "surchauffe moteur, panne refroidissement, isolation defectueuse"
            unit        = "°C"
        elif "PRES" in code:
            sensor_type = "pression (bar)"
            context     = "surpression, fuite de circuit, obstruction conduite"
            unit        = "bar"
        elif "HUMI" in code:
            sensor_type = "humidite (%)"
            context     = "condensation, corrosion equipements, infiltration eau"
            unit        = "%"
        elif "CO2" in code:
            sensor_type = "qualite air CO2 (ppm)"
            context     = "ventilation insuffisante, accumulation gaz, danger respiratoire"
            unit        = "ppm"
        else:
            sensor_type = "grandeur industrielle"
            context     = "anomalie capteur, derive mesure, dysfonctionnement equipement"
            unit        = "u"

        status = "ALERTE CRITIQUE" if is_alert else "STABLE"
        base   = f"Capteur {sensor_type} '{sensor_name}'. Min={min_val}{unit} Max={max_val}{unit} Moy={avg_val}{unit} Seuil={threshold}{unit} Depassements={over_threshold}/{len(all_values)} mesures. Tendance={trend_hint}. Etat={status}."

        async with httpx.AsyncClient(timeout=300.0) as client:

            async def ask(prompt: str, tokens: int) -> str:
                r = await client.post("http://localhost:11434/api/generate", json={
                    "model": "gemma2:2b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": tokens, "temperature": 0.1}
                })
                return r.json()["response"].strip()

            # ── 1. Diagnostic global ──────────────────────────────────────────
            diagnostic = await ask(
                f"{base} Ecris UNE phrase de diagnostic technique en francais.",
                80
            )

            # ── 2. Gravite ────────────────────────────────────────────────────
            gravite = await ask(
                f"{base} Evalue la gravite de la situation: Faible, Moderee ou Critique. "
                f"Explique en UNE phrase pourquoi.",
                80
            )

            # ── 3. Tendance ───────────────────────────────────────────────────
            tendance = await ask(
                f"{base} Decris en UNE phrase la tendance d evolution "
                f"(montee, descente, stable, oscillation).",
                80
            )

            # ── 4. Cause probable ─────────────────────────────────────────────
            cause = await ask(
                f"{base} Contexte: {context}. "
                f"Cite la cause industrielle la plus probable en UNE phrase.",
                80
            )

            # ── 5. Actions immediates ─────────────────────────────────────────
            actions = await ask(
                f"Capteur {sensor_type} en {status}. Contexte: {context}. "
                f"Donne 3 actions immediates courtes. Format:\n"
                f"- action 1\n- action 2\n- action 3\n"
                f"Maximum 10 mots par action. Rien d autre.",
                150
            )

            # ── 6. Prevention long terme ──────────────────────────────────────
            prevention = await ask(
                f"Capteur {sensor_type} en {status}. Contexte: {context}. "
                f"Donne 3 mesures preventives long terme. Format:\n"
                f"- mesure 1\n- mesure 2\n- mesure 3\n"
                f"Maximum 10 mots par mesure. Rien d autre.",
                150
            )

        return (
            f"1) DIAGNOSTIC:\n{diagnostic}\n\n"
            f"2) GRAVITE:\n{gravite}\n\n"
            f"3) TENDANCE:\n{tendance}\n\n"
            f"4) CAUSE PROBABLE:\n{cause}\n\n"
            f"5) ACTIONS IMMEDIATES:\n{actions}\n\n"
            f"6) PREVENTION LONG TERME:\n{prevention}"
        )

    except Exception as e:
        print(f"--- ERREUR IA COMPLETE ---: {repr(e)}")
        return (
            f"1) DIAGNOSTIC:\nImpossible de contacter Ollama.\n\n"
            f"2) GRAVITE:\nInconnue.\n\n"
            f"3) TENDANCE:\nVerifiez qu Ollama est lance.\n\n"
            f"4) CAUSE PROBABLE:\nConnexion Ollama impossible.\n\n"
            f"5) ACTIONS IMMEDIATES:\n- Lancer ollama serve\n- Verifier gemma2:2b\n- Relancer uvicorn\n\n"
            f"6) PREVENTION LONG TERME:\n- Configurer Ollama au demarrage\n- Monitorer le service\n- Verifier les logs"
        )

async def _analyze_with_ai_summary(prompt: str) -> str:
    """Generate a short AI summary using the local Ollama model."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post("http://localhost:11434/api/generate", json={
                "model": "gemma2:2b",
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 150, "temperature": 0.3}
            })
            return r.json()["response"].strip()
    except Exception as e:
        print(f"AI summary error: {e}")
        return "Analyse IA non disponible."
    
async def send_pdf_via_email(to_emails: List[str], subject: str, pdf_bytes: bytes, filename: str = "rapport.pdf"):
    """Send a PDF attachment to the given email(s)."""
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = ALERT_EMAIL_SENDER
        msg["To"] = ", ".join(to_emails)   # or use multiple To: fields? Simple comma works for SMTP.
        msg.set_content("Veuillez trouver le rapport ci-joint.")
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                              username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                              use_tls=True, timeout=30)
        print(f"Report sent to {', '.join(to_emails)}")
        return True
    except Exception as e:
        print(f"Failed to send report: {e}")
        return False    

async def generate_master_report_pdf(period: str, start_date: datetime, end_date: datetime, db: Session) -> BytesIO:
    """Generate a PDF report covering all sensors for the given period."""
    # Fetch all active sensors
    sensors = db.query(models.Capteur).filter(models.Capteur.is_activated == True).all()
    if not sensors:
        # Fallback: a simple message
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        doc.build([Paragraph("Aucun capteur actif trouvé.", getSampleStyleSheet()['Normal'])])
        buffer.seek(0)
        return buffer

    # Prepare data for each sensor: min, max, avg, alert count
    sensor_data = []
    for s in sensors:
        measures = db.query(models.Mesure).filter(
            models.Mesure.capteur_id == s.id,
            models.Mesure.time >= start_date,
            models.Mesure.time <= end_date
        ).all()
        if not measures:
            continue
        values = [m.valeur for m in measures]
        alert_count = db.query(models.Alerte).filter(
            models.Alerte.capteur_code == s.code_unique,
            models.Alerte.time >= start_date,
            models.Alerte.time <= end_date
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

    # Get zone stats
    zones = db.query(models.Zone).all()
    zone_stats = []
    for z in zones:
        zone_sensors = [s for s in sensors if s.zone_id == z.id]
        if not zone_sensors:
            continue
        # Compute average of main metric (e.g., temperature, but we'll just use all sensors? For simplicity, we'll average over all sensors in the zone)
        all_vals = []
        for s in zone_sensors:
            measures = db.query(models.Mesure).filter(
                models.Mesure.capteur_id == s.id,
                models.Mesure.time >= start_date,
                models.Mesure.time <= end_date
            ).all()
            all_vals.extend([m.valeur for m in measures])
        zone_avg = sum(all_vals)/len(all_vals) if all_vals else 0
        active_alerts = sum(1 for s in zone_sensors if db.query(models.Alerte).filter(
            models.Alerte.capteur_code == s.code_unique,
            models.Alerte.is_resolved == False
        ).count() > 0)
        zone_stats.append({
            "name": z.nom_zone,
            "sensor_count": len(zone_sensors),
            "avg_value": zone_avg,
            "active_alerts": active_alerts
        })

    # Generate AI summary
    # Build a short prompt from the aggregated data
    total_alerts = sum(s["alert_count"] for s in sensor_data)
    worst_zone = max(zone_stats, key=lambda z: z["active_alerts"]) if zone_stats else None
    prompt = f"""Rapport {period} – Période du {start_date.strftime('%d/%m/%Y')} au {end_date.strftime('%d/%m/%Y')}.

Total capteurs actifs: {len(sensor_data)}
Alertes totales durant la période: {total_alerts}
Zone avec le plus d'alertes actives: {worst_zone['name'] if worst_zone else 'aucune'} ({worst_zone['active_alerts'] if worst_zone else 0} alertes)

Donne un résumé concis (3-4 phrases) en français, évaluant la santé générale du système et une recommandation principale.
"""
    ai_summary = await _analyze_with_ai_summary(prompt)  # we'll define this

    # Build PDF using reportlab
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

    # Header
    elements.append(Paragraph(f"Rapport {period.capitalize()}", title_style))
    elements.append(Paragraph(f"Période: {start_date.strftime('%d/%m/%Y')} – {end_date.strftime('%d/%m/%Y')}", normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Key metrics
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

    # AI Summary
    elements.append(Paragraph("Résumé IA", section_style))
    elements.append(Paragraph(ai_summary, normal_style))
    elements.append(Spacer(1, 0.5*cm))

    # Zone performance
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

    # Top alerts (optional, if any)
    active_alerts = db.query(models.Alerte).filter(models.Alerte.is_resolved == False).limit(5).all()
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
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#fef2f2') if a.valeur >= a.seuil_depasse else colors.HexColor('#f8fafc')),  # simplistic
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        elements.append(alerts_table)
        elements.append(Spacer(1, 0.5*cm))

    # Footer
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph("Document confidentiel – généré automatiquement par Flow · Supervision industrielle Cevital", small_style))

    doc.build(elements)
    buffer.seek(0)
    return buffer

async def _send_report_background(period: str, start_date: datetime, end_date: datetime, recipients: List[str]):
    """Background task to generate PDF and send email."""
    db = SessionLocal()
    try:
        pdf_buffer = await generate_master_report_pdf(period, start_date, end_date, db)
        pdf_bytes = pdf_buffer.getvalue()
        await send_pdf_via_email(recipients, f"Rapport {period} – Cevital", pdf_bytes, f"rapport_{period}_{end_date.strftime('%Y%m%d')}.pdf")
        print(f"Report sent to {', '.join(recipients)}")
    except Exception as e:
        print(f"Failed to send report: {e}")
    finally:
        db.close()    
@app.post("/api/sensors")
def create_sensor(sensor: SensorCreate, db: Session = Depends(get_db)):
    new = models.Capteur(**sensor.dict())
    db.add(new)
    db.commit()
    db.refresh(new)
    return new

@app.patch("/api/sensors/{sensor_id}/activate")
def toggle_sensor(
    sensor_id: int,
    payload: TogglePayload | None = Body(None),
    activate: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    sensor = db.query(models.Capteur).get(sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Capteur non trouvé")
    if payload is not None:
        sensor.is_activated = payload.activate
    elif activate is not None:
        sensor.is_activated = activate
    else:
        raise HTTPException(status_code=400, detail="Paramètre `activate` requis")
    db.commit()
    return {"success": True, "is_activated": sensor.is_activated}

@app.put("/api/sensors/{sensor_id}")
def update_sensor(sensor_id: int, sensor: SensorCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Capteur).filter(models.Capteur.id == sensor_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Capteur non trouve")
    existing.code_unique   = sensor.code_unique
    existing.type_grandeur = sensor.type_grandeur
    existing.unite         = sensor.unite
    existing.adresse_ip    = sensor.adresse_ip
    db.commit()
    db.refresh(existing)
    return existing    



async def send_scheduled_report(period: str):
    """Internal function to generate and send a scheduled report."""
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
        await send_pdf_via_email(
            recipients,
            f"Rapport {period.capitalize()} – Cevital",
            pdf_bytes,
            f"rapport_{period}_{end_date.strftime('%Y%m%d')}.pdf"
        )
        print(f"Scheduled {period} report sent.")
    except Exception as e:
        print(f"Failed to send scheduled {period} report: {e}")
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)
    asyncio.create_task(log_and_cache_forever())

    # Set up scheduler
    scheduler = AsyncIOScheduler()

    # Daily report at 8:00 AM (server time)
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("daily")),
        CronTrigger(hour=8, minute=0)
    )
    # Weekly report every Monday at 8:00 AM
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("weekly")),
        CronTrigger(day_of_week='mon', hour=8, minute=0)
    )
    # Monthly report on the 1st at 8:00 AM
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("monthly")),
        CronTrigger(day=1, hour=8, minute=0)
    )

    scheduler.start()
    app.state.scheduler = scheduler


@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, 'scheduler'):
        app.state.scheduler.shutdown()

# --- GENERATE REPORT (FIXED TEXT WRAPPING) ---
import io
@app.post("/generate-report")
async def generate_report(req: ReportRequest):
    analysis = await _analyze_with_ai(req.data, req.sensor_name, req.threshold)

    import io, os, re
    from datetime import datetime as _dt_now
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
        Table, TableStyle, Image as RLImage
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
        """Render bullet list items in a styled box."""
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

    def section_box(label, content_para, bg, border_col, icon=""):
        rows = [[Paragraph(f"{icon} {label}" if icon else label, section_s), content_para]]
        t = Table(rows, colWidths=[16*cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), bg),
            ('BOX', (0,0), (-1,-1), 1, border_col),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
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
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cevital.jpg')
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
@app.get("/api/live-stream")

async def get_live_stream():
    return {tag: list(points) for tag, points in live_cache.items()}

@app.get("/api/last-two")
async def get_last_two():
    return last_two

@app.get("/api/last-two/{code_unique}")
async def get_last_two_for_sensor(code_unique: str):
    return {code_unique: last_two.get(code_unique, [])}

@app.get("/api/sensors")
def get_sensors_list(db: Session = Depends(get_db)):
    return db.query(models.Capteur).filter(models.Capteur.is_activated == True).all()

def _lttb_downsample(points: list[dict], threshold: int) -> list[dict]:
    if threshold >= len(points) or threshold < 3:
        return points
    data = [{'x': p['time'].timestamp(), 'y': p['valeur']} for p in points]
    sampled = [points[0]]
    bucket_size = (len(data) - 2) / (threshold - 2)
    a = 0
    for i in range(0, threshold - 2):
        start = int(math.floor((i + 1) * bucket_size)) + 1
        end = int(math.floor((i + 2) * bucket_size)) + 1
        if end >= len(data): end = len(data) - 1
        count = end - start
        if count <= 0: count = 1
        avg_x = sum(d['x'] for d in data[start:end]) / count
        avg_y = sum(d['y'] for d in data[start:end]) / count
        max_area = -1
        next_idx = start
        for j in range(start, end):
            area = abs((data[a]['x'] - avg_x) * (data[j]['y'] - data[a]['y']) - (data[a]['x'] - data[j]['x']) * (avg_y - data[a]['y']))
            if area > max_area:
                max_area = area
                next_idx = j
        sampled.append(points[next_idx])
        a = next_idx
    sampled.append(points[-1])
    return sampled

@app.get("/api/history/{capteur_id}")
def get_long_history(capteur_id: int, hours: float | None = None, start: str | None = None, end: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(models.Mesure).filter(models.Mesure.capteur_id == capteur_id)
    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt   = datetime.fromisoformat(end)
            query = query.filter(models.Mesure.time >= start_dt, models.Mesure.time <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide.")
    elif hours is not None and hours > 0:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(models.Mesure.time >= cutoff)
    history = query.order_by(models.Mesure.time.asc()).all()
    result = [{"time": m.time, "valeur": m.valeur} for m in history]
    if len(result) > limit:
        result = _lttb_downsample(result, limit)
    return result

@app.get("/api/zones")
def get_zones(db: Session = Depends(get_db)):
    try:
        zones = db.query(models.Zone).all()
        result = [{"id": z.id, "nom_zone": z.nom_zone, "code_zone": z.code_zone} for z in zones]
        return result
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/sensors/zone/{zone_id}")
def get_sensors_by_zone(zone_id: int, db: Session = Depends(get_db)):
    sensors = db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).all()
    return sensors if sensors else []


class AlertTrigger(BaseModel):
    capteur_code: str
    valeur: float
    seuil_depasse: float
    message: str

    class Config:
        from_attributes = True

# --- 2. La Route POST pour enregistrer l'alerte ---
@app.post("/api/alerts/trigger")
async def trigger_alert(alert_data: AlertTrigger, db: Session = Depends(get_db)):
    try:
        # On utilise models.Alerte (ton modèle de base de données)
        new_alert = models.Alerte(
            capteur_code=alert_data.capteur_code,
            valeur=alert_data.valeur,
            seuil_depasse=alert_data.seuil_depasse,
            message=alert_data.message,
            time=datetime.utcnow(),
            is_resolved=False
        )
        
        db.add(new_alert)
        db.commit()
        db.refresh(new_alert)
        
        return {"status": "success", "id": new_alert.id}
        
    except Exception as e:
        db.rollback()
        print(f"Erreur BDD : {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/api/alerts")
async def get_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alerte).order_by(Alerte.time.desc()).limit(100).all()
    return [
        {
            "id": a.id,
            "code": a.capteur_code,
            "time": a.time.strftime("%d/%m %H:%M:%S"),
            "value": a.valeur,
            "seuil": a.seuil_depasse,
            "msg": a.message,
            "is_resolved": a.is_resolved
        } for a in alerts
    ]

@app.patch("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    alert.is_resolved = True
    db.commit()
    return {"success": True}

@app.patch("/api/alerts/{alert_id}/ignore")
def ignore_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    db.delete(alert)
    db.commit()
    return {"success": True}

@app.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    db.delete(alert)
    db.commit()
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


@app.post("/api/reports/send")
async def send_report(req: MasterReportRequest, db: Session = Depends(get_db)):
    """Generate and send a report for the given period (or custom dates)."""
    # Determine date range
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

    # Get recipient emails: either from request or from environment (fallback)
    recipients = req.recipients if req.recipients else [os.getenv("MANAGER_EMAIL", "manager@cevital.dz")]

    # Launch background task – response is immediate
    asyncio.create_task(_send_report_background(req.period or "custom", start_date, end_date, recipients))

    return {"success": True, "message": "La génération du rapport a commencé. Vous recevrez l'email sous peu."}
# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class UserPublic(BaseModel):
    id: int
    username: str
    role: str
    class Config:
        from_attributes = True

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserPublic:
    credentials_exc = HTTPException(
        status_code=401, detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exc
    username: str = payload.get("sub")
    if not username:
        raise credentials_exc
    user = db.query(Utilisateur).filter(Utilisateur.username == username).first()
    if not user:
        raise credentials_exc
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return UserPublic(id=user.id, username=user.username, role=role.nom if role else "unknown")

@app.post("/auth/login", response_model=TokenResponse, tags=["auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Utilisateur).filter(Utilisateur.username == form_data.username).first()
    dummy_hash = "$2b$12$notarealhashjustfortimingat0"
    valid = verify_password(form_data.password, user.password_hash if user else dummy_hash)
    if not user or not valid:
        raise HTTPException(status_code=401, detail="Nom d'utilisateur ou mot de passe incorrect", headers={"WWW-Authenticate": "Bearer"})
    role = db.query(Role).filter(Role.id == user.role_id).first()
    token = create_access_token({"sub": user.username, "user_id": user.id, "role": role.nom if role else "unknown"})
    return {"access_token": token, "token_type": "bearer"}

@app.get("/auth/me", response_model=UserPublic, tags=["auth"])
def read_me(current_user: UserPublic = Depends(get_current_user)):
    return current_user

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

@app.patch("/auth/change-password", tags=["auth"])
def change_password(
    payload: ChangePasswordRequest,
    current_user: UserPublic = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user = db.query(Utilisateur).filter(Utilisateur.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le mot de passe doit faire au moins 6 caracteres")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"success": True}


# =============================================================================
# USER MANAGEMENT ROUTES  (admin only)
# =============================================================================

def require_admin(current_user: UserPublic = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acces reserve aux administrateurs")
    return current_user

def generate_temp_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))

class UserCreate_Admin(BaseModel):
    username: str
    email:    str
    role:     str

class UserUpdate_Admin(BaseModel):
    email:    Optional[str] = None
    role:     Optional[str] = None
    username: Optional[str] = None

class UserOut(BaseModel):
    id:       int
    username: str
    email:    Optional[str]
    role:     str
    class Config:
        from_attributes = True

@app.get("/admin/users", response_model=list[UserOut], tags=["admin"])
def list_users(db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    users = db.query(Utilisateur).all()
    result = []
    for u in users:
        role = db.query(Role).filter(Role.id == u.role_id).first()
        result.append(UserOut(id=u.id, username=u.username, email=u.email, role=role.nom if role else "unknown"))
    return result

@app.post("/admin/users", response_model=UserOut, tags=["admin"])
async def create_user(payload: UserCreate_Admin, db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    if db.query(Utilisateur).filter(Utilisateur.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Ce nom d'utilisateur existe deja")
    if db.query(Utilisateur).filter(Utilisateur.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Cet email est deja utilise")
    role = db.query(Role).filter(Role.nom == payload.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role inconnu : {payload.role}")
    temp_password = generate_temp_password()
    new_user = Utilisateur(
        username=payload.username, email=payload.email,
        password_hash=hash_password(temp_password), role_id=role.id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    await _send_credentials_email(payload.email, payload.username, temp_password, payload.role)
    return UserOut(id=new_user.id, username=new_user.username, email=new_user.email, role=role.nom)

@app.patch("/admin/users/{user_id}", response_model=UserOut, tags=["admin"])
async def update_user(user_id: int, payload: UserUpdate_Admin, db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if payload.username: user.username = payload.username
    if payload.email:    user.email    = payload.email
    if payload.role:
        role = db.query(Role).filter(Role.nom == payload.role).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"Role inconnu : {payload.role}")
        user.role_id = role.id
    db.commit()
    db.refresh(user)
    role_obj = db.query(Role).filter(Role.id == user.role_id).first()
    if user.email:
        await _send_update_email(user.email, user.username, role_obj.nom if role_obj else "unknown")
    return UserOut(id=user.id, username=user.username, email=user.email, role=role_obj.nom if role_obj else "unknown")

@app.delete("/admin/users/{user_id}", tags=["admin"])
def delete_user(user_id: int, db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    db.delete(user)
    db.commit()
    return {"success": True, "deleted_id": user_id}

async def _send_credentials_email(to_email: str, username: str, password: str, role: str):
    msg = EmailMessage()
    msg["Subject"] = "Vos acces Flow - Systeme de supervision industrielle"
    msg["From"]    = ALERT_EMAIL_SENDER
    msg["To"]      = to_email
    msg.set_content(
        f"Bonjour {username},\n\n"
        f"Un compte a ete cree pour vous sur la plateforme Flow.\n\n"
        f"  Nom d'utilisateur : {username}\n"
        f"  Mot de passe temporaire : {password}\n"
        f"  Role : {role}\n\n"
        f"Cordialement,\nL'equipe Flow"
    )
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD, use_tls=True, timeout=10)
        print(f"Credentials envoyes a {to_email}")
    except Exception as e:
        print(f"Email non envoye : {e}")

async def _send_update_email(to_email: str, username: str, role: str):
    msg = EmailMessage()
    msg["Subject"] = "Votre compte Flow a ete mis a jour"
    msg["From"]    = ALERT_EMAIL_SENDER
    msg["To"]      = to_email
    msg.set_content(
        f"Bonjour {username},\n\n"
        f"Votre compte a ete modifie.\n"
        f"  Nom d'utilisateur : {username}\n"
        f"  Role : {role}\n\n"
        f"Cordialement,\nL'equipe Flow"
    )
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD, use_tls=True, timeout=10)
    except Exception as e:
        print(f"Email non envoye : {e}")



class EmailReportRequest(BaseModel):
  to_email:     str
  sensor_name:  str
  pdf_base64:   str
  chart_base64: Optional[str] = None
@app.post("/send-report-email")
async def send_report_email(req: EmailReportRequest):
    import base64
    try:
        pdf_bytes = base64.b64decode(req.pdf_base64)

        msg = EmailMessage()
        msg["Subject"] = f"Rapport d'Analyse IA — Capteur {req.sensor_name}"
        msg["From"]    = ALERT_EMAIL_SENDER
        msg["To"]      = req.to_email
        msg.set_content(
            f"Bonjour,\n\n"
            f"Veuillez trouver en pièce jointe :\n"
            f"  - Le rapport d'analyse IA (PDF)\n"
            f"  - Le graphique du capteur {req.sensor_name} (PNG)\n\n"
            f"Cordialement,\nSystème de Monitoring Flow — Cevital"
        )

        # Attach PDF
        msg.add_attachment(
            pdf_bytes,
            maintype="application",
            subtype="pdf",
            filename=f"Rapport_IA_{req.sensor_name}.pdf"
        )

        # Attach chart image if provided
        if req.chart_base64:
            chart_bytes = base64.b64decode(req.chart_base64)
            msg.add_attachment(
                chart_bytes,
                maintype="image",
                subtype="png",
                filename=f"Graphique_{req.sensor_name}.png"
            )

        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=465,
            username=ALERT_EMAIL_SENDER,
            password=ALERT_EMAIL_PASSWORD,
            use_tls=True,
            timeout=30,
        )
        return {"success": True}
    except Exception as e:
        print(f"Erreur envoi rapport : {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/zones/{zone_id}/stats")
def get_zone_stats(zone_id: int, db: Session = Depends(get_db)):
    """Get statistics for a specific zone: sensor count, active alerts, etc."""
    
    # Get sensors in this zone
    sensors = db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).all()
    sensor_count = len(sensors)
    
    # Get active alerts for sensors in this zone
    sensor_codes = [s.code_unique for s in sensors]
    active_alerts = db.query(models.Alerte).filter(
        models.Alerte.capteur_code.in_(sensor_codes),
        models.Alerte.is_resolved == False
    ).count()
    
    # Get latest values for each sensor (if you want to show current status)
    latest_values = {}
    for sensor in sensors:
        last_measure = db.query(models.Mesure).filter(
            models.Mesure.capteur_id == sensor.id
        ).order_by(models.Mesure.time.desc()).first()
        if last_measure:
            latest_values[sensor.code_unique] = last_measure.valeur
    
    return {
        "zone_id": zone_id,
        "sensor_count": sensor_count,
        "active_alerts": active_alerts,
        "sensors": [{"code": s.code_unique, "type": s.type_grandeur} for s in sensors],
        "latest_values": latest_values
    }       

# =============================================================================
# ZONE MANAGEMENT ENDPOINTS (Enhanced)
# =============================================================================

@app.get("/api/zones")
def get_zones(db: Session = Depends(get_db)):
    """Get all zones with their positions and types"""
    try:
        zones = db.query(models.Zone).all()
        result = [{
            "id": z.id, 
            "nom_zone": z.nom_zone, 
            "code_zone": z.code_zone,
            "type": getattr(z, 'type', 'Process'),
            "x": getattr(z, 'x', 100),
            "y": getattr(z, 'y', 100),
            "w": getattr(z, 'w', 120),
            "h": getattr(z, 'h', 100)
        } for z in zones]
        return result
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/zones/{zone_id}/stats")
def get_zone_stats(zone_id: int, db: Session = Depends(get_db)):
    """Get statistics for a specific zone: sensor count, active alerts, etc."""
    
    # Get the zone
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    
    # Get sensors in this zone
    sensors = db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).all()
    sensor_count = len(sensors)
    
    # Get active alerts for sensors in this zone
    sensor_codes = [s.code_unique for s in sensors]
    active_alerts = 0
    if sensor_codes:
        active_alerts = db.query(models.Alerte).filter(
            models.Alerte.capteur_code.in_(sensor_codes),
            models.Alerte.is_resolved == False
        ).count()
    
    # Get latest values for each sensor
    latest_values = {}
    sensors_list = []
    for sensor in sensors:
        sensors_list.append({
            "code": sensor.code_unique,
            "type": sensor.type_grandeur,
            "unit": sensor.unite,
            "is_activated": sensor.is_activated
        })
        
        last_measure = db.query(models.Mesure).filter(
            models.Mesure.capteur_id == sensor.id
        ).order_by(models.Mesure.time.desc()).first()
        if last_measure:
            latest_values[sensor.code_unique] = last_measure.valeur
    
    return {
        "zone_id": zone_id,
        "zone_name": zone.nom_zone,
        "sensor_count": sensor_count,
        "active_alerts": active_alerts,
        "sensors": sensors_list,
        "latest_values": latest_values
    }

@app.post("/api/zones")
def create_zone(zone: ZoneCreate, db: Session = Depends(get_db)):
    """Create a new zone with position and type"""
    # Check if code_zone already exists
    existing = db.query(models.Zone).filter(models.Zone.code_zone == zone.code_zone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce code de zone existe déjà")
    
    new_zone = models.Zone(
        nom_zone=zone.nom_zone,
        code_zone=zone.code_zone,
        type=zone.type,
        x=zone.x,
        y=zone.y,
        w=zone.w,
        h=zone.h
    )
    db.add(new_zone)
    db.commit()
    db.refresh(new_zone)
    return {
        "id": new_zone.id,
        "nom_zone": new_zone.nom_zone,
        "code_zone": new_zone.code_zone,
        "type": new_zone.type,
        "x": new_zone.x,
        "y": new_zone.y,
        "w": new_zone.w,
        "h": new_zone.h
    }

@app.put("/api/zones/{zone_id}")
def update_zone(zone_id: int, zone: ZoneUpdate, db: Session = Depends(get_db)):
    """Update zone position, size, name, or type"""
    existing = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    
    # Update only the fields that are provided
    update_data = zone.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    db.commit()
    db.refresh(existing)
    return {
        "id": existing.id,
        "nom_zone": existing.nom_zone,
        "code_zone": existing.code_zone,
        "type": existing.type,
        "x": existing.x,
        "y": existing.y,
        "w": existing.w,
        "h": existing.h
    }

@app.delete("/api/zones/{zone_id}")
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    """Delete a zone and move its sensors to the first available zone"""
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    
    # Find another zone to move sensors to
    other_zone = db.query(models.Zone).filter(models.Zone.id != zone_id).first()
    
    if other_zone:
        # Move sensors to the other zone
        db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).update(
            {"zone_id": other_zone.id}
        )
    else:
        # If this is the last zone, just set zone_id to NULL
        db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).update(
            {"zone_id": None}
        )
    
    db.delete(zone)
    db.commit()
    return {"success": True, "message": f"Zone '{zone.nom_zone}' supprimée"}

# Optional: Get zone by ID with full details
@app.get("/api/zones/{zone_id}")
def get_zone_by_id(zone_id: int, db: Session = Depends(get_db)):
    """Get a single zone by ID with all its details"""
    zone = db.query(models.Zone).filter(models.Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    
    # Get sensors in this zone
    sensors = db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).all()
    
    return {
        "id": zone.id,
        "nom_zone": zone.nom_zone,
        "code_zone": zone.code_zone,
        "type": getattr(zone, 'type', 'Process'),
        "x": getattr(zone, 'x', 100),
        "y": getattr(zone, 'y', 100),
        "w": getattr(zone, 'w', 120),
        "h": getattr(zone, 'h', 100),
        "sensors": [{
            "id": s.id,
            "code": s.code_unique,
            "type": s.type_grandeur,
            "unit": s.unite,
            "is_activated": s.is_activated
        } for s in sensors]
    }


# Analytics models
class TimeSeriesRequest(BaseModel):
    category: str          # "Température", "Pression", "Humidité", "Qualité Air"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    hours: Optional[float] = None
    interval: str = "hour"  # "hour", "day", "minute"

# =============================================================================
# ANALYTICS ENDPOINTS
# =============================================================================

class TimeSeriesRequest(BaseModel):
    category: str
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    hours: Optional[float] = None
    interval: str = "hour"
    zone_id: Optional[int] = None   

@app.post("/api/analytics/timeseries")
def get_timeseries_data(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    """
    Returns aggregated time series for a given sensor category,
    optionally filtered by zone.
    """
    # Determine time range
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")

    # Determine interval truncation
    trunc_map = {
        "minute": "minute",
        "hour": "hour",
        "day": "day"
    }
    trunc = trunc_map.get(req.interval, "hour")

    # Base query
    query = db.query(
        func.date_trunc(trunc, models.Mesure.time).label("bucket"),
        func.avg(models.Mesure.valeur).label("avg_value"),
        func.min(models.Mesure.valeur).label("min_value"),
        func.max(models.Mesure.valeur).label("max_value"),
        func.count(models.Mesure.valeur).label("count")
    ).join(
        models.Capteur, models.Mesure.capteur_id == models.Capteur.id
    ).filter(
        models.Capteur.type_grandeur == req.category,
        models.Mesure.time >= start_dt,
        models.Mesure.time <= end_dt
    )

    # Apply zone filter if provided
    if req.zone_id is not None:
        query = query.filter(models.Capteur.zone_id == req.zone_id)

    results = query.group_by("bucket").order_by("bucket").all()

    return [
        {
            "timestamp": r.bucket,
            "avg_value": r.avg_value,
            "min_value": r.min_value,
            "max_value": r.max_value,
            "count": r.count
        }
        for r in results
    ]

@app.post("/api/analytics/zone-comparison")
def get_zone_comparison(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    """Returns average value per zone for a given sensor category over the time range."""
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")

    results = db.query(
        models.Zone.id.label("zone_id"),
        models.Zone.nom_zone.label("zone_name"),
        func.avg(models.Mesure.valeur).label("avg_value"),
        func.count(func.distinct(models.Capteur.id)).label("sensor_count")
    ).join(
        models.Capteur, models.Capteur.zone_id == models.Zone.id
    ).join(
        models.Mesure, models.Mesure.capteur_id == models.Capteur.id
    ).filter(
        models.Capteur.type_grandeur == req.category,
        models.Mesure.time >= start_dt,
        models.Mesure.time <= end_dt
    ).group_by(
        models.Zone.id, models.Zone.nom_zone
    ).order_by(
        models.Zone.nom_zone
    ).all()

    return [
        {
            "zone_id": r.zone_id,
            "zone_name": r.zone_name,
            "avg_value": r.avg_value,
            "sensor_count": r.sensor_count
        }
        for r in results
    ]