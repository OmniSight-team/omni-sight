"""NFR-9: authentication tokens expire after 15 minutes of inactivity, and an
account locks after 5 consecutive failed login attempts.

Requires Postgres to be up (`docker compose up -d`).
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_password
from app.settings import settings
from omnisight_common import Role

client = TestClient(app)

TEST_EMAIL = "nfr9-lockout-test@omnisight.local"
TEST_PASSWORD = "Nfr9Pass123!"


@pytest.fixture(autouse=True)
def nfr9_user():
    with SessionLocal() as session:
        session.add(
            User(
                email=TEST_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                role=Role.OPERATOR,
                is_active=True,
            )
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter_by(email=TEST_EMAIL).delete(synchronize_session=False)
        session.commit()


def test_five_failed_logins_lock_the_account():
    for _ in range(5):
        resp = client.post("/auth/login", json={"email": TEST_EMAIL, "password": "wrong-password"})
        assert resp.status_code == 401

    with SessionLocal() as session:
        user = session.query(User).filter_by(email=TEST_EMAIL).one()
        assert user.failed_attempts == 5
        assert user.locked_until is not None
        assert user.locked_until > datetime.now(timezone.utc)

    # Sixth attempt, correct password this time — still refused, locked.
    resp = client.post("/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 401


def test_token_past_its_inactivity_window_is_rejected():
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "1",
        "role": "operator",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=1),
    }
    idle_token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")

    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {idle_token}"})
    assert resp.status_code == 401
