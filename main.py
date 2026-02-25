import asyncio
from datetime import datetime, timedelta
from collections import deque
import math

from fastapi import FastAPI, Depends, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from asyncua import Client

# Importation de tes fichiers locaux
# Assure-toi que database.py et models.py sont dans le même dossier
from database import SessionLocal, engine, Base
import models

# --- INITIALISATION ---
app = FastAPI(title="Industrial IoT Gateway - Master 2")

# FIX CORS : On liste explicitement les origines pour éviter les blocages navigateurs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# dependency for database sessions
def get_db():
    """Yields a SQLAlchemy session and ensures it's closed after use."""
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

# seuil critique global
DANGER_THRESHOLD = 80.0

# informations d'envoi d'email
import os
from email.message import EmailMessage
import aiosmtplib

ALERT_EMAIL_SENDER = "mascioul8@gmail.com"
ALERT_EMAIL_PASSWORD = "qlwuhufccwuyyuga"
ALERT_EMAIL_RECIPIENT = "ademoulhaci123@gmail.com"

# helper asynchrone pour envoyer le mail d'alerte
async def send_alert_email(sensor_code: str, value: float, timestamp: str, message: str):
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        print("[ALERTE EMAIL] pas de sender/password configurés, envoi ignoré")
        return
    print(f"[ALERTE EMAIL] envoi à {ALERT_EMAIL_RECIPIENT} pour {sensor_code}={value}")
    msg = EmailMessage()
    msg["Subject"] = f"[ALERTE] {sensor_code} valeur critique {value}"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ALERT_EMAIL_RECIPIENT
    msg.set_content(
        f"Capteur {sensor_code} a atteint une valeur dangereuse ({value})\n"
        f"à {timestamp}.\n\n"
        f"Message : {message}"
    )
    try:
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=587,
            start_tls=True,
            username=ALERT_EMAIL_SENDER,
            password=ALERT_EMAIL_PASSWORD,
        )
        print("[ALERTE EMAIL] envoi réussi")
    except Exception as exc:
        print(f"Échec envoi mail d'alerte : {exc}")


# tâche de fond principale
async def log_and_cache_forever():
    """ Tâche de fond qui lit OPC UA, écrit en BDD et met à jour la RAM """
    global live_cache

    while True:
        db = SessionLocal()
        try:
            async with Client(url=OPC_URL) as client:
                # 1. On récupère les capteurs configurés en BDD
                sensors = db.query(models.Capteur).all()

                if not sensors:
                    print("⚠️ Aucun capteur trouvé en BDD. Lance seed_db.py.")

                for s in sensors:
                    if not s.is_activated:
                        continue
                    try:
                        # 2. Lecture de la valeur sur le serveur OPC UA
                        path = ["0:Objects", "2:Machine_Alpha", f"2:{s.code_unique}"]
                        node = await client.nodes.root.get_child(path)
                        val_brute = await node.read_value()
                        val = round(float(val_brute), 2)
                        current_time = datetime.now().strftime("%H:%M:%S")

                        # 3. MISE À JOUR DU CACHE (RAM) - Les 20 dernières valeurs
                        if s.code_unique not in live_cache:
                            live_cache[s.code_unique] = deque(maxlen=20)
                        live_cache[s.code_unique].append({"v": val, "t": current_time})

                        # 3.5 MISE À JOUR DU CACHE (RAM) - Les 2 dernières valeurs
                        if s.code_unique not in last_two:
                            last_two[s.code_unique] = []
                        last_two[s.code_unique].append(val)
                        if len(last_two[s.code_unique]) > 2:
                            last_two[s.code_unique].pop(0)

                        # 3.6 génération d'alerte si valeur dangereuse
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

                        # 3.7 Écriture dans la base de données PostgreSQL
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
            print(f"❌ Erreur de connexion OPC UA : {e}")
        finally:
            db.close()
        await asyncio.sleep(1)


# --- API UTILITAIRES ---

from pydantic import BaseModel

class SensorCreate(BaseModel):
    code_unique: str
    type_grandeur: str
    unite: str
    adresse_ip: str
    zone_id: int

class TogglePayload(BaseModel):
    activate: bool

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

# --- ÉVÉNEMENTS STARTUP ---

@app.on_event("startup")
async def startup_event():
    models.Base.metadata.create_all(bind=engine)
    asyncio.create_task(log_and_cache_forever())

# --- ROUTES API ---

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

# FIX : Ajout d'une sécurité count > 0 pour éviter ZeroDivisionError (Erreur 500)
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
        if end >= len(data):
            end = len(data) - 1

        count = end - start
        if count <= 0: count = 1 # Sécurité anti-crash

        avg_x = sum(d['x'] for d in data[start:end]) / count
        avg_y = sum(d['y'] for d in data[start:end]) / count

        max_area = -1
        next_idx = start
        for j in range(start, end):
            area = abs(
                (data[a]['x'] - avg_x) * (data[j]['y'] - data[a]['y'])
                - (data[a]['x'] - data[j]['x']) * (avg_y - data[a]['y'])
            )
            if area > max_area:
                max_area = area
                next_idx = j
        sampled.append(points[next_idx])
        a = next_idx

    sampled.append(points[-1])
    return sampled


@app.get("/api/history/{capteur_id}")
def get_long_history(
    capteur_id: int,
    hours: float | None = None,
    limit: int = 200,
    db: Session = Depends(get_db)
):
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
        result = []
        for z in zones:
            result.append({
                "id": z.id,
                "nom_zone": z.nom_zone,
                "code_zone": z.code_zone
            })
        return result
    except Exception as e:
        print(f"Erreur SQL : {e}")
        return {"error": str(e)}

@app.get("/api/sensors/zone/{zone_id}")
def get_sensors_by_zone(zone_id: int, db: Session = Depends(get_db)):
    sensors = db.query(models.Capteur).filter(models.Capteur.zone_id == zone_id).all()
    if not sensors:
        return []
    return sensors


if __name__ == "__main__":
    import uvicorn
    import socket

    host = os.getenv("FASTAPI_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("FASTAPI_PORT", "8000"))
    except ValueError:
        port = 8000

    try:
        uvicorn.run(app, host=host, port=port)
    except OSError as exc:
        if "10013" in str(exc):
            print(f"ERROR: cannot bind to {host}:{port}. Port déjà utilisé.")
        else:
            raise