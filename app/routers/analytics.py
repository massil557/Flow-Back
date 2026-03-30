from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from app.database import get_db
from app.models import Capteur, Mesure, Zone
from app.schemas import TimeSeriesRequest

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])

@router.post("/timeseries")
def get_timeseries_data(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")
    trunc_map = {"minute": "minute", "hour": "hour", "day": "day"}
    trunc = trunc_map.get(req.interval, "hour")
    query = db.query(
        func.date_trunc(trunc, Mesure.time).label("bucket"),
        func.avg(Mesure.valeur).label("avg_value"),
        func.min(Mesure.valeur).label("min_value"),
        func.max(Mesure.valeur).label("max_value"),
        func.count(Mesure.valeur).label("count")
    ).join(Capteur, Mesure.capteur_id == Capteur.id).filter(
        Capteur.type_grandeur == req.category,
        Mesure.time >= start_dt,
        Mesure.time <= end_dt
    )
    if req.zone_id is not None:
        query = query.filter(Capteur.zone_id == req.zone_id)
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

@router.post("/zone-comparison")
def get_zone_comparison(req: TimeSeriesRequest, db: Session = Depends(get_db)):
    if req.start and req.end:
        start_dt = req.start
        end_dt = req.end
    elif req.hours is not None and req.hours > 0:
        end_dt = datetime.utcnow()
        start_dt = end_dt - timedelta(hours=req.hours)
    else:
        raise HTTPException(status_code=400, detail="Either start/end or hours must be provided")
    results = db.query(
        Zone.id.label("zone_id"),
        Zone.nom_zone.label("zone_name"),
        func.avg(Mesure.valeur).label("avg_value"),
        func.count(func.distinct(Capteur.id)).label("sensor_count")
    ).join(Capteur, Capteur.zone_id == Zone.id).join(Mesure, Mesure.capteur_id == Capteur.id).filter(
        Capteur.type_grandeur == req.category,
        Mesure.time >= start_dt,
        Mesure.time <= end_dt
    ).group_by(Zone.id, Zone.nom_zone).order_by(Zone.nom_zone).all()
    return [
        {
            "zone_id": r.zone_id,
            "zone_name": r.zone_name,
            "avg_value": r.avg_value,
            "sensor_count": r.sensor_count
        }
        for r in results
    ]