"""
app/routers/admin_settings.py
──────────────────────────────
Admin-only endpoints for viewing/updating global application settings
stored in the app_settings table.
Settings include:
  - default_email_recipient : fallback email address for rule-based alerts
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.app_setting import AppSetting
from app.schemas.auth import UserPublic
from .auth import require_admin

router = APIRouter(prefix="/api/admin/settings", tags=["Admin Settings"])


class SettingUpdate(BaseModel):
    value: str


class SettingOut(BaseModel):
    key: str
    value: str


@router.get("", response_model=list[SettingOut])
def list_settings(db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    return db.query(AppSetting).all()


@router.get("/{key}", response_model=SettingOut)
def get_setting(key: str, db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Setting not found")
    return setting


@router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, payload: SettingUpdate, db: Session = Depends(get_db), _: UserPublic = Depends(require_admin)):
    setting = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not setting:
        setting = AppSetting(key=key, value=payload.value)
        db.add(setting)
    else:
        setting.value = payload.value
    db.commit()
    db.refresh(setting)
    return setting
