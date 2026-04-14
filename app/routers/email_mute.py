"""
app/routers/email_mute.py
─────────────────────────
Contrôle global de l'envoi des emails d'alerte.
État stocké en mémoire (reset au redémarrage = comportement voulu en dev).

Routes :
  GET  /api/email-mute          → { "muted": bool }
  POST /api/email-mute/toggle   → { "muted": bool }
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/email-mute", tags=["Email Mute"])

# ── État global en mémoire ────────────────────────────────────────────────────
# False = emails activés (comportement normal)
# True  = emails silencieux (alertes BDD créées, mais aucun email envoyé)
_muted: bool = False


def is_muted() -> bool:
    """Appelée par email_service.py avant chaque envoi."""
    return _muted


@router.get("")
def get_mute_status():
    return {"muted": _muted}


@router.post("/toggle")
def toggle_mute():
    global _muted
    _muted = not _muted
    state = "silencieux" if _muted else "actif"
    print(f"[EmailMute] Envoi des emails d'alerte : {state}")
    return {"muted": _muted}
