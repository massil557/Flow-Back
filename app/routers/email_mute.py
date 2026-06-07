"""
app/routers/email_mute.py
─────────────────────────
Global email alert silencing with file-based persistence.
State survives server restarts, logouts, and browser closes.

Legacy routes (kept for backward compatibility):
  GET  /api/email-mute           → { "muted": bool }
  POST /api/email-mute/toggle    → { "muted": bool }  (flips state)

New admin routes:
  GET  /api/admin/email-silence  → { "silenced": bool }
  POST /api/admin/email-silence  → { "silenced": bool }  (set explicit state)
"""

import json
import os
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.schemas.auth import UserPublic
from app.config import ALERT_EMAIL_SENDER, ALERT_EMAIL_PASSWORD, ALERT_EMAIL_RECIPIENT
from .auth import require_admin

router = APIRouter(tags=["Email Mute"])

_SILENCE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "silence_state.json"
)


class SilencePayload(BaseModel):
    silenced: bool


# ── File I/O helpers ───────────────────────────────────────────────────────────

def _load_state() -> bool:
    """Read silenced state from file. Returns False if file missing/corrupt."""
    try:
        if os.path.exists(_SILENCE_FILE):
            with open(_SILENCE_FILE, "r") as f:
                data = json.load(f)
                return bool(data.get("silenced", False))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[EmailMute] Warning: could not read {_SILENCE_FILE}: {e}")
    return False


def _save_state(silenced: bool) -> None:
    """Persist silenced state to file."""
    try:
        with open(_SILENCE_FILE, "w") as f:
            json.dump({"silenced": silenced}, f)
    except OSError as e:
        print(f"[EmailMute] Error: could not write {_SILENCE_FILE}: {e}")


# ── Module-level cache (loaded once at import time) ────────────────────────────
_silenced: bool = _load_state()


def is_muted() -> bool:
    """Called by email_service.py before sending alert emails."""
    return _silenced


# ── GET /api/email-mute (legacy) ───────────────────────────────────────────────

@router.get("/api/email-mute")
def get_mute_status():
    return {"muted": _silenced}


# ── POST /api/email-mute/toggle (legacy, admin only) ───────────────────────────

@router.post("/api/email-mute/toggle")
def toggle_mute(_: UserPublic = Depends(require_admin)):
    global _silenced
    _silenced = not _silenced
    _save_state(_silenced)
    state = "silencieux" if _silenced else "actif"
    print(f"[EmailMute] Envoi des emails d'alerte : {state}")
    return {"muted": _silenced}


# ── GET /api/admin/email-silence (admin) ───────────────────────────────────────

@router.get("/api/admin/email-silence")
def get_email_silence(_: UserPublic = Depends(require_admin)):
    return {"silenced": _silenced}


# ── POST /api/admin/email-silence (admin, set explicit state) ──────────────────

@router.post("/api/admin/email-silence")
def set_email_silence(payload: SilencePayload, _: UserPublic = Depends(require_admin)):
    global _silenced
    _silenced = payload.silenced
    _save_state(_silenced)
    state = "silencieux" if _silenced else "actif"
    print(f"[EmailMute] Envoi des emails d'alerte : {state}")
    return {"silenced": _silenced}


# ── POST /api/test-email (bypasses mute, sends a direct SMTP test) ──────────

@router.post("/api/test-email")
async def send_test_email():
    """Send a test email to ALERT_EMAIL_RECIPIENT to verify SMTP config."""
    import aiosmtplib
    from email.message import EmailMessage

    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return {"success": False, "detail": "ALERT_EMAIL_SENDER ou ALERT_EMAIL_PASSWORD non configuré"}

    msg = EmailMessage()
    msg["Subject"] = "🔧 Test email — Flow Supervision"
    msg["From"]    = ALERT_EMAIL_SENDER
    msg["To"]      = ALERT_EMAIL_RECIPIENT
    msg.set_content(
        "Ceci est un email de test envoyé depuis Flow.\n"
        f"État actuel du silence : {'silencieux' if _silenced else 'actif'}\n"
        f"is_muted() = {is_muted()}\n"
        f"_silenced = {_silenced}\n"
    )

    try:
        await aiosmtplib.send(
            msg,
            hostname="smtp.gmail.com",
            port=465,
            username=ALERT_EMAIL_SENDER,
            password=ALERT_EMAIL_PASSWORD,
            use_tls=True,
            timeout=30,
        )
        print(f"[TestEmail] ✅ Test email envoyé à {ALERT_EMAIL_RECIPIENT}")
        return {"success": True, "detail": f"Email envoyé à {ALERT_EMAIL_RECIPIENT}"}
    except Exception as e:
        print(f"[TestEmail] ❌ Échec : {e}")
        return {"success": False, "detail": str(e)}
