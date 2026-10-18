"""TC-10: every protected endpoint rejects requests lacking a valid token or
sufficient role, and accepts one that has both.

Requires Postgres to be up (`docker compose up -d`) — these hit the real
database, the same way the rest of this sprint was verified manually.
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

TEST_PASSWORD = "Tc1010Pass!"
ADMIN_EMAIL = "tc10-admin@omnisight.local"
OPERATOR_EMAIL = "tc10-operator@omnisight.local"

# Every route gated by get_current_user or require_role. /auth/login isn't
# here — it's the public entry point, not a protected route. /health isn't
# either — it's deliberately public.
PROTECTED_GET_ROUTES = ["/auth/me", "/nav", "/admin/ping", "/cameras", "/videos"]


@pytest.fixture(scope="module", autouse=True)
def tc10_users():
    with SessionLocal() as session:
        session.add_all(
            [
                User(
                    email=ADMIN_EMAIL,
                    password_hash=hash_password(TEST_PASSWORD),
                    role=Role.ADMIN,
                    is_active=True,
                ),
                User(
                    email=OPERATOR_EMAIL,
                    password_hash=hash_password(TEST_PASSWORD),
                    role=Role.OPERATOR,
                    is_active=True,
                ),
            ]
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter(User.email.in_([ADMIN_EMAIL, OPERATOR_EMAIL])).delete(
            synchronize_session=False
        )
        session.commit()


@pytest.fixture(scope="module")
def admin_token():
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def operator_token():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _expired_token() -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "1",
        "role": "admin",
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=1),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")


# --- Condition 1: valid token, correct role -> 200 ---


@pytest.mark.parametrize("path", ["/auth/me", "/nav", "/cameras", "/videos"])
def test_valid_token_any_role_returns_200(path, operator_token):
    resp = client.get(path, headers={"Authorization": f"Bearer {operator_token}"})
    assert resp.status_code == 200


def test_admin_ping_valid_admin_token_returns_200(admin_token):
    resp = client.get("/admin/ping", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200


def test_logout_valid_token_returns_200(operator_token):
    resp = client.post("/auth/logout", headers={"Authorization": f"Bearer {operator_token}"})
    assert resp.status_code == 200


# --- Condition 2: valid token, insufficient role -> 403 ---
# Only /admin/ping has a role narrower than "any authenticated user" (that's
# exactly why OMNI-107 added it — to make this path real and testable).


def test_admin_ping_insufficient_role_returns_403(operator_token):
    resp = client.get("/admin/ping", headers={"Authorization": f"Bearer {operator_token}"})
    assert resp.status_code == 403


# --- Condition 3: no token, or expired or invalid -> 401 ---


@pytest.mark.parametrize("path", PROTECTED_GET_ROUTES)
def test_no_token_returns_401(path):
    resp = client.get(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("path", PROTECTED_GET_ROUTES)
def test_expired_token_returns_401(path):
    resp = client.get(path, headers={"Authorization": f"Bearer {_expired_token()}"})
    assert resp.status_code == 401


@pytest.mark.parametrize("path", PROTECTED_GET_ROUTES)
def test_tampered_token_returns_401(path, operator_token):
    # Change a character in the middle of the signature, not the last one: the
    # last base64url character of an HS256 signature carries 2 unused bits, so
    # swapping "A" for "B" there decodes to the same signature (K-22).
    i = operator_token.rindex(".") + 20
    tampered = operator_token[:i] + ("A" if operator_token[i] != "A" else "B") + operator_token[i + 1 :]
    resp = client.get(path, headers={"Authorization": f"Bearer {tampered}"})
    assert resp.status_code == 401


def test_logout_no_token_returns_401():
    resp = client.post("/auth/logout")
    assert resp.status_code == 401
