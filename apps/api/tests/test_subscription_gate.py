"""The paywall lives in the API, on the routes that spend money.

Audit 4.1 (crítico): ACTIVE_STATUSES was read nowhere but routers/billing.py,
and the only check in the whole product was
apps/web/app/[locale]/dashboard/layout.tsx, whose comment documented its own
escape hatch ("genuine fetch error -> allow access (fail open)"). Any valid
JWT reached documents, chat, briefings, the agent, enrichment and ingestion,
spending Mistral OCR/Voxtral credit with no ceiling, and a linked Telegram
chat kept ingesting long after the trial expired.

The first fix put the dependency on six APIRouter objects, which was too wide:
it also closed the reads and the deletes, so a mother who cancelled could not
see her baby's records, could not erase a single document, and could not reach
the settings screen that holds "export my data". GDPR art. 15, 17 and 20 are
not features one stops paying for. The gate now sits on the routes that cost:
uploads (Mistral OCR/Voxtral), chat turns, agent turns, briefing generation,
share-link creation, PDF rendering, and the two spend-only routers.

PG-gated like tests/test_audio_retention.py: the gate reads a real
users.subscription_status row.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.models import User

from tests.db_helpers import make_user
from tests.pg_gate import PG_AVAILABLE
from tests.test_auth import make_token

pytestmark = pytest.mark.skipif(
    not PG_AVAILABLE, reason="PG required — run locally with docker compose up postgres"
)


class _SilentProvider:
    """POST /agent/turn is one of the paid routes; a 200 reaches the SSE body,
    where get_provider() would raise for lack of an LLM key. The gate is what
    is under test, not the model."""

    async def stream_step(self, *, system, messages, tools):
        yield {"type": "token", "text": "ok"}
        yield {"type": "stop", "stop_reason": "end_turn"}


@pytest.fixture(autouse=True)
def _agent_provider():
    with patch("adelia.agent.orchestrator.get_provider", return_value=_SilentProvider()):
        yield


@pytest.fixture(autouse=True)
def _billing_configured(monkeypatch):
    """Every case here is about a deployment that SELLS something.

    has_active_subscription short-circuits to True when STRIPE_SECRET_KEY is
    empty, because an instance where checkout answers 503 can never move an
    account out of "none" and would otherwise lock its owner out of her own
    data (see test_a_self_hosted_instance_without_stripe_is_not_paywalled).
    The test settings have no key, so the paywall cases have to declare one.
    """
    monkeypatch.setattr(settings, "auth_secret", "test-secret")
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_gate")


async def _headers(status_value: str = "none") -> dict[str, str]:
    user_id = await make_user(subscription_status=status_value)
    return {"Authorization": f"Bearer {make_token(str(user_id))}"}


# One route per guarded group. These SPEND: OCR/Voxtral, LLM turns, the
# 5-stage briefing pipeline, a public link, a rendered PDF.
PAID_ROUTES = [
    ("documents-upload", "POST", "/documents"),
    ("chat-turn", "POST", "/chat"),
    ("briefings-generate", "POST", "/briefings"),
    ("agent-turn", "POST", "/agent/turn"),
    ("enrichment", "GET", "/enrichment/coverage"),
    ("ingestion", "GET", "/ingestion/guides"),
    ("shares-create", "POST", "/shares"),
]

# These do NOT spend, and are the parent's own data or her own GDPR doors.
FREE_ROUTES = [
    ("documents-list", "GET", "/documents"),
    ("chat-sessions", "GET", "/chat/sessions"),
    ("briefings-list", "GET", "/briefings"),
    ("agent-suggestions", "GET", "/agent/suggestions"),
    ("shares-list", "GET", "/shares"),
    ("data-export", "GET", "/users/me/export"),
]


async def _call(client, method: str, path: str, headers: dict[str, str]):
    if method == "POST":
        if path == "/documents":
            return await client.post(
                path,
                headers=headers,
                files={"file": ("informe.pdf", b"%PDF-1.4 fake", "application/pdf")},
            )
        return await client.post(path, headers=headers, json={})
    return await client.get(path, headers=headers)


@pytest.mark.parametrize("group,method,path", PAID_ROUTES)
async def test_inactive_subscription_gets_402_on_every_paid_route(
    client, group, method, path
):
    resp = await _call(client, method, path, await _headers("none"))

    assert resp.status_code == 402, f"{group}: {resp.status_code} {resp.text}"
    assert resp.json()["detail"] == "Subscription required"


@pytest.mark.parametrize("group,method,path", PAID_ROUTES)
async def test_active_subscription_is_not_paywalled(client, group, method, path):
    """Control: the same routes with a live subscription never answer 402."""
    resp = await _call(client, method, path, await _headers("active"))

    assert resp.status_code != 402, f"{group}: {resp.text}"


@pytest.mark.parametrize("group,method,path", FREE_ROUTES)
async def test_a_canceled_user_keeps_her_gdpr_doors(client, group, method, path):
    """Art. 15 (access), 17 (erasure) and 20 (portability): cancelling cannot
    close her own records, her exports, or her ability to pull back a public
    link to her baby's history."""
    resp = await _call(client, method, path, await _headers("canceled"))

    assert resp.status_code != 402, f"{group}: {resp.status_code} {resp.text}"


