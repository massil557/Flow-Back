"""
app/services/email_service.py
──────────────────────────────
Unified email service with:
- DB-backed per-rule cooldown tracking (alert_email_log table)
- 3-attempt retry with exponential backoff (0s, 5s, 10s)
- Logging every attempt (success/failure) to alert_email_log
- Automatic recipient resolution: per-call → ALERT_EMAIL_TO → ALERT_EMAIL_RECIPIENT
- Proper async, non-blocking sending via aiosmtplib
"""

import asyncio
import logging
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Optional

import aiosmtplib
from sqlalchemy import desc

from app.config import ALERT_EMAIL_SENDER, ALERT_EMAIL_PASSWORD, ALERT_EMAIL_RECIPIENT, ALERT_EMAIL_TO

logger = logging.getLogger("email_service")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_default_recipient() -> str:
    return (ALERT_EMAIL_TO or ALERT_EMAIL_RECIPIENT or "").strip()


def _is_muted() -> bool:
    from app.routers.email_mute import is_muted
    return is_muted()


def _cooldown_seconds_for(rule_id: Optional[int], config_id: Optional[int], sensor_code: str, level: str) -> int:
    """
    Read the applicable cooldown from the rule/config definition.
    AlertRule: cooldown_seconds (default 0 = no cooldown)
    AlertConfig: reminder_interval_min * 60
    """
    from app.database import SessionLocal
    from app.models.alert_rule import AlertRule
    from app.models.alert_config import AlertConfig

    db = SessionLocal()
    try:
        if rule_id is not None:
            rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
            if rule:
                return rule.cooldown_seconds or 0
        if config_id is not None:
            cfg = db.query(AlertConfig).filter(AlertConfig.id == config_id).first()
            if cfg:
                return cfg.reminder_interval_min * 60
    finally:
        db.close()
    return 0


def _last_successful_send(rule_id: Optional[int], config_id: Optional[int], sensor_code: str, level: str) -> Optional[datetime]:
    """Return the timestamp of the most recent successful send for the given entity."""
    from app.database import SessionLocal
    from app.models.alert_email_log import AlertEmailLog

    db = SessionLocal()
    try:
        query = db.query(AlertEmailLog).filter(
            AlertEmailLog.level == level,
            AlertEmailLog.success == True,
        )
        if rule_id is not None:
            query = query.filter(AlertEmailLog.rule_id == rule_id)
        elif config_id is not None:
            query = query.filter(AlertEmailLog.config_id == config_id)
        else:
            query = query.filter(AlertEmailLog.sensor_code == sensor_code)

        last = query.order_by(desc(AlertEmailLog.last_sent_at)).first()
        if last is not None:
            return last.last_sent_at
        return None
    finally:
        db.close()


def _is_cooldown_active(rule_id: Optional[int], config_id: Optional[int], sensor_code: str, level: str) -> bool:
    cooldown_sec = _cooldown_seconds_for(rule_id, config_id, sensor_code, level)
    if cooldown_sec <= 0:
        return False
    last = _last_successful_send(rule_id, config_id, sensor_code, level)
    if last is None:
        return False
    elapsed = (datetime.utcnow() - last).total_seconds()
    return elapsed < cooldown_sec


