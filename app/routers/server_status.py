"""
app/routers/server_status.py
─────────────────────────────
Route GET /api/server-status
Retourne : CPU, RAM, disque, uptime, connexion DB, statut Ollama,
           compteurs capteurs / mesures / alertes actives.
Nécessite : pip install psutil
"""

import time
import os
import httpx
import psutil
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text, func

from app.database import get_db, engine
from app.models import Capteur, Mesure, Alerte

router = APIRouter(prefix="/api/server-status", tags=["Server Status"])

# Heure de démarrage du processus (uptime)
_START_TIME = time.time()


def _fmt_uptime(seconds: float) -> str:
    td = timedelta(seconds=int(seconds))
    days    = td.days
    hours   = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    if days:
        return f"{days}j {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@router.get("")
async def get_server_status(db: Session = Depends(get_db)):

    # ── CPU ──────────────────────────────────────────────────────────────────
    cpu_percent = psutil.cpu_percent(interval=0.2)
    cpu_count   = psutil.cpu_count(logical=True)
    cpu_freq    = psutil.cpu_freq()
    cpu_freq_mhz = round(cpu_freq.current) if cpu_freq else None

    # ── RAM ──────────────────────────────────────────────────────────────────
    mem = psutil.virtual_memory()
    ram_total_gb  = round(mem.total  / (1024 ** 3), 1)
    ram_used_gb   = round(mem.used   / (1024 ** 3), 1)
    ram_percent   = mem.percent

    # ── Disque ───────────────────────────────────────────────────────────────
    disk = psutil.disk_usage('/')
    disk_total_gb = round(disk.total / (1024 ** 3), 1)
    disk_used_gb  = round(disk.used  / (1024 ** 3), 1)
    disk_percent  = disk.percent

    # ── Uptime ───────────────────────────────────────────────────────────────
    uptime_seconds = time.time() - _START_TIME
    uptime_str     = _fmt_uptime(uptime_seconds)

    # ── Base de données PostgreSQL ────────────────────────────────────────────
    db_status  = "ok"
    db_latency = None
    db_version = None
    try:
        t0 = time.perf_counter()
        result = db.execute(text("SELECT version()")).fetchone()
        db_latency = round((time.perf_counter() - t0) * 1000, 2)   # ms
        db_version = result[0].split(",")[0] if result else "unknown"
    except Exception as e:
        db_status = f"error: {str(e)[:80]}"

    # ── Compteurs BDD ─────────────────────────────────────────────────────────
    try:
        sensors_total   = db.query(func.count(Capteur.id)).scalar() or 0
        sensors_active  = db.query(func.count(Capteur.id)).filter(Capteur.is_activated == True).scalar() or 0
        measures_total  = db.query(func.count(Mesure.id)).scalar() or 0
        alerts_active   = db.query(func.count(Alerte.id)).filter(Alerte.is_resolved == False).scalar() or 0

        # Dernière mesure enregistrée
        last_measure = db.query(Mesure).order_by(Mesure.time.desc()).first()
        last_measure_time = (
            last_measure.time.strftime("%d/%m/%Y %H:%M:%S")
            if last_measure else None
        )
    except Exception:
        sensors_total  = sensors_active = measures_total = alerts_active = 0
        last_measure_time = None

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_status = "offline"
    ollama_model  = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("http://localhost:11434/api/tags")
            if r.status_code == 200:
                ollama_status = "online"
                models = r.json().get("models", [])
                ollama_model = models[0]["name"] if models else "aucun modèle"
    except Exception:
        ollama_status = "offline"

    # ── OPC UA (vérifie si la tâche tourne via live_cache) ────────────────────
    try:
        from app.services.opcua_client import get_live_cache
        cache = get_live_cache()
        opcua_status      = "active" if len(cache) > 0 else "waiting"
        opcua_sensor_count = len(cache)
    except Exception:
        opcua_status       = "unknown"
        opcua_sensor_count = 0

    return {
        "timestamp": datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S UTC"),
        "uptime":    uptime_str,

        "cpu": {
            "percent":   cpu_percent,
            "cores":     cpu_count,
            "freq_mhz":  cpu_freq_mhz,
        },
        "ram": {
            "percent":   ram_percent,
            "used_gb":   ram_used_gb,
            "total_gb":  ram_total_gb,
        },
        "disk": {
            "percent":   disk_percent,
            "used_gb":   disk_used_gb,
            "total_gb":  disk_total_gb,
        },
        "database": {
            "status":      db_status,
            "latency_ms":  db_latency,
            "version":     db_version,
        },
        "ollama": {
            "status": ollama_status,
            "model":  ollama_model,
        },
        "opcua": {
            "status":       opcua_status,
            "active_feeds": opcua_sensor_count,
        },
        "data": {
            "sensors_total":    sensors_total,
            "sensors_active":   sensors_active,
            "measures_total":   measures_total,
            "alerts_active":    alerts_active,
            "last_measure_at":  last_measure_time,
        },
    }
