# seed_users.py — Run once to create roles + default users
# python seed_users.py

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
            db.flush()
            print(f"✅ Role créé : {nom}")
        roles[nom] = role

    # ── 2. Default users (with email) ────────────────────────────────────────
    users_to_create = [
        {
            "username": "admin",
            "password": "admin123",
            "email":    "admin@cevital.dz",
            "role":     "admin",
        },
        {
            "username": "massil",
            "password": "massil123",
            "email":    "massil@cevital.dz",
            "role":     "automatician",
        },
    ]

    for u in users_to_create:
        exists = db.query(Utilisateur).filter(Utilisateur.username == u["username"]).first()
        if not exists:
            new_user = Utilisateur(
                username      = u["username"],
                password_hash = hash_password(u["password"]),
                email         = u["email"],
                role_id       = roles[u["role"]].id,
                is_admin      = (u["role"] == "admin"),
            )
            db.add(new_user)
            print(f"✅ Utilisateur créé : {u['username']} ({u['role']}) → {u['email']}")
        else:
            print(f"ℹ️  Déjà existant : {u['username']}")

    db.commit()
    db.close()
    print("\n🎉 Seed terminé.")

if __name__ == "__main__":
    seed_users()
