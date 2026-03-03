# seed_users.py
# Run ONCE after the DB tables are created:  python seed_users.py
# This creates the roles and two default users with bcrypt-hashed passwords.

from database import SessionLocal
from models import Role, Utilisateur
from auth import hash_password

def seed_users():
    db = SessionLocal()

    # ── 1. Roles ──────────────────────────────────────────────────────────────
    roles = {}
    for nom in ["admin", "automatician", "viewer"]:
        role = db.query(Role).filter(Role.nom == nom).first()
        if not role:
            role = Role(nom=nom)
            db.add(role)
            db.flush()          # get the id without committing yet
            print(f"✅ Role créé : {nom}")
        roles[nom] = role

    # ── 2. Users ──────────────────────────────────────────────────────────────
    users_to_create = [
        {"username": "admin",   "password": "admin123",   "role": "admin"},
        {"username": "massil",  "password": "massil123",  "role": "automatician"},
    ]

    for u in users_to_create:
        exists = db.query(Utilisateur).filter(Utilisateur.username == u["username"]).first()
        if not exists:
            new_user = Utilisateur(
                username      = u["username"],
                password_hash = hash_password(u["password"]),   # bcrypt hash
                role_id       = roles[u["role"]].id,
            )
            db.add(new_user)
            print(f"✅ Utilisateur créé : {u['username']}  (role: {u['role']})")
        else:
            print(f"ℹ️  Utilisateur déjà existant : {u['username']}")

    db.commit()
    db.close()
    print("\n🎉 Seed terminé. Vous pouvez maintenant vous connecter.")

if __name__ == "__main__":
    seed_users()
