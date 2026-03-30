import os
from dotenv import load_dotenv

load_dotenv()

# CORS — allow all Vite dev-server origins
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Email
ALERT_EMAIL_SENDER = os.getenv("ALERT_EMAIL_SENDER", "mascioul8@gmail.com")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD")
ALERT_EMAIL_RECIPIENT = os.getenv("ALERT_EMAIL_RECIPIENT", "ademoulhaci123@gmail.com")

# Manager email for reports
MANAGER_EMAIL = os.getenv("MANAGER_EMAIL", "manager@cevital.dz")

# OPC UA
OPC_URL = "opc.tcp://127.0.0.1:4840/freeopcua/server/"

# Sensor thresholds
SENSOR_THRESHOLDS = {
    'TEMP': 30.0,
    'PRES': 4.0,
    'HUMI': 80.0,
    'CO2': 900.0,
}
DEFAULT_THRESHOLD = 30.0

def get_threshold(code_unique: str) -> float:
    for prefix, val in SENSOR_THRESHOLDS.items():
        if prefix in code_unique.upper():
            return val
    return DEFAULT_THRESHOLD

# Email cooldown
EMAIL_COOLDOWN_SECONDS = 300

# JWT Configuration (read from environment, with fallback defaults)
SECRET_KEY = os.getenv("SECRET_KEY", "CHANGE_ME_TO_A_LONG_RANDOM_SECRET")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))
