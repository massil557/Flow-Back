"""
set_admin.py — Set a user as admin by username or email.

Usage:
  python set_admin.py admin          # Set user 'admin' as admin
  python set_admin.py massil         # Set user 'massil' as admin
  python set_admin.py --email user@example.com  # Set by email
"""

import sys
from database import SessionLocal
from models import Utilisateur


def set_admin(username: str = None, email: str = None):
    db = SessionLocal()

    query = db.query(Utilisateur)
    if username:
        user = query.filter(Utilisateur.username == username).first()
    elif email:
        user = query.filter(Utilisateur.email == email).first()
    else:
        print("Usage: python set_admin.py <username>  OR  python set_admin.py --email <email>")
        sys.exit(1)

    if not user:
        print(f"User not found: {username or email}")
        sys.exit(1)

    user.is_admin = True
    db.commit()
    print(f"User '{user.username}' is now an admin (is_admin=True).")
    db.close()


if __name__ == "__main__":
    if len(sys.argv) == 2:
        set_admin(username=sys.argv[1])
    elif len(sys.argv) == 3 and sys.argv[1] == "--email":
        set_admin(email=sys.argv[2])
    else:
        print("Usage: python set_admin.py <username>")
        print("       python set_admin.py --email <email>")
        sys.exit(1)
