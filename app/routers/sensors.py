from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Capteur
from app.schemas import SensorCreate, TogglePayload

router = APIRouter(prefix="/api/sensors", tags=["Sensors"])

@router.post("")
def create_sensor(sensor: SensorCreate, db: Session = Depends(get_db)):
    new = Capteur(**sensor.dict())
    db.add(new)
    db.commit()
    db.refresh(new)
    return new

@router.patch("/{sensor_id}/activate")
def toggle_sensor(
    sensor_id: int,
    payload: TogglePayload | None = Body(None),
    activate: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    sensor = db.query(Capteur).get(sensor_id)
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

@router.put("/{sensor_id}")
def update_sensor(sensor_id: int, sensor: SensorCreate, db: Session = Depends(get_db)):
    existing = db.query(Capteur).filter(Capteur.id == sensor_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Capteur non trouve")
    existing.code_unique = sensor.code_unique
    existing.type_grandeur = sensor.type_grandeur
    existing.unite = sensor.unite
    existing.adresse_ip = sensor.adresse_ip
    db.commit()
    db.refresh(existing)
    return existing

@router.get("")
def get_sensors_list(db: Session = Depends(get_db)):
    return db.query(Capteur).filter(Capteur.is_activated == True).all()

@router.get("/zone/{zone_id}")
def get_sensors_by_zone(zone_id: int, db: Session = Depends(get_db)):
    sensors = db.query(Capteur).filter(Capteur.zone_id == zone_id).all()
    return sensors if sensors else []