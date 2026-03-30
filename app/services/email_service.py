import asyncio
import aiosmtplib
from email.message import EmailMessage
from app.config import ALERT_EMAIL_SENDER, ALERT_EMAIL_PASSWORD, ALERT_EMAIL_RECIPIENT

async def send_alert_email(sensor_code: str, value: float, timestamp: str, message: str):
    if not ALERT_EMAIL_SENDER or not ALERT_EMAIL_PASSWORD:
        return
    msg = EmailMessage()
    msg["Subject"] = f"ALERTE : {sensor_code} ({value})"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = ALERT_EMAIL_RECIPIENT
    msg.set_content(f"Capteur: {sensor_code}\nValeur: {value}\nTemps: {timestamp}\n{message}")
    for attempt in range(3):
        try:
            await asyncio.sleep(attempt * 5)
            await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                                  username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                                  use_tls=True, timeout=30)
            print(f"Mail envoye pour {sensor_code}")
            return
        except Exception as exc:
            print(f"Erreur mail tentative {attempt+1}/3 : {exc}")
            if attempt == 2:
                print(f"Email abandonne pour {sensor_code} apres 3 tentatives")

async def send_pdf_via_email(to_emails: list, subject: str, pdf_bytes: bytes, filename: str = "rapport.pdf"):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = ALERT_EMAIL_SENDER
        msg["To"] = ", ".join(to_emails)
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

async def send_credentials_email(to_email: str, username: str, password: str, role: str):
    msg = EmailMessage()
    msg["Subject"] = "Vos acces Flow - Systeme de supervision industrielle"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = to_email
    msg.set_content(
        f"Bonjour {username},\n\n"
        f"Un compte a ete cree pour vous sur la plateforme Flow.\n\n"
        f"  Nom d'utilisateur : {username}\n"
        f"  Mot de passe temporaire : {password}\n"
        f"  Role : {role}\n\n"
        f"Cordialement,\nL'equipe Flow"
    )
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                              username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                              use_tls=True, timeout=10)
        print(f"Credentials envoyes a {to_email}")
    except Exception as e:
        print(f"Email non envoye : {e}")

async def send_update_email(to_email: str, username: str, role: str):
    msg = EmailMessage()
    msg["Subject"] = "Votre compte Flow a ete mis a jour"
    msg["From"] = ALERT_EMAIL_SENDER
    msg["To"] = to_email
    msg.set_content(
        f"Bonjour {username},\n\n"
        f"Votre compte a ete modifie.\n"
        f"  Nom d'utilisateur : {username}\n"
        f"  Role : {role}\n\n"
        f"Cordialement,\nL'equipe Flow"
    )
    try:
        await aiosmtplib.send(msg, hostname="smtp.gmail.com", port=465,
                              username=ALERT_EMAIL_SENDER, password=ALERT_EMAIL_PASSWORD,
                              use_tls=True, timeout=10)
    except Exception as e:
        print(f"Email non envoye : {e}")