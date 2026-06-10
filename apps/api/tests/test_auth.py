from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import JWTError, jwt

from adelia.auth import decode_session_token, get_current_user_id
from adelia.config import settings


def make_token(sub: str, exp_in_seconds: int = 3600) -> str:
    payload = {
        "sub": sub,
        "email": f"{sub}@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=exp_in_seconds),
    }
    return jwt.encode(payload, settings.auth_secret or "test-secret", algorithm="HS256")


def test_decode_valid_token():
    settings.auth_secret = "test-secret"
    token = make_token("11111111-1111-1111-1111-111111111111")
    payload = decode_session_token(token)
    assert payload["sub"] == "11111111-1111-1111-1111-111111111111"


def test_decode_expired_token_raises():
    settings.auth_secret = "test-secret"
    token = make_token("u1", exp_in_seconds=-10)
    with pytest.raises(JWTError):
        decode_session_token(token)


def _make_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user_id=Depends(get_current_user_id)):
        return {"user_id": str(user_id)}

    return app


async def test_get_current_user_id_valid_token_returns_uuid(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from tests.db_helpers import make_user

    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    user_uuid = str(await make_user())
    token = make_token(user_uuid)
    transport = ASGITransport(app=_make_test_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            "/whoami", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    assert response.json() == {"user_id": user_uuid}


def test_get_current_user_id_unknown_user_returns_401(monkeypatch):
    """A valid signature whose sub no longer exists (erased account) is 401 —
    tokens must not outlive the user row."""
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = make_token("11111111-1111-1111-1111-111111111111")
    client = TestClient(_make_test_app())

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Unknown user"


def test_get_current_user_id_malformed_uuid_returns_401(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    token = make_token("not-a-uuid")
    client = TestClient(_make_test_app())

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert "not a valid UUID" in response.json()["detail"]


def test_get_current_user_id_invalid_signature_returns_401(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    # token signed with a different secret
    user_uuid = "11111111-1111-1111-1111-111111111111"
    payload = {
        "sub": user_uuid,
        "email": "x@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=3600),
    }
    bad_token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
    client = TestClient(_make_test_app())

    response = client.get("/whoami", headers={"Authorization": f"Bearer {bad_token}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid token"


def test_get_current_user_id_missing_sub_returns_401(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    payload = {
        "email": "x@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=3600),
    }
    token_no_sub = jwt.encode(payload, "test-secret", algorithm="HS256")
    client = TestClient(_make_test_app())

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token_no_sub}"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Token missing sub"


def test_empty_secret_rejects_all_tokens_with_503(monkeypatch):
    """Empty AUTH_SECRET must NOT silently accept tokens signed with "" —
    that would let anyone forge a session (v0.1.1 security carry-over)."""
    monkeypatch.setattr(settings, "auth_secret", "")
    forged = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "exp": datetime.now(timezone.utc) + timedelta(seconds=3600),
        },
        "",
        algorithm="HS256",
    )
    client = TestClient(_make_test_app())

    response = client.get("/whoami", headers={"Authorization": f"Bearer {forged}"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Server auth not configured"


def test_decode_with_empty_secret_raises_runtime_error(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "")
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        decode_session_token("whatever")
