"""
app/services/rule_evaluator.py
───────────────────────────────
Evaluates AlertRule conditions on every sensor reading.
Creates an alert in the database when a rule is triggered, and
dispatches an async email with DB-backed per-rule cooldown.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models.alert_rule import AlertRule
from app.models.capteur import Capteur
from app.models.alerte import Alerte
from app.services.email_service import send_rule_alert_email

logger = logging.getLogger("rule_evaluator")


def evaluate_rules_for_sensor(sensor_id: int, sensor_code: str, value: float) -> None:
    db = SessionLocal()
    try:
        rules = db.query(AlertRule).filter(
            AlertRule.active == True,
            AlertRule.sensor_id == sensor_id
        ).all()

        now = datetime.utcnow()
        for rule in rules:
            triggered = False
            if rule.condition == ">" and value > rule.threshold:
                triggered = True
            elif rule.condition == "<" and value < rule.threshold:
                triggered = True
            elif rule.condition == ">=" and value >= rule.threshold:
                triggered = True
            elif rule.condition == "<=" and value <= rule.threshold:
                triggered = True
            elif rule.condition == "==" and value == rule.threshold:
                triggered = True

            if not triggered:
                continue

            # ── DB dedup: skip if a similar unresolved alert exists within cooldown ─
            cooldown_sec = rule.cooldown_seconds or 0
            if cooldown_sec > 0:
                existing = db.query(Alerte).filter(
                    Alerte.capteur_code == sensor_code,
                    Alerte.rule_id == rule.id,
                    Alerte.is_resolved == False,
                    Alerte.time >= now - timedelta(seconds=cooldown_sec)
                ).first()
                if existing:
                    continue

            # ── Create the alert ──────────────────────────────────────────────
            db.add(Alerte(
                capteur_code=sensor_code,
                valeur=value,
                seuil_depasse=rule.threshold,
                message=f"[{rule.severity.upper()}] {sensor_code} {rule.condition} {rule.threshold} (valeur={value})",
                time=now,
                is_resolved=False,
                severity=rule.severity,
                rule_id=rule.id,
                is_rule_based=True,
            ))
            db.commit()

            # ── Dispatch async email (non-blocking) ─────────────────────────
            asyncio.ensure_future(send_rule_alert_email(
                sensor_code=sensor_code,
                sensor_label=sensor_code,
                value=value,
                threshold=rule.threshold,
                severity=rule.severity,
                rule_id=rule.id,
                timestamp=now.strftime("%d/%m/%Y %H:%M:%S"),
            ))

    except Exception as e:
        logger.error(f"Error evaluating rules for sensor {sensor_code}: {e}")
        db.rollback()
    finally:
        db.close()
