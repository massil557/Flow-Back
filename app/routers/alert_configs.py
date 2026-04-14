"""
app/routers/alert_configs.py
────────────────────────────
CRUD pour les règles d'alerte configurables depuis l'UI.
Routes :
  GET    /api/alert-configs            → liste toutes les règles
  POST   /api/alert-configs            → créer une règle
  PUT    /api/alert-configs/{id}       → modifier une règle
  PATCH  /api/alert-configs/{id}/toggle → activer / désactiver
  DELETE /api/alert-configs/{id}       → supprimer
  POST   /api/alert-configs/{id}/test-email → envoyer un email de test
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models.alert_config import AlertConfig
from app.schemas.alert_config import AlertConfigCreate, AlertConfigUpdate, AlertConfigOut
from app.services.email_service import send_alert_config_email

router = APIRouter(prefix="/api/alert-configs", tags=["Alert Configs"])


# ── GET all ──────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AlertConfigOut])
def get_alert_configs(db: Session = Depends(get_db)):
    return db.query(AlertConfig).order_by(AlertConfig.id.asc()).all()


# ── POST create ──────────────────────────────────────────────────────────────

@router.post("", response_model=AlertConfigOut, status_code=201)
def create_alert_config(data: AlertConfigCreate, db: Session = Depends(get_db)):
    # Validation : danger doit être >= warning
    if data.danger_threshold < data.warning_threshold:
        raise HTTPException(
            status_code=422,
            detail="Le seuil danger doit être supérieur ou égal au seuil avertissement."
        )
    config = AlertConfig(**data.dict())
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


# ── PUT update ───────────────────────────────────────────────────────────────

@router.put("/{config_id}", response_model=AlertConfigOut)
def update_alert_config(
    config_id: int,
    data: AlertConfigUpdate,
    db: Session = Depends(get_db)
):
    config = db.query(AlertConfig).filter(AlertConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Règle introuvable")

    update_data = data.dict(exclude_unset=True)

    # Revalidate thresholds if both are being updated
    w = update_data.get("warning_threshold", config.warning_threshold)
    d = update_data.get("danger_threshold",  config.danger_threshold)
    if d < w:
        raise HTTPException(
            status_code=422,
            detail="Le seuil danger doit être supérieur ou égal au seuil avertissement."
        )

    for field, value in update_data.items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)
    return config


# ── PATCH toggle ─────────────────────────────────────────────────────────────

@router.patch("/{config_id}/toggle", response_model=AlertConfigOut)
def toggle_alert_config(config_id: int, db: Session = Depends(get_db)):
    config = db.query(AlertConfig).filter(AlertConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    config.is_enabled = not config.is_enabled
    db.commit()
    db.refresh(config)
    return config


# ── DELETE ───────────────────────────────────────────────────────────────────

@router.delete("/{config_id}")
def delete_alert_config(config_id: int, db: Session = Depends(get_db)):
    config = db.query(AlertConfig).filter(AlertConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    db.delete(config)
    db.commit()
    return {"success": True}


# ── POST test-email ───────────────────────────────────────────────────────────

@router.post("/{config_id}/test-email")
async def test_alert_email(config_id: int, db: Session = Depends(get_db)):
    config = db.query(AlertConfig).filter(AlertConfig.id == config_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Règle introuvable")

    recipients = [r.strip() for r in config.email_recipients.split(",") if r.strip()]
    if not recipients:
        raise HTTPException(
            status_code=400,
            detail="Aucun destinataire configuré pour cette règle."
        )

    await send_alert_config_email(
        recipients=recipients,
        sensor_prefix=config.sensor_prefix,
        label=config.label,
        level="test",
        value=config.warning_threshold,
        threshold=config.warning_threshold,
        custom_message=config.custom_message or "Ceci est un email de test.",
        timestamp=datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S")
    )
    return {"success": True, "sent_to": recipients}
