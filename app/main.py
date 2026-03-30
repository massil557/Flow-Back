from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.config import ALLOWED_ORIGINS
from app.database import Base, engine
from app.services.opcua_client import log_and_cache_forever
from app.services.scheduler import send_scheduled_report
from app.routers import (
    sensors_router, zones_router, alerts_router, reports_router,
    analytics_router, auth_router, admin_router
)

app = FastAPI(title="Industrial IoT Gateway - Master 2")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(sensors_router)
app.include_router(zones_router)
app.include_router(alerts_router)
app.include_router(reports_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(admin_router)

# Additional direct endpoints (live-stream, last-two, history) that use the caches
from app.services.opcua_client import get_live_cache, get_last_two
from app.utils.downsampling import lttb_downsample
from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Mesure

@app.get("/api/live-stream")
async def get_live_stream():
    return get_live_cache()

@app.get("/api/last-two")
async def get_last_two():
    return get_last_two()

@app.get("/api/last-two/{code_unique}")
async def get_last_two_for_sensor(code_unique: str):
    return {code_unique: get_last_two().get(code_unique, [])}

@app.get("/api/history/{capteur_id}")
def get_long_history(capteur_id: int, hours: float | None = None, start: str | None = None, end: str | None = None, limit: int = 200, db: Session = Depends(get_db)):
    query = db.query(Mesure).filter(Mesure.capteur_id == capteur_id)
    if start and end:
        try:
            start_dt = datetime.fromisoformat(start)
            end_dt = datetime.fromisoformat(end)
            query = query.filter(Mesure.time >= start_dt, Mesure.time <= end_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide.")
    elif hours is not None and hours > 0:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = query.filter(Mesure.time >= cutoff)
    history = query.order_by(Mesure.time.asc()).all()
    result = [{"time": m.time, "valeur": m.valeur} for m in history]
    if len(result) > limit:
        result = lttb_downsample(result, limit)
    return result

# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    asyncio.create_task(log_and_cache_forever())

    scheduler = AsyncIOScheduler()
    scheduler.add_job(lambda: asyncio.create_task(send_scheduled_report("daily")), CronTrigger(hour=8, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_scheduled_report("weekly")), CronTrigger(day_of_week='mon', hour=8, minute=0))
    scheduler.add_job(lambda: asyncio.create_task(send_scheduled_report("monthly")), CronTrigger(day=1, hour=8, minute=0))
    scheduler.start()
    app.state.scheduler = scheduler

@app.on_event("shutdown")
async def shutdown_event():
    if hasattr(app.state, 'scheduler'):
        app.state.scheduler.shutdown()