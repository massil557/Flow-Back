"""
app/services/email_service.py
──────────────────────────────
Vérifie is_muted() avant chaque envoi d'email d'ALERTE.
Les emails de rapports PDF et de credentials ne sont PAS affectés par le mute.
"""

import asyncio
import aiosmtplib
from email.message import EmailMessage
from app.config import ALERT_EMAIL_SENDER, ALERT_EMAIL_PASSWORD, ALERT_EMAIL_RECIPIENT


def _is_muted() -> bool:
    from app.routers.email_mute import is_muted
    return is_muted()


async def send_alert_email(sensor_code: str, value: float, timestamp: str, message: str):
    if _is_muted():
        print(f"[EmailMute] 🔕 Email silencieux pour {sensor_code} (mute actif)")
        return
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return
    msg = EmailMessage()
    msg["Subject"] = f"ALERTE : {sensor_code} ({value})"
    msg["From"]    = ALERT_EMAIL_SENDER
    msg["To"]      = ALERT_EMAIL_RECIPIENT
    msg.set_content(f"Capteur: {sensor_code}\nValeur: {value}\nTemps: {timestamp}\n{message}")
    for attempt in range(3):
        try:
            await asyncio.sleep(attempt * 5)
            await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                use_tls=True, timeout=30)
            print(f"Mail envoyé pour {sensor_code}")
            return
        except Exception as exc:
            print(f"Erreur mail tentative {attempt+1}/3 : {exc}")
            if attempt == 2:
                print(f"Email abandonné pour {sensor_code} après 3 tentatives")


async def send_alert_config_email(recipients, sensor_prefix, label, level,
                                   value, threshold, custom_message="", timestamp=""):
    # "test" passe toujours même si mute actif
    if level != "test" and _is_muted():
        print(f"[EmailMute] 🔕 Email '{level}' silencieux pour {sensor_prefix} (mute actif)")
        return
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return
    level_labels = {"warning": "⚠️  AVERTISSEMENT", "danger": "🚨 DANGER CRITIQUE", "test": "🔧 TEST"}
    subject_prefix = level_labels.get(level, "ALERTE")
    msg = EmailMessage()
    msg["Subject"] = f"{subject_prefix} — {label} ({sensor_prefix})"
    msg["From"]    = ALERT_EMAIL_SENDER
    msg["To"]      = ", ".join(recipients)
    body = (f"=== {subject_prefix} ===\n\nCapteur    : {label} ({sensor_prefix})\n"
            f"Valeur     : {value}\nSeuil      : {threshold}\nHorodatage : {timestamp}\n")
    if custom_message:
        body += f"\nMessage    : {custom_message}\n"
    body += "\n— Système de supervision Flow\n"
    msg.set_content(body)
    for attempt in range(3):
        try:
            await asyncio.sleep(attempt * 5)
            await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                use_tls=True, timeout=30)
            print(f"[AlertConfig] Email '{level}' envoyé à {recipients} pour {sensor_prefix}")
            return
        except Exception as exc:
            print(f"[AlertConfig] Erreur tentative {attempt+1}/3 : {exc}")


async def send_pdf_via_email(to_emails, subject, pdf_bytes, filename="rapport.pdf"):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"]    = ALERT_EMAIL_SENDER
        msg["To"]      = ", ".join(to_emails)
        msg.set_content("Veuillez trouver le rapport ci-joint.")
        msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
            use_tls=True, timeout=30)
        print(f"Report sent to {', '.join(to_emails)}")
        return True
    except Exception as e:
        print(f"Failed to send report: {e}")
        return False


async def send_credentials_email(to_email, username, password, role):
    msg = EmailMessage()
    msg["Subject"] = "Vos accès Flow - Système de supervision industrielle"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"]   = to_email
    msg.set_content(f"Bonjour {username},\n\nCompte créé.\nNom: {username}\nMDP: {password}\nRôle: {role}\n\nFlow")
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
            use_tls=True, timeout=10)
    except Exception as e:
        print(f"Email non envoyé : {e}")


async def send_update_email(to_email, username, role):
    msg = EmailMessage()
    msg["Subject"] = "Votre compte Flow a été mis à jour"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"]   = to_email
    msg.set_content(f"Bonjour {username},\nCompte modifié.\nNom: {username}\nRôle: {role}\n\nFlow")
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
            username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
            use_tls=True, timeout=10)
    except Exception as e:
        print(f"Email non envoyé : {e}")
