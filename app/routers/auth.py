from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Utilisateur, Role
from app.schemas import TokenResponse, UserPublic, ChangePasswordRequest
from app.utils.auth_utils import hash_password, verify_password, create_access_token, decode_access_token

router = APIRouter(prefix="/auth", tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Dependency to get current user
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserPublic:
    credentials_exc = HTTPException(
        status_code=401, detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exc
    username: str = payload.get("sub")
    if not username:
        raise credentials_exc
    user = db.query(Utilisateur).filter(Utilisateur.username == username).first()
    if not user:
        raise credentials_exc
    role = db.query(Role).filter(Role.id == user.role_id).first()
    return UserPublic(id=user.id, username=user.username, role=role.nom if role else "unknown", is_admin=user.is_admin)

@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(Utilisateur).filter(Utilisateur.username == form_data.username).first()
    dummy_hash = "$2b$12$xA.2HpCbll4WXagQ3kbfvu34V5u0H67Wsff2U3Sv7Unycd/hOCeb6"
    valid = verify_password(form_data.password, user.password_hash if user else dummy_hash)
    if not user or not valid:
        raise HTTPException(status_code=401, detail="Nom d'utilisateur ou mot de passe incorrect", headers={"WWW-Authenticate": "Bearer"})
    role = db.query(Role).filter(Role.id == user.role_id).first()
    token = create_access_token({"sub": user.username, "user_id": user.id, "role": role.nom if role else "unknown"})
    return {"access_token": token, "token_type": "bearer"}

def require_admin(current_user: UserPublic = Depends(get_current_user)):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Acces reserve aux administrateurs"
        )
    return current_user


@router.get("/me", response_model=UserPublic)
def read_me(current_user: UserPublic = Depends(get_current_user)):
    return current_user

@router.patch("/change-password")
def change_password(payload: ChangePasswordRequest, current_user: UserPublic = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.query(Utilisateur).filter(Utilisateur.id == current_user.id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Le mot de passe doit faire au moins 6 caracteres")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"success": True}