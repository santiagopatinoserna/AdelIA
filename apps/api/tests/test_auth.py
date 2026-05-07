from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

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
    with pytest.raises(Exception):
        decode_session_token(token)
