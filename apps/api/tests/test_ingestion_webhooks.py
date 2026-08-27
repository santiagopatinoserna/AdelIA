"""Tests for Telegram + Postmark webhook handlers."""
from __future__ import annotations

import hashlib
import hmac
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from adelia.config import settings
from adelia.ingestion.email_inbound import (
    _alias_for_user,
    parse_to_address,
    validate_postmark_signature,
)
from adelia.ingestion.telegram_bot import (
    decode_link_token,
    mint_link_token,
    validate_telegram_secret,
)


# ----------------------------------------------------------------------------
# Telegram link tokens
# ----------------------------------------------------------------------------


def test_link_token_roundtrip(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret-32bytes-min")
    user_id = uuid4()
    token = mint_link_token(user_id)
    assert isinstance(token, str)
    decoded = decode_link_token(token)
    assert decoded == user_id


def test_link_token_invalid_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "test-secret-32bytes-min")
    assert decode_link_token("garbage.token.here") is None


def test_link_token_no_secret_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "")
    assert decode_link_token("any") is None


def test_mint_link_token_requires_secret(monkeypatch):
    monkeypatch.setattr(settings, "auth_secret", "")
    with pytest.raises(RuntimeError):
        mint_link_token(uuid4())


# ----------------------------------------------------------------------------
# Telegram webhook signature validation
# ----------------------------------------------------------------------------


def test_telegram_secret_validation_match(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "shared-secret-abc")
    assert validate_telegram_secret("shared-secret-abc") is True


def test_telegram_secret_validation_mismatch(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "shared-secret-abc")
    assert validate_telegram_secret("wrong") is False
    assert validate_telegram_secret(None) is False


def test_telegram_secret_not_configured_rejects_all(monkeypatch):
    monkeypatch.setattr(settings, "telegram_webhook_secret", "")
    assert validate_telegram_secret("anything") is False


# ----------------------------------------------------------------------------
# Postmark signature validation
# ----------------------------------------------------------------------------


def test_postmark_signature_validates_correct_hmac(monkeypatch):
    monkeypatch.setattr(settings, "postmark_inbound_token", "test-token")
    body = b'{"From": "doctor@example.com"}'
    expected = hmac.new(b"test-token", body, hashlib.sha256).hexdigest()
    assert validate_postmark_signature(body, expected) is True


def test_postmark_signature_rejects_wrong():
    body = b'{"x": 1}'
    assert validate_postmark_signature(body, "wrong_sig") is False


def test_postmark_signature_rejects_missing_token(monkeypatch):
    monkeypatch.setattr(settings, "postmark_inbound_token", "")
    assert validate_postmark_signature(b"x", "any") is False


# ----------------------------------------------------------------------------
# Email helpers
# ----------------------------------------------------------------------------


def test_parse_to_address_plain():
    assert parse_to_address("alice@example.com") == "alice@example.com"


def test_parse_to_address_with_name():
    assert parse_to_address('"Alice" <alice@example.com>') == "alice@example.com"


def test_parse_to_address_case_normalized():
    assert parse_to_address("ALICE@EXAMPLE.COM") == "alice@example.com"


def test_parse_to_address_empty_or_invalid():
    assert parse_to_address("") is None
    assert parse_to_address("no-at-sign") is None


def test_alias_for_user_is_deterministic():
    uid = UUID("12345678-1234-5678-1234-567812345678")
    a = _alias_for_user(uid)
    b = _alias_for_user(uid)
    assert a == b
    assert "@" in a
    assert "adelia" in a or "in." in a  # uses settings.adelia_email_domain


# ----------------------------------------------------------------------------
# Telegram update handler
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_update_non_message_ignored():
    from adelia.ingestion.telegram_bot import handle_update

    res = await handle_update({"update_id": 1, "edited_message": {}})
    assert res["action"] == "ignore"


@pytest.mark.asyncio
async def test_handle_update_text_only_message():
    from adelia.ingestion.telegram_bot import handle_update

    update = {
        "message": {
            "chat": {"id": 42},
            "from": {"username": "tester"},
            "text": "hola",
        }
    }
    res = await handle_update(update)
    # Telegram-first diary: text from an unlinked chat gets linking instructions
    # (a linked chat would get a diary entry, see tests/test_telegram_diary.py).
    assert res["action"] == "no_link"
    assert "/start" in res["reply"]


@pytest.mark.asyncio
async def test_handle_update_start_no_token():
    from adelia.ingestion.telegram_bot import handle_update

    update = {
        "message": {
            "chat": {"id": 42},
            "from": {"username": "tester"},
            "text": "/start",
        }
    }
    res = await handle_update(update)
    assert res["action"] == "start_no_token"


@pytest.mark.asyncio
async def test_handle_update_start_invalid_token(monkeypatch):
    from adelia.ingestion.telegram_bot import handle_update
    monkeypatch.setattr(settings, "auth_secret", "test-secret-32bytes-min")

    update = {
        "message": {
            "chat": {"id": 42},
            "from": {"username": "tester"},
            "text": "/start bogus.token.value",
        }
    }
    res = await handle_update(update)
    assert res["action"] == "start_invalid_token"


# ----------------------------------------------------------------------------
# Postmark payload handler
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_postmark_no_recipient():
    from adelia.ingestion.email_inbound import handle_postmark_payload

    res = await handle_postmark_payload({})
    assert res["action"] == "ignore"


@pytest.mark.asyncio
async def test_handle_postmark_unknown_alias(monkeypatch):
    """Email to alias with no AdelIA link → no_link response."""
    from adelia.ingestion import email_inbound
    from adelia import db as db_module

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, *a, **kw):
            return MagicMock(scalar_one_or_none=lambda: None)

    monkeypatch.setattr(db_module, "AsyncSessionLocal", lambda: FakeSession())

    res = await email_inbound.handle_postmark_payload(
        {"To": "abc12345@in.adelia.app"}
    )
    assert res["action"] == "no_link"
