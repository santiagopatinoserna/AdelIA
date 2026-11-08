"""Guest accounts: the landing's visitor uses the real panel (2026-11-06).

Until this date the demo answered from an in-memory fixture and wrote nothing
(audit 4.6). Santiago's decision of 2026-11-06 reverses that: "la demo es la
app real". A visitor's first question creates a guest, a real `users` row with
a real child, Lucía, whose story (adelia/demo/fixture.py) is seeded as rows of
her own record. From then on every surface (the agent, "Hoy", the history, the
reports, the recorder) reads and writes it exactly as for an account, through
the same Scope(user_id, profile_id), so guests are isolated from each other and
from accounts by the same code that isolates accounts.

Three rules this module keeps:

1. No model call while seeding. The rows are the fixture's text. The only
   network call is the embedding of the record's few texts, done once per text
   EVER (demo_seed_embeddings) and after the response, never holding a session.
2. A guest has no email. `users.email` is NOT NULL and UNIQUE, so it gets a
   synthetic address in the reserved `.invalid` TLD (RFC 2606): it can never
   receive mail nor collide with a mother's address.
3. Saving the account moves the data, it does not rename the guest. The magic
   link may be opened in another browser (the phone's mail app), so the
   account it signs in is whatever Auth.js resolves for that email: a new row
   or an existing account. That account adopts the guest's rows and the guest
   row is deleted, which also kills every session that still points at it. A
   claim token in the link ties the two: the adoption needs the token AND an
   account whose email is the one the claim named, so neither a leaked link
   without the inbox nor an inbox without the link can take a vault.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from adelia.agent.graph import LOCAL_TZ
from adelia.agent.pediatrics import _calendar, resolve_country
from adelia import qa_traffic
from adelia.config import settings
from adelia.db import AsyncSessionLocal
from adelia.demo.fixture import DEFAULT_LOCALE, DEMO_LOCALES, demo_profile
from adelia.models import (
    Chunk, DemoSeedEmbedding, Document, Entity, GuestClaim, Observation, Profile, User,
)
from adelia.services import usage

logger = logging.getLogger(__name__)

GUEST_EMAIL_DOMAIN = "guest.adelia.invalid"
#: As long as the Auth.js magic link the claim rides on (its default maxAge).
CLAIM_TTL = timedelta(hours=24)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# What each fixture item becomes in her record. The diary is not a document:
# it is what the agent writes when she notes something (observations, 0023).
_DOC_SOURCE = {"report": "web", "lab": "web", "consulta": "consulta"}

# The numbers of the fixture as entities, so labs, growth and the briefing read
# them as they read an extracted report. Same values as the fixture's lines.
_LAB_ENTITIES = {
    "es": [("Hemoglobina", 10.8, "g/dL"), ("Ferritina", 18, "ng/mL"),
           ("Leucocitos", 9.2, "x10⁹/L")],
    "en": [("Haemoglobin", 10.8, "g/dL"), ("Ferritin", 18, "ng/mL"),
           ("White cells", 9.2, "x10⁹/L")],
    "fr": [("Hémoglobine", 10.8, "g/dL"), ("Ferritine", 18, "ng/mL"),
           ("Leucocytes", 9.2, "x10⁹/L")],
}
_GROWTH_ENTITIES = {
    "es": [("Peso", 6.4, "kg"), ("Talla", 63, "cm"), ("Perímetro craneal", 41.5, "cm")],
    "en": [("Weight", 6.4, "kg"), ("Length", 63, "cm"), ("Head circumference", 41.5, "cm")],
    "fr": [("Poids", 6.4, "kg"), ("Taille", 63, "cm"), ("Périmètre crânien", 41.5, "cm")],
}
#: Every dose the calendar of her country puts at or before this month is on
#: her vaccination card, so "Hoy" does not open on a false overdue reminder.
_VACCINATED_UP_TO_MONTH = 4


def guest_email(user_id: uuid.UUID) -> str:
    """Her synthetic address. A guest created by test traffic gets the "qa-"
    prefix, which is how the funnel leaves her out of signups and activations
    (adelia/qa_traffic.py). Nothing else reads the address."""
    prefix = qa_traffic.GUEST_EMAIL_PREFIX if qa_traffic.is_qa() else ""
    return f"{prefix}invitado-{user_id}@{GUEST_EMAIL_DOMAIN}"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seed_key(content: str) -> str:
    """The template key of one seeded text: the model is part of it, because a
    vector from another embedder is a different space (docs/MODELOS.md)."""
    return _sha256(f"{settings.mistral_embed_model}\n{content}")


def _locale(locale: str | None) -> str:
    key = (locale or DEFAULT_LOCALE).split("-")[0].lower()
    return key if key in DEMO_LOCALES else DEFAULT_LOCALE


@dataclass
class GuestCreated:
    user_id: uuid.UUID
    profile_id: uuid.UUID
    #: seed_key -> text, for the vectors the template does not have yet.
    missing_embeddings: dict[str, str] = field(default_factory=dict)


async def create_guest(locale: str = DEFAULT_LOCALE, *, today: date | None = None) -> GuestCreated:
    """A guest with Lucía as her default child and Lucía's story as her record.

    One transaction: a half-seeded guest would greet her with a baby and no
    history. `onboarded_at` is stamped because the baby is already known, so
    the panel never sends a guest to the onboarding screen.
    """
    key = _locale(locale)
    today = today or datetime.now(LOCAL_TZ).date()
    story = demo_profile(key, today=today)
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as session:
        user_id = uuid.uuid4()
        session.add(User(id=user_id, email=guest_email(user_id), is_guest=True,
                         onboarded_at=now))
        await session.flush()
        profile = Profile(user_id=user_id, display_name=story["baby_name"],
                          relationship="child", sex="F", is_default=True,
                          date_of_birth=date.fromisoformat(story["date_of_birth"]))
        session.add(profile)
        await session.flush()

        texts: dict[str, str] = {}
        for item in story["items"]:
            if item["kind"] == "diary":
                continue
            day = date.fromisoformat(item["date"])
            stamp = datetime.combine(day, time(10, 0), tzinfo=LOCAL_TZ)
            body = "\n".join([item["title"], item["meta"], *item["lines"]])
            doc = Document(
                user_id=user_id, profile_id=profile.id, source=_DOC_SOURCE[item["kind"]],
                mime_type="text/plain",
                s3_key=f"users/{user_id}/{uuid.uuid4()}-{item['title']}.txt",
                raw_text=body, created_at=stamp, processed_at=now,
                document_metadata={"demo_seed": True, "summary": " ".join(item["lines"])},
            )
            session.add(doc)
            await session.flush()
            content = f"{item['title']} ({item['date']}): {' '.join(item['lines'])}"
            texts[seed_key(content)] = content
            session.add(Chunk(document_id=doc.id, user_id=user_id, profile_id=profile.id,
                              content=content, chunk_index=0,
                              chunk_metadata={"demo_seed": True, "seed_key": seed_key(content)}))
            entities = (_LAB_ENTITIES[key] if item["kind"] == "lab"
                        else _GROWTH_ENTITIES[key] if item["kind"] == "report" else [])
            for name, value, unit in entities:
                session.add(Entity(user_id=user_id, profile_id=profile.id, document_id=doc.id,
                                   entity_type="observation", name=name,
                                   value={"value": value, "unit": unit}, event_date=day,
                                   status="final", provenance="extracted_from_clinician_doc",
                                   raw_quote=f"{name} {value} {unit}"))
            if item["kind"] == "report":
                report_doc, report_day = doc, day

        dob = profile.date_of_birth
        for entry in _calendar(resolve_country(None, key)).get("vaccines", []):
            if entry["due_month"] > _VACCINATED_UP_TO_MONTH:
                continue
            given = dob + timedelta(days=int(entry["due_month"] * 30.4))
            session.add(Entity(user_id=user_id, profile_id=profile.id,
                               document_id=report_doc.id, entity_type="immunization",
                               name=entry["name"], event_date=min(given, report_day),
                               status="completed", provenance="extracted_from_clinician_doc"))

        diary = next(i for i in story["items"] if i["kind"] == "diary")
        night = datetime.combine(date.fromisoformat(diary["date"]), time(21, 30), tzinfo=LOCAL_TZ)
        session.add(Observation(user_id=user_id, profile_id=profile.id, kind="sleep",
                                value=5, unit="h", text=diary["lines"][0],
                                observed_at=night, source="telegram"))

        known = {
            row[0]: row[1]
            for row in (await session.execute(
                sa.select(DemoSeedEmbedding.content_sha256, DemoSeedEmbedding.embedding)
                .where(DemoSeedEmbedding.content_sha256.in_(list(texts)))
            )).all()
        }
        if known:
            for sha, vector in known.items():
                await session.execute(
                    sa.update(Chunk)
                    .where(Chunk.user_id == user_id,
                           Chunk.chunk_metadata["seed_key"].astext == sha)
                    .values(embedding=vector)
                )
        await session.commit()

    return GuestCreated(
        user_id=user_id, profile_id=profile.id,
        missing_embeddings={k: v for k, v in texts.items() if k not in known},
    )


@usage.in_surface("guest")
async def fill_seed_embeddings(user_id: uuid.UUID, missing: dict[str, str]) -> int:
    """Embed the texts the template lacks, store them once, give them to this guest.

    Runs after the response. Best effort: without a key (CI, a dev box) the
    guest keeps a record the agent cannot retrieve by meaning, and "Hoy", the
    history, the labs and the reports still read it from their own rows.
    """
    if not missing:
        return 0
    from adelia.workers.embed import embed_texts

    keys = list(missing)
    try:
        vectors = await embed_texts([missing[k] for k in keys])
    except Exception as exc:  # noqa: BLE001 — no key or an outage: seeded without vectors
        logger.warning("guest seed embeddings skipped: %s", type(exc).__name__)
        return 0
    async with AsyncSessionLocal() as session:
        for sha, vector in zip(keys, vectors):
            await session.execute(
                pg_insert(DemoSeedEmbedding)
                .values(content_sha256=sha, embedding=vector)
                .on_conflict_do_nothing()
            )
            await session.execute(
                sa.update(Chunk)
                .where(Chunk.user_id == user_id, Chunk.chunk_metadata["seed_key"].astext == sha)
                .values(embedding=vector)
            )
        await session.commit()
    return len(keys)


# --- "Guardar mi cuenta" ----------------------------------------------------


class ClaimError(Exception):
    """The claim cannot be honoured; the message is for logs, not for her."""


def normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL.match(value) or value.endswith(f"@{GUEST_EMAIL_DOMAIN}") or len(value) > 254:
        raise ClaimError("not an email")
    return value


async def create_claim(guest_id: uuid.UUID, email: str) -> str:
    """A token for the magic link that will save this guest under `email`.

    A new claim replaces the previous one: she may mistype the address and ask
    again, and only the last link she asked for should work.
    """
    address = normalise_email(email)
    token = secrets.token_urlsafe(32)
    async with AsyncSessionLocal() as session:
        guest = await session.get(User, guest_id)
        if guest is None or not guest.is_guest:
            raise ClaimError("not a guest")
        await session.execute(sa.delete(GuestClaim).where(GuestClaim.guest_id == guest_id))
        session.add(GuestClaim(token_hash=_sha256(token), guest_id=guest_id, email=address,
                               expires_at=datetime.now(timezone.utc) + CLAIM_TTL))
        await session.commit()
    return token


# Tables that hold at most one row per user: on adoption the account's own row
# wins and the guest's is dropped instead of colliding on the key. A PARTIAL
# unique index (one default profile per user) is not one of them: Lucía must
# move, only her default flag yields, which adopt_guest clears beforehand.
_ONE_PER_USER = sa.text(
    """
    SELECT c.relname FROM pg_index i
    JOIN pg_class c ON c.oid = i.indrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = i.indkey[0]
    WHERE i.indisunique AND i.indnatts = 1 AND a.attname = 'user_id' AND i.indpred IS NULL
    """
)
_WITH_USER_ID = sa.text(
    """
    SELECT table_name FROM information_schema.columns
    WHERE table_schema = 'public' AND column_name = 'user_id'
      AND table_name IN (SELECT table_name FROM information_schema.tables
                         WHERE table_schema = 'public' AND table_type = 'BASE TABLE')
    """
)


async def adopt_guest(*, token: str, user_id: uuid.UUID) -> uuid.UUID:
    """Move the claimed guest's whole vault to `user_id`; returns the guest's id.

    Every table with a `user_id` column is moved, read from the catalogue
    rather than listed here, so a table added later cannot be left behind
    (and stranded under a deleted user, or erased with it). Then the guest
    row goes, cascading the claim and any row that was not moved.
    """
    async with AsyncSessionLocal() as session:
        claim = await session.get(GuestClaim, _sha256(token or ""))
        if claim is None or claim.expires_at <= datetime.now(timezone.utc):
            raise ClaimError("unknown or expired claim")
        account = await session.get(User, user_id)
        guest = await session.get(User, claim.guest_id)
        if account is None or guest is None or not guest.is_guest:
            raise ClaimError("nothing to adopt")
        if account.id == guest.id or account.email.lower() != claim.email:
            raise ClaimError("the claim names another email")

        has_default = await session.scalar(
            sa.select(sa.func.count()).select_from(Profile).where(
                Profile.user_id == account.id, Profile.is_default.is_(True),
                Profile.deleted_at.is_(None))
        )
        if has_default:
            await session.execute(
                sa.update(Profile).where(Profile.user_id == guest.id).values(is_default=False)
            )

        one_per_user = {row[0] for row in (await session.execute(_ONE_PER_USER)).all()}
        tables = sorted({row[0] for row in (await session.execute(_WITH_USER_ID)).all()})
        params = {"guest": guest.id, "account": account.id}
        for table in tables:
            if table in one_per_user:
                await session.execute(sa.text(
                    f'DELETE FROM "{table}" WHERE user_id = :guest AND EXISTS '
                    f'(SELECT 1 FROM "{table}" WHERE user_id = :account)'), params)
            await session.execute(
                sa.text(f'UPDATE "{table}" SET user_id = :account WHERE user_id = :guest'), params)

        if account.onboarded_at is None:
            account.onboarded_at = datetime.now(timezone.utc)
        await session.execute(sa.delete(User).where(User.id == guest.id))
        await session.commit()
        logger.info("guest %s adopted by user %s", guest.id, account.id)
        return guest.id
