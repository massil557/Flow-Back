"""
app/main.py  (mis à jour — ajout du router alert_configs)
Seule modification : import + include_router pour alert_configs_router.
Tout le reste est identique à l'original.
"""

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.config import ALLOWED_ORIGINS
from app.database import Base, engine, get_db
from app.models import Mesure, Capteur
# ── NOUVEAU ──────────────────────────────────────────────────────────────────
from app.models.alert_config import AlertConfig          # force la création de la table
# ─────────────────────────────────────────────────────────────────────────────
from app.services.opcua_client import log_and_cache_forever
from app.services.opcua_client import get_live_cache as _get_live_cache
from app.services.opcua_client import get_last_two as _get_last_two_cache
from app.services.scheduler import send_scheduled_report
from app.utils.downsampling import lttb_downsample
from app.routers import (
    sensors_router, zones_router, alerts_router, reports_router,
    analytics_router, auth_router, admin_router
)
# ── NOUVEAU ──────────────────────────────────────────────────────────────────
from app.routers.alert_configs import router as alert_configs_router
# ─────────────────────────────────────────────────────────────────────────────
from app.routers.email_mute import router as email_mute_router
from app.routers.server_status import router as server_status_router

app = FastAPI(title="Industrial IoT Gateway - Master 2")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers existants ─────────────────────────────────────────────────────────
app.include_router(sensors_router)
app.include_router(zones_router)
app.include_router(alerts_router)
app.include_router(reports_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(admin_router)

# ── NOUVEAU router ────────────────────────────────────────────────────────────
app.include_router(alert_configs_router)
app.include_router(email_mute_router)
app.include_router(server_status_router)


# ── Live stream ────────────────────────────────────────────────────────────────
@app.get("/api/live-stream")
async def live_stream_endpoint():
    return _get_live_cache()


# ── Last-two (all sensors) ─────────────────────────────────────────────────────
@app.get("/api/last-two")
async def last_two_all_endpoint():
    return _get_last_two_cache()


# ── Last-two (single sensor) with DB fallback ─────────────────────────────────
@app.get("/api/last-two/{code_unique}")
async def last_two_sensor_endpoint(code_unique: str, db: Session = Depends(get_db)):
    cached = _get_last_two_cache().get(code_unique)
    if cached:
        return {code_unique: cached}

    sensor = db.query(Capteur).filter(Capteur.code_unique == code_unique).first()
    if not sensor:
        return {code_unique: []}

    rows = (
        db.query(Mesure)
        .filter(Mesure.capteur_id == sensor.id)
        .order_by(Mesure.time.desc())
        .limit(2)
        .all()
    )
    values = [r.valeur for r in reversed(rows)]
    return {code_unique: values}


# ── Long history ───────────────────────────────────────────────────────────────
@app.get("/api/history/{capteur_id}")
def history_endpoint(
    capteur_id: int,
    hours: float | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = db.query(Mesure).filter(Mesure.capteur_id == capteur_id)
    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt   = datetime.fromisoformat(end)
            query = query.filter(Mesure.time >= start_dt, Mesure.time <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide.")
    elif hours is not None and hours > 0:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query  = query.filter(Mesure.time >= cutoff)

    history = query.order_by(Mesure.time.asc()).all()
    result  = [{"time": m.time, "valeur": m.valeur} for m in history]
    if len(result) > limit:
        result = lttb_downsample(result, limit)
    return result


# ── Startup / shutdown ─────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    # Crée toutes les tables (y compris alert_configs)
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(log_and_cache_forever())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("daily")),
        CronTrigger(hour=8, minute=0),
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("weekly")),
        CronTrigger(day_of_week="mon", hour=8, minute=0),
    )
    scheduler.add_job(
        lambda: asyncio.create_task(send_scheduled_report("monthly")),
        CronTrigger(day=1, hour=8, minute=0),
    )
    scheduler.start()
    app.state.scheduler = scheduler


@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, "scheduler"):
        app.state.scheduler.shutdown()
