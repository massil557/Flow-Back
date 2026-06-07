"""
app/services/opcua_client.py
─────────────────────────────
Reads sensor values from the OPC UA server, persists them, and runs
both legacy AlertConfig and new AlertRule evaluations.
Email cooldown is now managed inside email_service.py against the DB.
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from asyncua import Client
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models import Capteur, Alerte, Mesure
from app.models.alert_config import AlertConfig
from app.config import OPC_URL, get_threshold
from app.services.email_service import send_alert_config_email, send_alert_email
from app.services.rule_evaluator import evaluate_rules_for_sensor

logger = logging.getLogger("opcua_client")

live_cache = {}
last_two   = {}

# Keep strong references to asyncio tasks so they are not GC'd before completion
_pending_email_tasks: list[asyncio.Task] = []


def _run_email_task(coro) -> None:
    task = asyncio.create_task(coro)

    def _done_cb(t: asyncio.Task) -> None:
        _pending_email_tasks[:] = [t_ for t_ in _pending_email_tasks if t_ is not t]
        exc = t.exception()
        if exc:
            logger.error(f"[EmailTask] Failed to send email: {exc}")

    task.add_done_callback(_done_cb)
    _pending_email_tasks.append(task)


def _get_matching_config(sensor_code: str, sensor_id: int, db: Session) -> AlertConfig | None:
    """
    Trouve la première AlertConfig active correspondant au capteur.
    Priorité : sensor_id exact → préfixe dans le code.
    """
    configs = db.query(AlertConfig).filter(AlertConfig.is_enabled == True).all()
    for cfg in configs:
        if cfg.sensor_id == sensor_id:
            return cfg
    code_upper = sensor_code.upper()
    for cfg in configs:
        if cfg.sensor_prefix.upper() in code_upper:
            return cfg
    return None


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

                        if s.code_unique not in live_cache:
                            live_cache[s.code_unique] = deque(maxlen=20)
                        live_cache[s.code_unique].append({"v": val, "t": current_time})

                        if s.code_unique not in last_two:
                            last_two[s.code_unique] = []
                        last_two[s.code_unique].append(val)
                        if len(last_two[s.code_unique]) > 2:
                            last_two[s.code_unique].pop(0)

                        prev_vals = last_two.get(s.code_unique, [])
                        prev_val  = prev_vals[-2] if len(prev_vals) > 1 else None

                        cfg = _get_matching_config(s.code_unique, s.id, db)

                        if cfg:
                            if val >= cfg.danger_threshold:
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

                                recipients = [
                                    r.strip()
                                    for r in cfg.email_recipients.split(",")
                                    if r.strip()
                                ]
                                if recipients:
                                    _run_email_task(send_alert_config_email(
                                        recipients    = recipients,
                                        sensor_prefix = s.code_unique,
                                        label         = cfg.label,
                                        level         = "danger",
                                        value         = val,
                                        threshold     = cfg.danger_threshold,
                                        custom_message= cfg.custom_message,
                                        timestamp     = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
                                        config_id     = cfg.id,
                                    ))

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

                                recipients = [
                                    r.strip()
                                    for r in cfg.email_recipients.split(",")
                                    if r.strip()
                                ]
                                if recipients:
                                    _run_email_task(send_alert_config_email(
                                        recipients    = recipients,
                                        sensor_prefix = s.code_unique,
                                        label         = cfg.label,
                                        level         = "warning",
                                        value         = val,
                                        threshold     = cfg.warning_threshold,
                                        custom_message= cfg.custom_message,
                                        timestamp     = datetime.utcnow().strftime("%d/%m/%Y %H:%M:%S"),
                                        config_id     = cfg.id,
                                    ))

                        else:
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
                                    _run_email_task(send_alert_email(
                                        sensor_code = s.code_unique,
                                        value       = val,
                                        timestamp   = current_time,
                                        message     = alert_msg,
                                    ))

                        evaluate_rules_for_sensor(s.id, s.code_unique, val)

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
