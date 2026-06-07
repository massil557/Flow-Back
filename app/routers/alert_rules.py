from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.alert_rule import AlertRule
from app.models.capteur import Capteur
from app.schemas.alert_rule import AlertRuleCreate, AlertRuleUpdate, AlertRuleOut
from .auth import require_admin

router = APIRouter(prefix="/api/rules", tags=["Alert Rules"])

@router.get("", response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db)):
    return db.query(AlertRule).order_by(AlertRule.id.asc()).all()

@router.post("", response_model=AlertRuleOut, status_code=201)
def create_rule(data: AlertRuleCreate, db: Session = Depends(get_db), _=Depends(require_admin)):
    sensor = db.query(Capteur).filter(Capteur.id == data.sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Capteur introuvable")
    rule = AlertRule(
        sensor_id=data.sensor_id,
        condition=data.condition,
        threshold=data.threshold,
        severity=data.severity,
        cooldown_seconds=data.cooldown_seconds,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule

@router.put("/{rule_id}", response_model=AlertRuleOut)
def update_rule(rule_id: int, data: AlertRuleUpdate, db: Session = Depends(get_db), _=Depends(require_admin)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    for field, value in data.dict(exclude_unset=True).items():
        setattr(rule, field, value)
    db.commit()
    db.refresh(rule)
    return rule

@router.delete("/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db), _=Depends(require_admin)):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    db.delete(rule)
    db.commit()
    return {"success": True}
