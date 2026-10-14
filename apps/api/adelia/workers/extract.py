import json
import logging
import re
from datetime import date

from mistralai.client.errors import MistralError
from pydantic import ValidationError

from adelia.llm import get_mistral_client
from adelia.schemas import ExtractedEntity, ExtractionReport

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a medical information extraction assistant.

Given a medical document (clinical note, lab result, prescription, discharge summary),
extract structured entities.

Each entity MUST include:
- entity_type: one of condition, medication, allergy, immunization, procedure,
  observation, family_history, device, allergen_reaction, social_history
- name: human-readable name (e.g., "Metformin", "Type 2 Diabetes Mellitus")
- raw_quote: the EXACT verbatim text from the document that supports this entity.
  This is critical — it must be a substring of the input document character-for-character.
  Do not paraphrase. Do not summarize. Copy the exact text.
- confidence: 0.0 to 1.0, your self-rated certainty

Optional fields:
- value: dict with entity-specific data (e.g., {"dose": "500 mg", "freq": "BID"} for
  medications, {"value": 6.8, "unit": "%"} for observations)
- event_date: ISO date string YYYY-MM-DD if a date is present
- status: "active", "resolved", "completed" for conditions; "current" for medications
- coding_system: "ICD10", "SNOMED", "LOINC", "ATC", "RxNorm" if you can confidently code
- code: the code itself
- page: page number if multi-page

Clinical-quality rule (so a doctor sees a trustworthy medication list):
- CURRENT vs PLANNED medications: a drug the patient is ACTIVELY taking gets
  status "current". A drug merely RECOMMENDED or PLANNED (e.g. under "PLAN",
  "anadir", "iniciar", "se recomienda", "considerar") gets status "planned" —
  do NOT present it as a current medication.
  Extract EVERY diagnosis you find — never omit one to avoid repetition;
  de-duplication happens downstream, your job is recall.

Return ONLY a JSON object: {"entities": [...]}. No prose, no markdown fence, just JSON.

