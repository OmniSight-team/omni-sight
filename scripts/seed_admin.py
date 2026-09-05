import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "query"))

from omnisight_common import Role

from app.db import SessionLocal
from app.models import User
from app.security import hash_password
from app.settings import settings


def seed_admin() -> None:
    with SessionLocal() as session:
        existing = session.query(User).filter_by(email=settings.admin_email).first()
        if existing:
            print(f"admin account already exists: {existing.email}")
            return

        admin = User(
            email=settings.admin_email,
            password_hash=hash_password(settings.admin_password),
            role=Role.ADMIN,
            is_active=True,
        )
        session.add(admin)
        session.commit()
        print(f"seeded admin account: {admin.email}")


if __name__ == "__main__":
    seed_admin()
