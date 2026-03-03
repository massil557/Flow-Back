

import asyncio
from datetime import datetime, timedelta
from collections import deque
import math

from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from asyncua import Client
from datetime import datetime
from pydantic import BaseModel
# --- GOOGLE AI IMPORT ---
import google.generativeai as genai

# Importation de tes fichiers locaux
from database import SessionLocal, engine, Base
import models
from models import Alerte, Utilisateur, Role

# ── Auth imports ──────────────────────────────────────────────────────────────
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from auth import hash_password, verify_password, create_access_token, decode_access_token

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

GEMINI_API_KEY = "AIzaSyAgdFpRoye9mD4HccM-r9TxxBm4Ggz9hU8"
genai.configure(api_key=GEMINI_API_KEY)

ai_model = genai.GenerativeModel('gemini-1.5-flash-latest')

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

DANGER_THRESHOLD = 30

import os
from email.message import EmailMessage
import aiosmtplib

ALERT_EMAIL_SENDER = "mascioul8@gmail.com"
ALERT_EMAIL_PASSWORD = "qlwuhufccwuyyuga"
ALERT_EMAIL_RECIPIENT = "ademoulhaci123@gmail.com"


# helper asynchrone pour envoyer le mail d'alerte
async def send_alert_email(sensor_code: str, value: float, timestamp: str, message: str):
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return

    msg = EmailMessage()
    msg["Subject"] = f"ALERTE : {sensor_code} ({value})"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ALERT_EMAIL_RECIPIENT
    msg.set_content(f"Capteur: {sensor_code}\nValeur: {value}\nTemps: {timestamp}\n{message}")

    try:
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=465,
            username=ALERT_EMAIL_SENDER,
            password=ALERT_EMAIL_PASSWORD,
            use_tls=True, # SSL direct
            timeout=10
        )
        print(f"Mail envoyé avec succès pour {sensor_code}")
    except Exception as exc:
        print(f"Erreur mail : {exc}")
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

                        if val >= DANGER_THRESHOLD:
                            prev_vals = last_two.get(s.code_unique, [])
                            prev_val = prev_vals[-2] if len(prev_vals) > 1 else None
                            if prev_val is None or prev_val < DANGER_THRESHOLD:
                                alert_msg = f"Valeur {val} >= seuil {DANGER_THRESHOLD}"
                                alert = {
                                    "code": s.code_unique,
                                    "value": val,
                                    "time": current_time,
                                    "msg": alert_msg,
                                }
                                alerts.append(alert)
                                print(f"[ALERTE] ajoutée {alert}")
                                asyncio.create_task(send_alert_email(s.code_unique, val, current_time, alert_msg))

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


async def _analyze_with_ai(points: list[GraphPoint], sensor_name: str, threshold: float) -> str:
    try:
        recent_values = [p.y for p in points[-30:]]
        if not recent_values:
            return "Aucune donnée disponible pour l'analyse."

        # Le prompt professionnel avec seuil dynamique
        prompt = (
            f"Expert IoT: Analyse {sensor_name} (valeurs: {recent_values}). "
            f"Seuil critique: {threshold}. "
            f"Donne un DIAGNOSTIC (Stable/Alerte), la Tendance en 1 phrase et une RECOMMANDATION technique."
        )

        # 2. Découverte dynamique du modèle (pour éviter les erreurs 404)
        def get_available_analysis():
            available_models = [m.name for m in genai.list_models() 
                               if 'generateContent' in m.supported_generation_methods]
            
            if not available_models:
                raise Exception("Aucun modèle trouvé pour cette clé API.")
            
            # Priorité au modèle Flash
            selected_model = next((m for m in available_models if "flash" in m), available_models[0])
            
            print(f"[IA] Analyse dynamique avec : {selected_model} (Seuil: {threshold})")
            model_instance = genai.GenerativeModel(selected_model)
            return model_instance.generate_content(prompt)

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, get_available_analysis)
        
        return response.text.strip()

    except Exception as e:
        print(f"--- ERREUR IA ---: {e}")
        return f"Analyse indisponible (Erreur: {str(e)[:30]}...)"
    
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

@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)
    asyncio.create_task(log_and_cache_forever())

# --- GENERATE REPORT (FIXED TEXT WRAPPING) ---
import io
@app.post("/generate-report")
async def generate_report(req: ReportRequest):
    analysis = await _analyze_with_ai(req.data, req.sensor_name, req.threshold)
    
    import io
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    import textwrap

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # --- ENTÊTE ---
    p.setStrokeColor(colors.dodgerblue)
    p.setLineWidth(2)
    p.line(50, height - 50, width - 50, height - 50)
    
    p.setFont("Helvetica-Bold", 18)
    p.setFillColor(colors.dodgerblue)
    p.drawString(50, height - 80, "RAPPORT D'ANALYSE TECHNIQUE")
    
    p.setFont("Helvetica", 10)
    p.setFillColor(colors.black)
    p.drawString(50, height - 100, f"Capteur : {req.sensor_name}")
    p.drawString(50, height - 115, f"Seuil de référence : {req.threshold}")

    # --- SECTION ANALYSE IA ---
    p.setFont("Helvetica-Bold", 13)
    p.drawString(50, height - 160, "RÉSULTATS DE L'ANALYSE IA")
    p.line(50, height - 165, width - 50, height - 165)

    text_obj = p.beginText(50, height - 185)
    text_obj.setFont("Helvetica", 11)
    text_obj.setLeading(14)
    
    lines = textwrap.wrap(analysis, width=80)
    for line in lines:
        text_obj.textLine(line)
    p.drawText(text_obj)

    p.showPage()
    p.save()
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

@app.get("/api/alerts")
async def get_alerts():
    return list(alerts)

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
def get_long_history(capteur_id: int, hours: float | None = None, limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(models.Mesure).filter(models.Mesure.capteur_id == capteur_id)
    if hours is not None and hours > 0:
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
    alerts = db.query(Alerte).order_by(Alerte.time.desc()).limit(50).all()
    return [
        {
            "id": a.id,
            "code": a.capteur_code,
            "time": a.time.strftime("%H:%M:%S"),
            "value": a.valeur,
            "msg": a.message,
            "is_resolved": a.is_resolved
        } for a in alerts
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

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
