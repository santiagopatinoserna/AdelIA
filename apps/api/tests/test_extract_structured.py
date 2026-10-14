"""Schema-enforced extraction, observable drops, and the repeated-quote rule.

No test here needs a live key except the one explicitly gated on it. The
provider is faked at the `chat.complete_async` boundary, which is where the
real client is called, so the request the extractor builds (response_format,
fallback order) is what is asserted, not an internal helper.
"""
from __future__ import annotations

import io
import json
import logging
import typing
import uuid
from types import SimpleNamespace

import httpx
import pytest
import sqlalchemy as sa
from mistralai.client.errors import SDKError

from adelia.config import settings
from adelia.models import Chunk, Document, Entity
from adelia.schemas import DROP_REASONS, ExtractedEntity, ExtractionReport
from adelia.workers import extract as extract_mod
from adelia.workers.extract import (
    ExtractionResult,
    extract_entities,
    extraction_json_schema,
    locate_quote,
    quote_is_verbatim,
    quote_occurrences,
)
from tests.pg_gate import PG_AVAILABLE

DOC = (
    "Informe de alta.\n"
    "Alergia: penicilina.\n"
    "Tratamiento actual: Metformina 500 mg cada 12 horas.\n"
    "Hemoglobina 12,1 g/dL.\n"
)

# One phrase, "negativo", three times: the case find() got wrong.
REPEATED = (
    "Prueba VIH: negativo.\n"
    "Prueba estreptococo: negativo.\n"
    "Prueba hepatitis B: negativo.\n"
)


def _ent(**over) -> dict:
    base = {
        "entity_type": "allergy",
        "name": "Penicilina",
        "raw_quote": "Alergia: penicilina",
        "confidence": 0.9,
    }
    return {**base, **over}


def _reply(*entities: dict) -> str:
    return json.dumps({"entities": list(entities)})


def _sdk_error(status: int) -> SDKError:
    request = httpx.Request("POST", "https://api.mistral.ai/v1/chat/completions")
    return SDKError(f"HTTP {status}", httpx.Response(status, request=request, text="nope"))


