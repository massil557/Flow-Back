from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Zone, Capteur, Alerte, Mesure
from app.schemas import ZoneCreate, ZoneUpdate

router = APIRouter(prefix="/api/zones", tags=["Zones"])

@router.get("")
def get_zones(db: Session = Depends(get_db)):
    try:
        zones = db.query(Zone).all()
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

@router.get("/{zone_id}/stats")
def get_zone_stats(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    sensors = db.query(Capteur).filter(Capteur.zone_id == zone_id).all()
    sensor_count = len(sensors)
    sensor_codes = [s.code_unique for s in sensors]
    active_alerts = 0
    if sensor_codes:
        active_alerts = db.query(Alerte).filter(
            Alerte.capteur_code.in_(sensor_codes),
            Alerte.is_resolved == False
        ).count()
    latest_values = {}
    sensors_list = []
    for sensor in sensors:
        sensors_list.append({
            "code": sensor.code_unique,
            "type": sensor.type_grandeur,
            "unit": sensor.unite,
            "is_activated": sensor.is_activated
        })
        last_measure = db.query(Mesure).filter(
            Mesure.capteur_id == sensor.id
        ).order_by(Mesure.time.desc()).first()
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

@router.post("")
def create_zone(zone: ZoneCreate, db: Session = Depends(get_db)):
    existing = db.query(Zone).filter(Zone.code_zone == zone.code_zone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ce code de zone existe déjà")
    new_zone = Zone(**zone.dict())
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

@router.put("/{zone_id}")
def update_zone(zone_id: int, zone: ZoneUpdate, db: Session = Depends(get_db)):
    existing = db.query(Zone).filter(Zone.id == zone_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Zone introuvable")
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

@router.delete("/{zone_id}")
def delete_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    other_zone = db.query(Zone).filter(Zone.id != zone_id).first()
    if other_zone:
        db.query(Capteur).filter(Capteur.zone_id == zone_id).update({"zone_id": other_zone.id})
    else:
        db.query(Capteur).filter(Capteur.zone_id == zone_id).update({"zone_id": None})
    db.delete(zone)
    db.commit()
    return {"success": True, "message": f"Zone '{zone.nom_zone}' supprimée"}

@router.get("/{zone_id}")
def get_zone_by_id(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(Zone).filter(Zone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    sensors = db.query(Capteur).filter(Capteur.zone_id == zone_id).all()
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