def _log_attempt(rule_id, config_id, sensor_code, level, recipient, success, error_msg, attempt_count):
    from app.database import SessionLocal
    from app.models.alert_email_log import AlertEmailLog

    db = SessionLocal()
    try:
        db.add(AlertEmailLog(
            rule_id=rule_id,
            config_id=config_id,
            sensor_code=sensor_code,
            level=level,
            recipient=recipient,
            success=success,
            error_message=error_msg,
            attempt_count=attempt_count,
            last_sent_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception as e:
        logger.error(f"Failed to log email attempt: {e}")
    finally:
        db.close()


# ── Low-level sender with retry ──────────────────────────────────────────────

async def _send_raw(subject: str, body: str, to_addrs: list[str]) -> tuple[bool, str]:
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        logger.warning("Missing SMTP credentials, skipping email")
        return False, "Missing SMTP credentials"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(body)

    last_error = ""
    for attempt in range(3):
        try:
            if attempt > 0:
                delay = attempt * 5
                await asyncio.sleep(delay)
            await aiosmtplib.send(
                msg,
                hostname="smtp.gmail.com",
                port=465,
                username=ALERT_EMAIL_SENDER,
                password=ALERT_EMAIL_PASSWORD,
                use_tls=True,
                timeout=30,
            )
            logger.info(f"Email sent to {', '.join(to_addrs)}: {subject}")
            return True, ""
        except Exception as exc:
            last_error = str(exc)
            logger.error(f"Attempt {attempt+1}/3 failed for {to_addrs}: {exc}")

    logger.error(f"Email abandoned after 3 attempts for {to_addrs}: {subject}")
    return False, last_error


# ── Public API ───────────────────────────────────────────────────────────────

async def send_alert_config_email(
    recipients: list[str],
    sensor_prefix: str,
    label: str,
    level: str,
    value: float,
    threshold: float,
    custom_message: str = "",
    timestamp: str = "",
    config_id: Optional[int] = None,
) -> None:
    if level != "test" and _is_muted():
        logger.info(f"[Mute] Skipping {level} email for {sensor_prefix}")
        return

    if not recipients:
        recipients = [_get_default_recipient()]
    recipients = [r for r in recipients if r]
    if not recipients:
        logger.warning(f"No recipients for config {sensor_prefix}")
        return

    if level != "test" and _is_cooldown_active(None, config_id, sensor_prefix, level):
        logger.info(f"[Cooldown] Skipping {level} email for config #{config_id} ({sensor_prefix})")
        return

    level_labels = {"warning": "AVERTISSEMENT", "danger": "DANGER CRITIQUE", "test": "TEST"}
    prefix = level_labels.get(level, "ALERTE")
    subject = f"[{prefix}] {label} ({sensor_prefix})"
    body = (
        f"=== {prefix} ===\n\n"
        f"Capteur    : {label} ({sensor_prefix})\n"
        f"Valeur     : {value}\n"
        f"Seuil      : {threshold}\n"
        f"Horodatage : {timestamp}\n"
    )
    if custom_message:
        body += f"\nMessage    : {custom_message}\n"
    body += "\n--- Systeme de supervision Flow ---\n"

    success, error = await _send_raw(subject, body, recipients)
    _log_attempt(None, config_id, sensor_prefix, level, ", ".join(recipients), success, error if not success else None, 3 if not success else 1)


async def send_rule_alert_email(
    sensor_code: str,
    sensor_label: str,
    value: float,
    threshold: float,
    severity: str,
    rule_id: int,
    timestamp: str = "",
    recipient: str = "",
) -> None:
    if _is_muted():
        logger.info(f"[Mute] Skipping rule {rule_id} email for {sensor_code}")
        return

    to_addr = (recipient or _get_default_recipient()).strip()
    if not to_addr:
        logger.warning(f"No recipient for rule {rule_id} ({sensor_code})")
        return

    if _is_cooldown_active(rule_id, None, sensor_code, severity):
        logger.info(f"[Cooldown] Skipping rule {rule_id} email for {sensor_code}/{severity}")
        return

    level_label = "DANGER" if severity == "danger" else "AVERTISSEMENT"
    subject = f"[{level_label}] {sensor_label or sensor_code} ({value})"
    body = (
        f"=== {level_label} ===\n\n"
        f"Capteur    : {sensor_label or sensor_code}\n"
        f"Valeur     : {value}\n"
        f"Seuil      : {threshold}\n"
        f"Regle      : #{rule_id}\n"
        f"Horodatage : {timestamp}\n\n"
        f"--- Systeme de supervision Flow ---\n"
    )

    success, error = await _send_raw(subject, body, [to_addr])
    _log_attempt(rule_id, None, sensor_code, severity, to_addr, success, error if not success else None, 3 if not success else 1)


async def send_alert_email(
    sensor_code: str,
    value: float,
    timestamp: str,
    message: str,
) -> None:
    """Fallback email (no AlertConfig match). Uses env-var recipient."""
    if _is_muted():
        logger.info(f"[Mute] Skipping fallback email for {sensor_code}")
        return

    to_addr = _get_default_recipient()
    if not to_addr:
        logger.warning(f"No default recipient for fallback alert {sensor_code}")
        return

    subject = f"[ALERTE] {sensor_code} ({value})"
    body = (
        f"=== ALERTE ===\n\n"
        f"Capteur    : {sensor_code}\n"
        f"Valeur     : {value}\n"
        f"Horodatage : {timestamp}\n"
        f"{message}\n\n"
        f"--- Systeme de supervision Flow ---\n"
    )

    success, error = await _send_raw(subject, body, [to_addr])
    _log_attempt(None, None, sensor_code, "danger", to_addr, success, error if not success else None, 3 if not success else 1)


# ── Report / credential emails (unchanged, no cooldown) ────────────────────

async def send_pdf_via_email(to_emails: list[str], subject: str, pdf_bytes: bytes, filename: str = "rapport.pdf") -> bool:
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ", ".join(to_emails)
    msg.set_content("Veuillez trouver le rapport ci-joint.")
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD, use_tls=True, timeout=30)
        logger.info(f"PDF report sent to {', '.join(to_emails)}")
        return True
    except Exception as e:
        logger.error(f"Failed to send PDF report: {e}")
        return False


async def send_credentials_email(to_email: str, username: str, password: str, role: str) -> None:
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return
    msg = EmailMessage()
    msg["Subject"] = "Vos acces Flow - Systeme de supervision industrielle"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = to_email
    msg.set_content(f"Bonjour {username},\n\nCompte cree.\nNom: {username}\nMDP: {password}\nRole: {role}\n\nFlow")
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD, use_tls=True, timeout=10)
        logger.info(f"Credentials email sent to {to_email}")
    except Exception as e:
        logger.error(f"Credentials email failed: {e}")


async def send_update_email(to_email: str, username: str, role: str) -> None:
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return
    msg = EmailMessage()
    msg["Subject"] = "Votre compte Flow a ete mis a jour"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = to_email
    msg.set_content(f"Bonjour {username},\nCompte modifie.\nNom: {username}\nRole: {role}\n\nFlow")
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD, use_tls=True, timeout=10)
        logger.info(f"Update email sent to {to_email}")
    except Exception as e:
        logger.error(f"Update email failed: {e}")