class _FakeChat:
    """Answers per requested response_format type; an Exception value is raised."""

    def __init__(self, by_format: dict):
        self.by_format = by_format
        self.calls: list[dict] = []

    async def complete_async(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.by_format[kwargs["response_format"]["type"]]
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def formats(self) -> list[str]:
        return [c["response_format"]["type"] for c in self.calls]


def _provider(monkeypatch, **by_format) -> _FakeChat:
    chat = _FakeChat(by_format)
    monkeypatch.setattr(extract_mod, "get_mistral_client", lambda: SimpleNamespace(chat=chat))
    return chat


# --- One definition of an extracted entity ------------------------------------

def test_schema_is_derived_from_the_entity_model():
    schema = extraction_json_schema()
    item = schema["properties"]["entities"]["items"]

    assert schema["required"] == ["entities"]
    assert set(item["properties"]) == set(ExtractedEntity.model_fields)
    assert set(item["required"]) == {
        name for name, f in ExtractedEntity.model_fields.items() if f.is_required()
    }
    entity_types = typing.get_args(ExtractedEntity.model_fields["entity_type"].annotation)
    assert item["properties"]["entity_type"]["enum"] == list(entity_types)
    assert item["properties"]["confidence"]["minimum"] == 0.0
    assert item["properties"]["confidence"]["maximum"] == 1.0


def test_every_schema_field_is_a_column_of_the_entities_table():
    columns = set(Entity.__table__.columns.keys())
    assert set(ExtractedEntity.model_fields) <= columns


# --- Request path ---------------------------------------------------------------

async def test_asks_for_schema_enforced_output_first(monkeypatch):
    chat = _provider(monkeypatch, json_schema=_reply(_ent()))

    out = await extract_entities(DOC)

    assert chat.formats == ["json_schema"]
    fmt = chat.calls[0]["response_format"]["json_schema"]
    assert fmt["strict"] is True
    assert fmt["schema"] == extraction_json_schema()
    assert chat.calls[0]["model"] == "mistral-medium-latest"
    assert chat.calls[0]["temperature"] == 0.0
    assert [e.name for e in out] == ["Penicilina"]
    assert out.report.path == "json_schema"


@pytest.mark.parametrize("status", [400, 422])
async def test_falls_back_to_json_object_when_the_provider_rejects_the_schema(
    monkeypatch, caplog, status
):
    chat = _provider(monkeypatch, json_schema=_sdk_error(status), json_object=_reply(_ent()))

    with caplog.at_level(logging.WARNING, logger=extract_mod.logger.name):
        out = await extract_entities(DOC)

    assert chat.formats == ["json_schema", "json_object"]
    assert chat.calls[1]["response_format"] == {"type": "json_object"}
    assert [e.name for e in out] == ["Penicilina"]
    assert out.report.path == "json_object"
    assert "falling back to json_object" in caplog.text


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_a_transient_error_is_not_absorbed_by_the_fallback(monkeypatch, status):
    # The caller's retry loop owns transient failures; falling back would hide
    # an outage behind a second request that fails the same way.
    chat = _provider(monkeypatch, json_schema=_sdk_error(status), json_object=_reply(_ent()))

    with pytest.raises(SDKError):
        await extract_entities(DOC)

    assert chat.formats == ["json_schema"]


@pytest.mark.parametrize(
    "unusable", ["I cannot do that.", '{"entities": [', '{"entities": [}', '{"nope": 1}']
)
async def test_falls_back_when_the_schema_reply_is_unusable(monkeypatch, unusable):
    chat = _provider(monkeypatch, json_schema=unusable, json_object=_reply(_ent()))

    out = await extract_entities(DOC)

    assert chat.formats == ["json_schema", "json_object"]
    assert [e.name for e in out] == ["Penicilina"]
    assert out.report.path == "json_object"


async def test_a_reply_with_no_entities_list_is_flagged_not_mistaken_for_an_empty_document(
    monkeypatch,
):
    _provider(monkeypatch, json_schema="no json", json_object="still no json")

    out = await extract_entities(DOC)

    assert list(out) == []
    assert out.report.unusable_reply is True
    assert out.report.received == 0

    _provider(monkeypatch, json_schema=_reply())
    empty = await extract_entities(DOC)
    assert list(empty) == [] and empty.report.unusable_reply is False


async def test_broken_json_on_the_last_path_still_fails_loudly(monkeypatch):
    # Unchanged behaviour: a document must not turn "ready with no facts"
    # because the model emitted half a JSON object.
    # Braces that do not make JSON. (No closing brace at all never matched the
    # extraction regex and has always meant "no reply", covered above.)
    _provider(monkeypatch, json_schema=_sdk_error(400), json_object='{"entities": [}')

    with pytest.raises(json.JSONDecodeError):
        await extract_entities(DOC)


async def test_markdown_fenced_json_is_still_parsed(monkeypatch):
    fenced = f"```json\n{_reply(_ent())}\n```"
    _provider(monkeypatch, json_schema=_sdk_error(400), json_object=fenced)

    out = await extract_entities(DOC)

    assert [e.name for e in out] == ["Penicilina"]


# --- Drops are counted, with a reason -------------------------------------------

def _mixed_reply() -> str:
    return _reply(
        _ent(),                                                        # kept
        _ent(entity_type="medication", name="Metformina",
             raw_quote="Metformina 500 mg cada 12 horas"),             # kept
        {"entity_type": "allergy", "raw_quote": "Alergia: penicilina",
         "confidence": 0.9},                                           # no name
        _ent(entity_type="banana"),                                    # outside the enum
        _ent(value=["not", "an", "object"]),                           # wrong JSON type
        "just a string",                                               # not an object
        _ent(confidence=1.7),                                          # right shape, bad value
        _ent(event_date="2026-13-45"),                                 # right shape, bad date
        _ent(raw_quote="Alergia: amoxicilina"),                        # invented quote
        _ent(raw_quote="alergia: penicilina"),                         # case differs
        _ent(raw_quote="Alergia:  penicilina"),                        # whitespace differs
        _ent(raw_quote="   "),                                         # nothing at all
        _ent(raw_quote=""),
        _ent(confidence=0.4),                                          # same fact, repeat
    )


async def test_every_drop_is_counted_under_its_reason(monkeypatch):
    _provider(monkeypatch, json_schema=_mixed_reply())

    out = await extract_entities(DOC)

    assert [e.name for e in out] == ["Penicilina", "Metformina"]
    assert out.report.received == 14
    assert out.report.kept == 2
    assert out.report.dropped == {
        "schema_invalid": 4,
        "validation_error": 2,
        "quote_not_verbatim": 5,
        "duplicate": 1,
    }
    assert set(out.report.dropped) == set(DROP_REASONS)
    assert out.report.received == out.report.kept + out.report.dropped_total


async def test_each_drop_leaves_a_log_line_with_its_reason(monkeypatch, caplog):
    _provider(monkeypatch, json_schema=_mixed_reply())

    with caplog.at_level(logging.INFO, logger=extract_mod.logger.name):
        await extract_entities(DOC)

    for reason in DROP_REASONS:
        assert f"reason={reason}" in caplog.text
    assert "kept 2 of 14" in caplog.text


async def test_log_lines_do_not_echo_rejected_values(monkeypatch, caplog):
    secret = "valor-clinico-que-no-debe-salir"
    _provider(monkeypatch, json_schema=_reply(_ent(confidence=secret)))

    with caplog.at_level(logging.INFO, logger=extract_mod.logger.name):
        out = await extract_entities(DOC)

    assert out.report.dropped["validation_error"] == 1
    assert secret not in caplog.text


async def test_a_duplicate_keeps_the_more_confident_copy(monkeypatch):
    _provider(monkeypatch, json_schema=_reply(_ent(confidence=0.3), _ent(confidence=0.95)))

    out = await extract_entities(DOC)

    assert len(out) == 1 and out[0].confidence == 0.95
    assert out.report.dropped["duplicate"] == 1


async def test_entities_that_differ_in_any_field_are_not_duplicates(monkeypatch):
    # Same quote, different fact: collapsing these would lose one of them.
    _provider(monkeypatch, json_schema=_reply(
        _ent(entity_type="observation", name="Hemoglobina", raw_quote="Hemoglobina 12,1",
             value={"value": 12.1, "unit": "g/dL"}),
        _ent(entity_type="observation", name="Hb", raw_quote="Hemoglobina 12,1",
             value={"value": 12.1, "unit": "g/dL"}),
        _ent(entity_type="observation", name="Hemoglobina", raw_quote="Hemoglobina 12,1",
             value={"value": 12.1, "unit": "g/dL"}, event_date="2026-09-01"),
    ))

    out = await extract_entities(DOC)

    assert len(out) == 3 and out.report.dropped["duplicate"] == 0


async def test_diary_date_is_stamped_on_both_paths(monkeypatch):
    for responses in (
        {"json_schema": _reply(_ent())},
        {"json_schema": _sdk_error(400), "json_object": _reply(_ent())},
    ):
        _provider(monkeypatch, **responses)
        out = await extract_entities(DOC, diary_date="2026-08-27")
        assert out[0].event_date.isoformat() == "2026-08-27"


# --- The verbatim rule is the same on both paths --------------------------------

_FABRICATED = _reply(
    _ent(),
    _ent(name="Amoxicilina", raw_quote="Alergia: amoxicilina"),
    _ent(name="Latex", raw_quote="Alergia al latex"),
)
_BOTH_PATHS = [
    pytest.param({"json_schema": _FABRICATED}, "json_schema", id="schema-enforced"),
    pytest.param(
        {"json_schema": _sdk_error(400), "json_object": _FABRICATED}, "json_object",
        id="json-object-fallback",
    ),
]


@pytest.mark.parametrize(("responses", "path"), _BOTH_PATHS)
async def test_a_fabricated_quote_is_discarded_whichever_path_produced_it(
    monkeypatch, responses, path
):
    _provider(monkeypatch, **responses)

    out = await extract_entities(DOC)

    assert out.report.path == path
    assert [e.name for e in out] == ["Penicilina"]
    assert out.report.dropped["quote_not_verbatim"] == 2
    assert all(e.raw_quote in DOC for e in out)


@pytest.mark.parametrize(("responses", "path"), _BOTH_PATHS)
async def test_nothing_is_kept_without_passing_the_one_verbatim_check(
    monkeypatch, responses, path
):
    # If either path had its own copy of the rule, this would let something
    # through: the shared function is the only gate and it says no to everything.
    seen: list[str] = []

    def reject_all(text: str, quote: str) -> bool:
        seen.append(quote)
        return False

    monkeypatch.setattr(extract_mod, "quote_is_verbatim", reject_all)
    _provider(monkeypatch, **responses)

    out = await extract_entities(DOC)

    assert list(out) == []
    assert out.report.dropped["quote_not_verbatim"] == 3
    assert len(seen) == 3


def test_the_verbatim_rule_is_exact_and_stricter_than_truthiness():
    assert quote_is_verbatim(DOC, "Alergia: penicilina")
    assert not quote_is_verbatim(DOC, "alergia: penicilina")
    assert not quote_is_verbatim(DOC, "Alergia:  penicilina")
    assert not quote_is_verbatim(DOC, "")
    assert not quote_is_verbatim(DOC, "   ")  # a space IS in the document; it proves nothing
    assert not quote_is_verbatim("", "Alergia")


# --- A quote that repeats has no single place -----------------------------------

def test_a_phrase_repeated_three_times_has_three_occurrences_and_no_location():
    starts = quote_occurrences(REPEATED, "negativo")

    assert len(starts) == 3
    assert [REPEATED[s:s + 8] for s in starts] == ["negativo"] * 3
    assert starts[0] == REPEATED.find("negativo")  # the one find() would have picked
    assert locate_quote(REPEATED, "negativo") is None


def test_a_unique_quote_keeps_its_exact_location():
    span = locate_quote(REPEATED, "Prueba estreptococo: negativo")

    assert span is not None
    assert REPEATED[span[0]:span[1]] == "Prueba estreptococo: negativo"
    assert span[0] > REPEATED.find("negativo")  # not the first "negativo" in the file


def test_overlapping_occurrences_count_as_ambiguous():
    assert quote_occurrences("aaa", "aa") == [0, 1]
    assert locate_quote("aaa", "aa") is None
    assert locate_quote("aaa", "aaa") == (0, 3)


def test_an_absent_or_empty_quote_has_no_location():
    assert locate_quote(REPEATED, "positivo") is None
    assert locate_quote(REPEATED, "") is None
    assert quote_occurrences(REPEATED, "") == []


async def test_a_repeated_quote_is_kept_but_reported_as_ambiguous(monkeypatch):
    # Kept: the quote IS verbatim, so the verbatim rule is satisfied and the
    # fact is not lost. Only its place is withheld, and the report says so.
    _provider(monkeypatch, json_schema=_reply(
        _ent(entity_type="observation", name="Resultado", raw_quote="negativo"),
        _ent(entity_type="observation", name="VIH", raw_quote="Prueba VIH: negativo"),
    ))

    out = await extract_entities(REPEATED)

    assert [e.name for e in out] == ["Resultado", "VIH"]
    assert out.report.ambiguous_quote == 1
    assert out.report.dropped_total == 0


# --- Router: location, persisted counts -------------------------------------------

@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: run locally with docker compose up postgres")
async def test_pipeline_links_only_unambiguous_quotes_and_stores_the_report(monkeypatch):
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod
    from tests.db_helpers import make_user

    report = ExtractionReport(path="json_schema", received=5, kept=2, ambiguous_quote=1)
    report.dropped["quote_not_verbatim"] = 3

    async def fake_extract(text, *, diary_date=None):
        return ExtractionResult(
            [
                ExtractedEntity(entity_type="observation", name="VIH",
                                raw_quote="Prueba VIH: negativo", confidence=0.9),
                ExtractedEntity(entity_type="observation", name="Resultado",
                                raw_quote="negativo", confidence=0.9),
            ],
            report,
        )

    async def fake_get_object(key):
        return io.BytesIO(b"")

    async def fake_embed(texts):
        return [[0.0] * 1024 for _ in texts]

    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", ())
    monkeypatch.setattr(docs_mod.storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", fake_embed)

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.uuid4(), user_id=user_id, source="web", mime_type="text/plain",
            s3_key=f"users/{user_id}/{uuid.uuid4()}-informe.txt", raw_text=REPEATED,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    await docs_mod._process_document_inner(doc_id, "text/plain")

    async with AsyncSessionLocal() as session:
        entities = {
            e.name: e for e in (await session.execute(
                sa.select(Entity).where(Entity.document_id == doc_id))).scalars()
        }
        chunks = (await session.execute(
            sa.select(Chunk).where(Chunk.document_id == doc_id))).scalars().all()
        stored = await session.get(Document, doc_id)

    # Both facts are saved; only the unambiguous one is tied to a chunk.
    assert set(entities) == {"VIH", "Resultado"}
    linked = {eid for c in chunks for eid in c.chunk_metadata["entity_ids"]}
    assert linked == {str(entities["VIH"].id)}

    assert stored.document_metadata["extraction"]["dropped"]["quote_not_verbatim"] == 3
    out = docs_mod._doc_to_out(stored)
    assert out.extraction is not None
    assert out.extraction.received == 5 and out.extraction.ambiguous_quote == 1


@pytest.mark.skipif(not PG_AVAILABLE, reason="PG required: run locally with docker compose up postgres")
async def test_a_failed_pipeline_stores_no_extraction_report(monkeypatch):
    from adelia.db import AsyncSessionLocal
    from adelia.routers import documents as docs_mod
    from tests.db_helpers import make_user

    async def fake_extract(text, *, diary_date=None):
        return ExtractionResult([], ExtractionReport(path="json_schema"))

    async def fake_get_object(key):
        return io.BytesIO(b"")

    async def failing_embed(texts):
        raise RuntimeError("embedding down")

    monkeypatch.setattr(docs_mod, "RETRY_DELAYS", ())
    monkeypatch.setattr(docs_mod.storage, "get_object", fake_get_object)
    monkeypatch.setattr(docs_mod, "extract_entities", fake_extract)
    monkeypatch.setattr(docs_mod, "embed_texts", failing_embed)

    user_id = await make_user()
    async with AsyncSessionLocal() as session:
        doc = Document(
            id=uuid.uuid4(), user_id=user_id, source="web", mime_type="text/plain",
            s3_key=f"users/{user_id}/{uuid.uuid4()}-informe.txt", raw_text=REPEATED,
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    await docs_mod._process_document_inner(doc_id, "text/plain")

    async with AsyncSessionLocal() as session:
        stored = await session.get(Document, doc_id)
    assert "extraction" not in (stored.document_metadata or {})
    assert docs_mod._doc_to_out(stored).extraction is None


# --- Live ---------------------------------------------------------------------------

@pytest.mark.skipif(not settings.mistral_api_key, reason="needs Mistral API key")
async def test_live_provider_accepts_the_schema():
    """The only place a human learns whether Mistral really takes this schema:
    a fallback here means the strict path is silently unused in production."""
    out = await extract_entities(DOC)

    assert out.report.path == "json_schema"
    assert all(e.raw_quote in DOC for e in out)
    assert out.report.received == out.report.kept + out.report.dropped_total
