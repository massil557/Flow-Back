from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Utilisateur, Role
from app.schemas import UserCreate_Admin, UserUpdate_Admin, UserOut
from app.utils.auth_utils import hash_password, generate_temp_password
from app.services.email_service import send_credentials_email, send_update_email
from .auth import get_current_user

router = APIRouter(prefix="/admin", tags=["Admin"])

def require_admin(current_user: UserOut = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Acces reserve aux administrateurs")
    return current_user

@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: UserOut = Depends(require_admin)):
    users = db.query(Utilisateur).all()
    result = []
    for u in users:
        role = db.query(Role).filter(Role.id == u.role_id).first()
        result.append(UserOut(id=u.id, username=u.username, email=u.email, role=role.nom if role else "unknown"))
    return result

@router.post("/users", response_model=UserOut)
async def create_user(payload: UserCreate_Admin, db: Session = Depends(get_db), _: UserOut = Depends(require_admin)):
    if db.query(Utilisateur).filter(Utilisateur.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Ce nom d'utilisateur existe deja")
    if db.query(Utilisateur).filter(Utilisateur.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Cet email est deja utilise")
    role = db.query(Role).filter(Role.nom == payload.role).first()
    if not role:
        raise HTTPException(status_code=400, detail=f"Role inconnu : {payload.role}")
    temp_password = generate_temp_password()
    new_user = Utilisateur(
        username=payload.username, email=payload.email,
        password_hash=hash_password(temp_password), role_id=role.id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    await send_credentials_email(payload.email, payload.username, temp_password, payload.role)
    return UserOut(id=new_user.id, username=new_user.username, email=new_user.email, role=role.nom)

@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, payload: UserUpdate_Admin, db: Session = Depends(get_db), _: UserOut = Depends(require_admin)):
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if payload.username:
        user.username = payload.username
    if payload.email:
        user.email = payload.email
    if payload.role:
        role = db.query(Role).filter(Role.nom == payload.role).first()
        if not role:
            raise HTTPException(status_code=400, detail=f"Role inconnu : {payload.role}")
        user.role_id = role.id
    db.commit()
    db.refresh(user)
    role_obj = db.query(Role).filter(Role.id == user.role_id).first()
    if user.email:
        await send_update_email(user.email, user.username, role_obj.nom if role_obj else "unknown")
    return UserOut(id=user.id, username=user.username, email=user.email, role=role_obj.nom if role_obj else "unknown")

@router.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), _: UserOut = Depends(require_admin)):
    user = db.query(Utilisateur).filter(Utilisateur.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    db.delete(user)
    db.commit()
    return {"success": True, "deleted_id": user_id}