async def test_a_canceled_user_can_still_erase_a_document(client, monkeypatch):
    """Erasure is the one that cannot wait for a payment: DELETE used to sit
    behind the router-level dependency and answer 402."""
    from adelia.models import Document
    from adelia.routers import documents as docs_mod

    async def _put(key, body, content_type=None):
        return None

    async def _noop_process(document_id, mime_type, is_consulta=False):
        return None

    async def _delete(key):
        return None

    monkeypatch.setattr(docs_mod.storage, "put_object", _put)
    monkeypatch.setattr(docs_mod, "process_document", _noop_process)
    # Let the REAL sweep run with S3 stubbed, so the tombstone this delete
    # writes is consumed here instead of being left for whichever test runs
    # next (tests/test_audio_retention.py asserts on the whole table).
    monkeypatch.setattr("adelia.routers.users.storage.delete_object", _delete)

    # Upload while she is paying, cancel, then erase.
    user_id = await make_user(subscription_status="active")
    headers = {"Authorization": f"Bearer {make_token(str(user_id))}"}
    created = await client.post(
        path := "/documents",
        headers=headers,
        files={"file": ("informe.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert created.status_code == 201, created.text
    doc_id = created.json()["id"]

    async with AsyncSessionLocal() as session:
        user = await session.get(User, user_id)
        user.subscription_status = "canceled"
        await session.commit()

    resp = await client.delete(f"{path}/{doc_id}", headers=headers)
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as session:
        assert await session.get(Document, uuid.UUID(doc_id)) is None


@pytest.mark.parametrize("status_value", ["trialing", "active"])
async def test_both_active_statuses_pass_the_gate(client, status_value):
    """ACTIVE_STATUSES is {trialing, active}: a mom inside her free trial has
    not paid yet and must still get the product."""
    resp = await client.get(
        "/enrichment/coverage", headers=await _headers(status_value)
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "status_value", ["none", "past_due", "canceled", "unpaid", "incomplete"]
)
async def test_every_non_active_stripe_status_is_refused(client, status_value):
    resp = await client.get(
        "/enrichment/coverage", headers=await _headers(status_value)
    )

    assert resp.status_code == 402, resp.text


async def test_billing_and_health_stay_reachable_without_a_subscription(client):
    """The way out of a 402 must never be behind the 402. /billing/status is
    what the web reads to decide where to send her, and /health is the probe."""
    headers = await _headers("none")

    status_resp = await client.get("/billing/status", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["active"] is False

    assert (await client.get("/health")).status_code == 200


async def test_upload_is_refused_before_any_blob_is_written(client, monkeypatch):
    """A 402 must cost nothing: the route dependency runs before the handler,
    so the S3 put and the Mistral pipeline never start."""
    from adelia.routers import documents as docs_mod

    puts: list[str] = []

    async def _put(key, body, content_type=None):
        puts.append(key)

    monkeypatch.setattr(docs_mod.storage, "put_object", _put)

    resp = await client.post(
        "/documents",
        headers=await _headers("none"),
        files={"file": ("informe.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert resp.status_code == 402
    assert puts == []


async def test_the_public_share_viewer_is_never_paywalled(client):
    """/s/{token} is read by a pediatrician with no account at all. A
    router-level dependency on sharing.py would have closed it, which is why
    the gate there is per route."""
    resp = await client.get("/s/definitely-not-a-real-token")

    assert resp.status_code != 402
    assert resp.status_code in (404, 410), resp.text


async def test_subscription_status_defaults_to_none_for_a_fresh_user():
    """The column's server_default is what the gate reads on a brand-new
    account, so a signup with no checkout is refused by default."""
    async with AsyncSessionLocal() as session:
        user = User(email=f"fresh-{uuid.uuid4()}@adelia.test")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        user_id = user.id

    from adelia.auth import has_active_subscription, subscription_status_for

    assert await subscription_status_for(user_id) == "none"
    assert await has_active_subscription(user_id) is False


# --- Self-hosting (audit follow-up) -----------------------------------------
#
# users.subscription_status is written by exactly one thing: the Stripe
# webhook (routers/billing.py). Without STRIPE_SECRET_KEY that webhook never
# fires and /billing/checkout answers 503, so on the AGPL install the README
# documents ("## Self-host") no account could ever leave "none" and every
# product route answered 402 forever, with no documented way back in.


async def test_a_self_hosted_instance_without_stripe_is_not_paywalled(
    client, monkeypatch
):
    monkeypatch.setattr(settings, "stripe_secret_key", "")

    resp = await client.get("/documents", headers=await _headers("none"))

    assert resp.status_code == 200, resp.text


async def test_a_self_hosted_instance_can_also_spend(client, monkeypatch):
    """Not just the reads: the whole point is that the instance works."""
    monkeypatch.setattr(settings, "stripe_secret_key", "")

    resp = await client.get(
        "/enrichment/coverage", headers=await _headers("none")
    )

    assert resp.status_code == 200, resp.text


async def test_configuring_stripe_turns_the_paywall_back_on(client, monkeypatch):
    """Anti-regression control for the audit's original 4.1 goal: the SaaS,
    where the key IS set, still refuses an account that is not paying."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")

    resp = await client.get(
        "/enrichment/coverage", headers=await _headers("none")
    )

    assert resp.status_code == 402, resp.text
