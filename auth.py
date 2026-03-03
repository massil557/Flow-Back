# auth.py  — bcrypt password hashing + HS256 JWT
# Uses bcrypt directly (no passlib) — compatible with bcrypt 4.x and Python 3.13

import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt

# ── Config ────────────────────────────────────────────────────────────────────
# Generate a strong secret with:
#   python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
ALGORITHM  = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 8   # 8 hours

# ── Bcrypt ────────────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    """Hash a plain-text password with bcrypt. Call when creating a user."""
    password_bytes = plain.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")

def verify_password(plain: str, hashed: str) -> bool:
    """Compare a plain password against a stored bcrypt hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

# ── JWT ───────────────────────────────────────────────────────────────────────
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    expire  = datetime.utcnow() + (expires_delta or timedelta(minutes=TOKEN_EXPIRE_MINUTES))
    payload.update({"exp": expire})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_access_token(token: str) -> Optional[dict]:
    """Returns decoded payload dict, or None if token is invalid/expired."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