If the document contains no medical information, return {"entities": []}.
"""


JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


DIARY_PROMPT_SUFFIX = """
This document is a parent's DAILY DIARY entry about their child, dated {diary_date}.
Besides any clinical facts, extract the everyday facts of that day as entities of
entity_type "observation" with provenance "patient_stated":
- feeding (what and how much), e.g. value {{"category": "feeding", "amount": "medio plátano"}}
- sleep (hours, naps), e.g. value {{"category": "sleep", "duration": "2 h"}}
- stools, mood, daycare, mild symptoms, e.g. value {{"category": "mood", "state": "irritable"}}
Use event_date "{diary_date}" unless the text names another day. raw_quote must
still be a verbatim substring. Return {{"entities": []}} only if nothing about the
day is stated.
"""


# HTTP statuses that mean "this request is malformed or unsupported", which is
# how a provider or model without json_schema support answers the parameter.
# Anything else (429, 5xx, network) is transient and must reach the caller's
# retry loop untouched, never be absorbed by the fallback below.
SCHEMA_REJECTED_STATUSES = frozenset({400, 422})


def extraction_json_schema() -> dict:
    """JSON Schema of the reply, derived from ExtractedEntity and nothing else.

    ExtractedEntity already mirrors the `entities` table and is what the
    router persists, so deriving the schema from it keeps ONE definition of
    "an extracted entity": a field added there reaches the model, the
    validation and the table together, and the schema cannot drift from them.
    The envelope is the only thing defined here, because the reply is
    `{"entities": [...]}` and ExtractedEntity describes one element.
    """
    return {
        "type": "object",
        "properties": {
            "entities": {"type": "array", "items": ExtractedEntity.model_json_schema()},
        },
        "required": ["entities"],
    }


def _schema_response_format() -> dict:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "extracted_entities",
            "schema": extraction_json_schema(),
            "strict": True,
        },
    }


class ExtractionResult(list[ExtractedEntity]):
    """The kept entities, as a plain list, with the counts attached as `.report`.

    A list subclass, not a tuple or a new return type, because
    `extract_entities` is called through `documents.py` and monkeypatched in a
    dozen tests as a function returning a list. Every caller that only wants
    the entities keeps working unchanged; the ones that want to say "7 of 31
    facts were discarded" read `.report`.
    """

    def __init__(self, entities=(), report: ExtractionReport | None = None):
        super().__init__(entities)
        self.report = report if report is not None else ExtractionReport()


def quote_occurrences(text: str, quote: str, *, limit: int | None = None) -> list[int]:
    """Start offsets of every occurrence of `quote` in `text`, overlaps included.

    Overlaps are counted on purpose: "aa" occurs twice in "aaa", and a quote
    that can be read at two places is ambiguous whether or not the two reads
    share characters. `limit` stops the scan early; callers that only need to
    tell zero from one from many pass 2.
    """
    starts: list[int] = []
    if not quote:
        return starts
    at = text.find(quote)
    while at != -1:
        starts.append(at)
        if limit is not None and len(starts) >= limit:
            break
        at = text.find(quote, at + 1)
    return starts


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """(start, end) of `quote` in `text`, or None unless it occurs exactly once.

    `text.find()` returns the FIRST occurrence, so for a quote that appears
    more than once ("negativo", "normal", a repeated date) the offsets fed to
    the chunker pointed at the first one whatever the model meant, and the
    entity was linked to the wrong chunk with full confidence. A quote alone
    cannot say which occurrence it came from, so the rule is: unique quote,
    unique place; ambiguous quote, NO place. Guessing the first is exactly the
    bug; the entity itself is still kept (its quote is verbatim, see
    `_screen_entities`) and simply carries no chunk link.
    """
    starts = quote_occurrences(text, quote, limit=2)
    if len(starts) != 1:
        return None
    return starts[0], starts[0] + len(quote)


def quote_is_verbatim(text: str, quote: str) -> bool:
    """The anti-hallucination rule (spec 6.1): the quote is a literal substring.

    The ONE place this is decided. Both request paths (schema-enforced and
    json_object) end in `_screen_entities`, which calls only this, so a
    provider that guarantees the reply's shape cannot buy a quote any more
    leniency than one that does not. Exact match: no case folding, no
    whitespace normalisation, no fuzzy matching. A quote that is only
    whitespace is rejected as well: it is a substring of nearly any document
    and supports nothing.
    """
    return bool(quote.strip()) and quote in text


def _validation_reason(exc: ValidationError) -> str:
    """schema_invalid when the item cannot be an instance of the requested schema.

    A missing required field, a value outside an enum (entity_type,
    provenance) or a wrong JSON type is the model breaking the SHAPE it was
    asked for, which strict structured output is supposed to rule out and
    which therefore deserves its own counter. Everything else is a well-shaped
    item whose VALUE our rules reject (confidence outside 0..1, a date that
    does not exist), counted as validation_error.
    """
    for error in exc.errors():
        kind = error["type"]
        if kind in ("missing", "literal_error") or kind.endswith("_type"):
            return "schema_invalid"
    return "validation_error"


def _dedupe_key(entity: ExtractedEntity) -> str:
    # Every field but confidence: two entities that differ in any other field
    # (name, value, date, status, quote) are different facts, and a wrong merge
    # would lose one. Only a verbatim repeat is collapsed.
    return json.dumps(entity.model_dump(mode="json", exclude={"confidence"}), sort_keys=True)


def _screen_entities(
    raw_items: list,
    text: str,
    diary_date: str | None,
    report: ExtractionReport,
) -> list[ExtractedEntity]:
    """Validate, verbatim-check and de-duplicate the model's items, counting drops.

    Shared by both request paths. Order matters: shape and value first, then
    the verbatim rule, then duplicates, so a fabricated repeat is counted as
    fabricated rather than as harmless.
    """
    report.received = len(raw_items)
    kept: list[ExtractedEntity] = []
    seen: dict[str, int] = {}

    def drop(reason: str, detail: str) -> None:
        report.dropped[reason] += 1
        logger.warning("extract: entity dropped reason=%s %s", reason, detail)

    for raw in raw_items:
        if not isinstance(raw, dict):
            drop("schema_invalid", f"item is a {type(raw).__name__}, not an object")
            continue
        try:
            entity = ExtractedEntity.model_validate(raw)
        except ValidationError as exc:
            # Locations and error kinds only: pydantic's own message echoes the
            # offending value, which here can be a fragment of a child's record.
            found = [(".".join(map(str, e["loc"])), e["type"]) for e in exc.errors()]
            drop(_validation_reason(exc), f"errors={found}")
            continue
        # Anti-hallucination: raw_quote MUST appear verbatim in the input text.
        if not quote_is_verbatim(text, entity.raw_quote):
            drop("quote_not_verbatim", f"quote={entity.raw_quote[:60]!r}")
            continue
        if diary_date and entity.event_date is None:
            entity.event_date = date.fromisoformat(diary_date)
        key = _dedupe_key(entity)
        if key in seen:
            # Keep the more confident copy: confidence below the review
            # threshold sets needs_review downstream.
            if entity.confidence > kept[seen[key]].confidence:
                kept[seen[key]] = entity
            drop("duplicate", f"name={entity.name[:40]!r}")
            continue
        if len(quote_occurrences(text, entity.raw_quote, limit=2)) > 1:
            report.ambiguous_quote += 1
            logger.info(
                "extract: quote occurs more than once, kept without a location: %.60r",
                entity.raw_quote,
            )
        seen[key] = len(kept)
        kept.append(entity)
    report.kept = len(kept)
    return kept


def _reply_text(response) -> str:
    content = response.choices[0].message.content if response.choices else ""
    if not isinstance(content, str):
        content = str(content)
    return content


def _parse_reply(content: str) -> list | None:
    """The `entities` list of the reply, or None when there is no usable one.

    Strips an optional markdown fence in case the model ignores the requested
    format. Raises json.JSONDecodeError for a reply that has braces but is not
    JSON, as it always did: on the json_object path that keeps a broken reply
    a loud failure of the document instead of a "ready" document with no facts.
    """
    match = JSON_BLOCK_RE.search(content)
    if not match:
        return None
    payload = json.loads(match.group(0))
    if not isinstance(payload, dict) or not isinstance(payload.get("entities"), list):
        return None
    return payload["entities"]


async def _complete(client, system_prompt: str, text: str, response_format: dict):
    return await client.chat.complete_async(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Document:\n\n{text}"},
        ],
        response_format=response_format,
        temperature=0.0,
    )


async def _request_entities(client, system_prompt: str, text: str) -> tuple[str, list | None]:
    """Ask for schema-enforced output; fall back to json_object, never to nothing.

    Returns (path, raw items); items is None when even the last attempt had no
    usable entities list. The fallback exists so no provider or model that
    lacks json_schema becomes unavailable. It triggers on a client error
    status (the provider refusing the parameter) or on a schema-path reply that
    is not usable at all; a transient failure is re-raised for the caller's
    retry loop. Not sticky: a 400 can also be a document-specific problem, and
    remembering it would switch the guarantee off for every later document.
    """
    try:
        response = await _complete(client, system_prompt, text, _schema_response_format())
    except MistralError as exc:
        if exc.status_code not in SCHEMA_REJECTED_STATUSES:
            raise
        logger.warning(
            "extract: provider rejected json_schema (HTTP %s), falling back to json_object",
            exc.status_code,
        )
    else:
        try:
            items = _parse_reply(_reply_text(response))
        except json.JSONDecodeError:
            items = None
        if items is not None:
            return "json_schema", items
        logger.warning("extract: json_schema reply unusable, falling back to json_object")

    response = await _complete(client, system_prompt, text, {"type": "json_object"})
    return "json_object", _parse_reply(_reply_text(response))


async def extract_entities(text: str, *, diary_date: str | None = None) -> ExtractionResult:
    """Extract FHIR-aligned medical entities from raw text via Mistral LLM.

    The reply is requested with schema-enforced output (response_format
    json_schema, derived from ExtractedEntity) and, if the provider refuses it,
    with plain json_object. Both paths then go through the same screening:
    validation, the verbatim-quote rule, duplicates. The schema is a promise
    about the reply's SHAPE; it says nothing about whether a quote is real, so
    the verbatim check is neither skipped nor relaxed on the strict path.

    Args:
        text: raw_text from a document (post-OCR or post-transcription).
        diary_date: ISO date when the text is a daily diary entry. Switches the
            prompt to everyday facts (feeding, sleep, mood...) and stamps that
            date as event_date on entities that carry none.

    Returns:
        ExtractionResult: a list of ExtractedEntity, with `.report` saying how
        many items the model returned and why each discarded one was
        discarded. Entities whose raw_quote does NOT appear verbatim in the
        input text are filtered out (anti-hallucination guard per spec 6.1).

    Raises:
        RuntimeError: if MISTRAL_API_KEY is not configured. Configuration error:
            do NOT retry; alert.
        mistralai.SDKError: on API failure (transient, caller may retry).
        json.JSONDecodeError: the final reply has braces but is not JSON.
    """
    client = get_mistral_client()

    system_prompt = SYSTEM_PROMPT
    if diary_date:
        system_prompt += DIARY_PROMPT_SUFFIX.format(diary_date=diary_date)

    path, raw_items = await _request_entities(client, system_prompt, text)
    report = ExtractionReport(path=path)
    if raw_items is None:
        report.unusable_reply = True
        logger.warning(
            "extract: reply has no usable entities list reason=schema_invalid path=%s", path
        )
        return ExtractionResult([], report)

    entities = _screen_entities(raw_items, text, diary_date, report)
    log = logger.warning if report.dropped_total else logger.info
    log(
        "extract: kept %d of %d entities path=%s dropped=%s ambiguous_quote=%d",
        report.kept, report.received, path, report.dropped, report.ambiguous_quote,
    )
    return ExtractionResult(entities, report)
