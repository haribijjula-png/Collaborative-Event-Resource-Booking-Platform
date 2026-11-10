from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import settings
from tests.helpers import PASSWORD


def reg(c, **kw):
    body = {"email": "a@example.com", "username": "alice", "full_name": "Alice", "password": PASSWORD, **kw}
    return c.post("/api/auth/register", json=body)


def test_register_and_login(client):
    r = reg(client)
    assert r.status_code == 201 and r.json()["data"]["email"] == "a@example.com"
    assert "hashed_password" not in r.text
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["access_token"] and d["refresh_token"] and d["user"]["username"] == "alice"


def test_register_duplicate_and_weak_password(client):
    reg(client)
    assert reg(client).status_code == 409
    r = reg(client, email="b@example.com", username="bob", password="short")
    assert r.status_code == 422 and r.json()["success"] is False and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_invalid_credentials(client):
    reg(client)
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong-pass1"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}).status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_access_token(client):
    reg(client)
    uid = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]["user"]["id"]
    expired = jwt.encode({"sub": str(uid), "type": "access", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, settings.SECRET_KEY, settings.JWT_ALGORITHM)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_refresh_rotation_and_reuse_detection(client):
    reg(client)
    t = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]
    r = client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 200
    new = r.json()["data"]
    assert new["refresh_token"] != t["refresh_token"]
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 200
    # old token reuse => rejected AND whole family revoked
    r = client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_REUSED"
    assert client.post("/api/auth/refresh", json={"refresh_token": new["refresh_token"]}).status_code == 401


def test_access_token_cannot_be_used_as_refresh(client):
    reg(client)
    t = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]
    assert client.post("/api/auth/refresh", json={"refresh_token": t["access_token"]}).status_code == 401


def test_expired_refresh_token(client):
    reg(client)
    uid = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]["user"]["id"]
    tok = jwt.encode({"sub": str(uid), "type": "refresh", "jti": "x", "exp": datetime.now(timezone.utc) - timedelta(seconds=5)}, settings.SECRET_KEY, settings.JWT_ALGORITHM)
    r = client.post("/api/auth/refresh", json={"refresh_token": tok})
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_logout_revokes_refresh_token(client):
    reg(client)
    t = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]
    assert client.post("/api/auth/logout", json={"refresh_token": t["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_change_password(client):
    reg(client)
    t = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]
    h = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.post("/api/auth/change-password", json={"old_password": "bad-old-pw1", "new_password": "NewPassw0rd"}, headers=h).status_code == 400
    assert client.post("/api/auth/change-password", json={"old_password": PASSWORD, "new_password": "NewPassw0rd"}, headers=h).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401  # sessions revoked
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "NewPassw0rd"}).status_code == 200


def test_inactive_user_cannot_authenticate(client):
    from app.db.session import SessionLocal
    from app.models.models import User
    reg(client)
    t = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD}).json()["data"]
    with SessionLocal() as db:
        db.query(User).update({"is_active": False})
        db.commit()
    r = client.post("/api/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 403 and r.json()["error"]["code"] == "USER_INACTIVE"
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {t['access_token']}"}).status_code == 403
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 403
