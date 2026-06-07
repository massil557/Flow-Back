from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from app.database import get_db
from app.models import Alerte
from app.schemas import AlertTrigger

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

@router.post("/trigger")
async def trigger_alert(alert_data: AlertTrigger, db: Session = Depends(get_db)):
    try:
        new_alert = Alerte(
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

@router.get("")
async def get_alerts(
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db)
):
    total = db.query(func.count(Alerte.id)).scalar()
    total_pages = max(1, (total + limit - 1) // limit) if total > 0 else 1
    offset_val = (page - 1) * limit
    alerts = db.query(Alerte).order_by(Alerte.time.desc()).offset(offset_val).limit(limit).all()
    return {
        "total": total,
        "totalPages": total_pages,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": a.id,
                "code": a.capteur_code,
                "time": a.time.strftime("%d/%m %H:%M:%S"),
                "value": a.valeur,
                "seuil": a.seuil_depasse,
                "msg": a.message,
                "is_resolved": a.is_resolved,
                "severity": a.severity or "danger",
                "is_rule_based": a.is_rule_based or False,
                "rule_id": a.rule_id
            } for a in alerts
        ]
    }

@router.patch("/{alert_id}/resolve")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    alert.is_resolved = True
    db.commit()
    return {"success": True}

@router.patch("/{alert_id}/ignore")
def ignore_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    db.delete(alert)
    db.commit()
    return {"success": True}

@router.delete("/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alerte).filter(Alerte.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    db.delete(alert)
    db.commit()
    return {"success": True}