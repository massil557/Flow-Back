"""
app/services/opcua_client.py  (version mise à jour)
─────────────────────────────────────────────────────
Utilise les AlertConfig en base de données pour déterminer les seuils
warning et danger au lieu des seuils codés en dur dans config.py.

Nouveau comportement :
  • Si une AlertConfig active correspond au capteur → on l'utilise
  • Sinon → fallback sur get_threshold() (ancien comportement, inchangé)
  • Les emails sont envoyés aux destinataires configurés dans l'AlertConfig
  • Un cooldown par (capteur, niveau) évite le spam
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from asyncua import Client
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Capteur, Alerte, Mesure
from app.models.alert_config import AlertConfig
from app.config import OPC_URL, get_threshold
from app.services.email_service import send_alert_config_email, send_alert_email

live_cache = {}
last_two   = {}

# Cooldown : { (capteur_code, level): datetime_dernier_envoi }
_email_cooldowns: dict[tuple, datetime] = {}


def _get_matching_config(sensor_code: str, db: Session) -> AlertConfig | None:
    """
    Trouve la première AlertConfig active dont le sensor_prefix
    correspond au code du capteur (insensible à la casse).
    """
    configs = db.query(AlertConfig).filter(AlertConfig.is_enabled == True).all()
    code_upper = sensor_code.upper()
    for cfg in configs:
        if cfg.sensor_prefix.upper() in code_upper:
            return cfg
    return None


def _cooldown_ok(key: tuple, interval_minutes: int) -> bool:
    """Retourne True si l'email peut être envoyé (cooldown écoulé)."""
    last = _email_cooldowns.get(key)
    if last is None:
        return True
    return datetime.utcnow() - last >= timedelta(minutes=interval_minutes)


async def log_and_cache_forever():
    global live_cache
    while True:
        db = SessionLocal()
        try:
            async with Client(url=OPC_URL) as client:
                sensors = db.query(Capteur).all()
                if not sensors:
                    print("Aucun capteur trouvé en BDD. Lance seed_db.py.")

                for s in sensors:
                    if not s.is_activated:
                        continue
                    try:
                        path = ["0:Objects", "2:Machine_Alpha", f"2:{s.code_unique}"]
                        node = await client.nodes.root.get_child(path)
                        val_brute = await node.read_value()
                        val = round(float(val_brute), 2)
                        current_time = datetime.now().strftime("%H:%M:%S")

                        # ── Live cache (20 derniers points) ──────────────────
                        if s.code_unique not in live_cache:
                            live_cache[s.code_unique] = deque(maxlen=20)
                        live_cache[s.code_unique].append({"v": val, "t": current_time})

                        # ── Last-two cache ────────────────────────────────────
                        if s.code_unique not in last_two:
                            last_two[s.code_unique] = []
                        last_two[s.code_unique].append(val)
                        if len(last_two[s.code_unique]) > 2:
                            last_two[s.code_unique].pop(0)

                        prev_vals = last_two.get(s.code_unique, [])
                        prev_val  = prev_vals[-2] if len(prev_vals) > 1 else None

                        # ── Résolution des seuils ────────────────────────────
                        cfg = _get_matching_config(s.code_unique, db)

                        if cfg:
                            # ── Niveau DANGER ─────────────────────────────────
                            if val >= cfg.danger_threshold:
                                # Créer l'alerte en BDD si c'est un nouveau franchissement
                                if prev_val is None or prev_val < cfg.danger_threshold:
                                    db.add(Alerte(
                                        capteur_code  = s.code_unique,
                                        valeur        = val,
                                        seuil_depasse = cfg.danger_threshold,
                                        message       = (
                                            cfg.custom_message
                                            or f"[DANGER] {s.code_unique} = {val} ≥ seuil {cfg.danger_threshold}"
                                        ),
                                        time          = datetime.utcnow(),
                                        is_resolved   = False,
                                    ))

                                # Email avec cooldown
                                cooldown_key = (s.code_unique, "danger")
                                if _cooldown_ok(cooldown_key, cfg.reminder_interval_min):
                                    recipients = [
                                        r.strip()
                                        for r in cfg.email_recipients.split(",")
                                        if r.strip()
                                    ]
                                    if recipients:
                                        asyncio.create_task(send_alert_config_email(
                                            recipients    = recipients,
                                            sensor_prefix = s.code_unique,
                                            label         = cfg.label,
                                            level         = "danger",
                                            value         = val,
                                            threshold     = cfg.danger_threshold,
                                            custom_message= cfg.custom_message,
                                            timestamp     = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
                                        ))
                                        _email_cooldowns[cooldown_key] = datetime.utcnow()

                            # ── Niveau WARNING (sous danger) ─────────────────
                            elif val >= cfg.warning_threshold:
                                if prev_val is None or prev_val < cfg.warning_threshold:
                                    db.add(Alerte(
                                        capteur_code  = s.code_unique,
                                        valeur        = val,
                                        seuil_depasse = cfg.warning_threshold,
                                        message       = (
                                            cfg.custom_message
                                            or f"[WARNING] {s.code_unique} = {val} ≥ seuil warning {cfg.warning_threshold}"
                                        ),
                                        time          = datetime.utcnow(),
                                        is_resolved   = False,
                                    ))

                                cooldown_key = (s.code_unique, "warning")
                                if _cooldown_ok(cooldown_key, cfg.reminder_interval_min):
                                    recipients = [
                                        r.strip()
                                        for r in cfg.email_recipients.split(",")
                                        if r.strip()
                                    ]
                                    if recipients:
                                        asyncio.create_task(send_alert_config_email(
                                            recipients    = recipients,
                                            sensor_prefix = s.code_unique,
                                            label         = cfg.label,
                                            level         = "warning",
                                            value         = val,
                                            threshold     = cfg.warning_threshold,
                                            custom_message= cfg.custom_message,
                                            timestamp     = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
                                        ))
                                        _email_cooldowns[cooldown_key] = datetime.utcnow()

                        else:
                            # ── Fallback : ancien comportement ────────────────
                            sensor_threshold = get_threshold(s.code_unique)
                            if val >= sensor_threshold:
                                if prev_val is None or prev_val < sensor_threshold:
                                    alert_msg = f"Valeur {val} >= seuil {sensor_threshold}"
                                    db.add(Alerte(
                                        capteur_code  = s.code_unique,
                                        valeur        = val,
                                        seuil_depasse = sensor_threshold,
                                        message       = alert_msg,
                                        time          = datetime.utcnow(),
                                        is_resolved   = False,
                                    ))
                                    cooldown_key = (s.code_unique, "danger")
                                    if _cooldown_ok(cooldown_key, 30):
                                        asyncio.create_task(send_alert_email(
                                            sensor_code = s.code_unique,
                                            value       = val,
                                            timestamp   = current_time,
                                            message     = alert_msg,
                                        ))
                                        _email_cooldowns[cooldown_key] = datetime.utcnow()

                        # ── Persistance en BDD ────────────────────────────────
                        db.add(Mesure(
                            capteur_id = s.id,
                            valeur     = val,
                            time       = datetime.utcnow(),
                        ))

                    except Exception:
                        continue

                db.commit()

        except Exception as e:
            print(f"Erreur de connexion OPC UA : {e}")
        finally:
            db.close()

        await asyncio.sleep(1)


def get_live_cache():
    return live_cache


def get_last_two():
    return last_two
