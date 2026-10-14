"""LLM-driven top-5 Q&A pre-baker with anti-hallucination guard.

One Mistral chat.complete_async call with structured output
(response_format=json_schema).
Post-LLM filter: every citation's raw_quote MUST appear verbatim in one of the
source documents' raw_text. Quotes that fail this check are dropped silently
with logger.warning. Minimum 3 items returned; never pad with synthetic content.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from adelia.config import settings
from adelia.services.briefing_i18n import qa_language
from adelia.schemas import Citation, LLMMeta, QAItem, Specialty

logger = logging.getLogger(__name__)


class QAPrebakerError(Exception):
    """Raised when the Mistral call fails irrecoverably."""


_QA_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "minLength": 1},
                    "answer": {"type": "string", "minLength": 1},
                    "citations": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "document_id": {"type": "string"},
                                "entity_id": {"type": ["string", "null"]},
                                "raw_quote": {"type": "string", "minLength": 1},
                            },
                            "required": ["document_id", "raw_quote"],
                        },
                    },
                },
                "required": ["question", "answer", "citations"],
            },
        }
    },
    "required": ["items"],
}


def _system_prompt(specialty: Specialty, hints: str, locale: str = "es") -> str:
    return (
        "You are a clinical assistant generating pre-baked Q&A for a medical briefing.\n\n"
        f"You are preparing a briefing for a patient about to see a {specialty.value} specialist.\n"
        "Generate exactly 5 questions a specialist is most likely to ask in a 15-minute consultation, "
        "based ONLY on the patient data provided below. For each question, provide an answer.\n\n"
        "CRITICAL ANTI-HALLUCINATION RULES:\n"
        "- If patient data does not contain enough info to answer a question, answer 'No data available in patient history'.\n"
        "- DO NOT invent diagnoses, medications, observations, or values not present in the entities.\n"
        "- Each answer MUST cite at least one raw_quote from the source documents — verbatim, no paraphrasing.\n"
        "- raw_quote MUST appear textually in one of the provided source quotes (no rephrasing, no synthesizing).\n"
        "- If you cannot generate 5 questions with grounded answers, generate fewer (minimum 3) — never fabricate.\n\n"
        f"Specialty-specific guidance: {hints}\n\n"
        f"{qa_language(locale)}\n\n"
        "Output JSON matching the provided schema."
    )


def _build_client():
    from adelia.llm import get_mistral_client

    if not settings.mistral_api_key:
        raise QAPrebakerError("MISTRAL_API_KEY not configured")
    return get_mistral_client()


async def _llm_structured_call(
    client: Any,
    system_prompt: str,
    user_content: str,
    model: str,
) -> tuple[dict, int]:
    """Call Mistral chat.complete_async with structured output.

    Returns (parsed_dict, tokens_used).

    `complete_async`, not `complete`: this is a single 10-30 s LLM call and it
    used to be the SYNCHRONOUS one, made from inside the event loop by a
    FastAPI BackgroundTask. While a briefing was baking, the whole worker was
    blocked — every other request on that process, /health included, waited
    for Mistral to finish writing five questions about someone else's baby
    (audit 4.5). Nothing else about the call changes; the anti-hallucination
    filter below still runs on the parsed result.
    """
    from mistralai.client.errors import MistralError

    from adelia.llm import content_text, reasoning_effort_kwargs

    try:
        # settings.briefing_reasoning_effort: unset (the default) adds nothing to
        # this call, so the request is the one sent before the knob existed. It
        # is the deliberate end of the range (a doctor's briefing), opposite to
        # chat_reasoning_effort, and Mistral does not document how reasoning
        # combines with a strict json_schema, so it needs an eval run first
        # (apps/api/docs/MODELOS.md).
        resp = await client.chat.complete_async(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "qa_items", "schema": _QA_JSON_SCHEMA, "strict": True},
            },
            temperature=0.2,
            **reasoning_effort_kwargs(
                settings.briefing_reasoning_effort, model, setting="briefing_reasoning_effort"
            ),
        )
    except MistralError as e:
        raise QAPrebakerError(f"Mistral API error: {e}") from e
    except Exception as e:
        raise QAPrebakerError(f"Unexpected error during Mistral call: {e}") from e

    content = resp.choices[0].message.content
    if isinstance(content, list):
        # reasoning_effort="high" answers with [ThinkChunk, TextChunk]; the JSON
        # is the text chunk and the thinking trace is not parsed or kept.
        content = content_text(content)
    tokens_used = getattr(resp.usage, "total_tokens", 0) if getattr(resp, "usage", None) else 0
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise QAPrebakerError(f"Failed to parse JSON from LLM: {e}") from e
    return data, tokens_used


def _enforce_raw_quote(items: list[dict], source_raw_texts: dict[str, str]) -> list[QAItem]:
    """Drop items whose citations don't appear verbatim in any source doc.

    Defense against LLM hallucination. raw_quote MUST be a substring of some doc's raw_text.
    """
    all_text = " \n ".join(source_raw_texts.values())
    kept: list[QAItem] = []
    for item_dict in items:
        valid_cits: list[Citation] = []
        for cit in item_dict.get("citations", []):
            quote = cit.get("raw_quote", "")
            if quote and quote in all_text:
                try:
                    doc_id = UUID(cit["document_id"])
                except (ValueError, KeyError):
                    logger.warning("Invalid document_id in citation, skipping: %r", cit)
                    continue
                entity_id_raw = cit.get("entity_id")
                entity_id: UUID | None
                if entity_id_raw:
                    try:
                        entity_id = UUID(entity_id_raw)
                    except ValueError:
                        entity_id = None
                else:
                    entity_id = None
                valid_cits.append(
                    Citation(document_id=doc_id, entity_id=entity_id, raw_quote=quote)
                )
            else:
                logger.warning(
                    "Anti-hallucination: dropping citation, raw_quote not in source: %r",
                    quote,
                )
        if not valid_cits:
            logger.warning(
                "Anti-hallucination: dropping QA item with no valid citations: %r",
                item_dict.get("question"),
            )
            continue
        try:
            kept.append(
                QAItem(
                    question=item_dict["question"],
                    answer=item_dict["answer"],
                    citations=valid_cits,
                )
            )
        except (ValidationError, KeyError) as e:
            logger.warning("Anti-hallucination: dropping malformed QA item: %s", e)
            continue
    return kept


async def bake_questions(
    specialty: Specialty,
    entities_text: str,
    specialty_hints: str,
    source_raw_texts: dict[str, str],
    model: str | None = None,
    locale: str = "es",
) -> tuple[list[QAItem], LLMMeta]:
    """Generate top-5 Q&A from patient context, with anti-hallucination filter.

    Returns (items, meta). Items may be 0-5 after filter; LLMMeta records cost/tokens.

    `model` defaults to settings.mistral_briefing_model ("mistral-medium-latest"
    today, the literal that used to be the default here); an explicit value wins.

    Async since 2026-08-31: the awaited call inside is the one that used to
    stall the event loop for the length of a briefing (audit 4.5).
    """
    model = model or settings.mistral_briefing_model
    client = _build_client()
    system_prompt = _system_prompt(specialty, specialty_hints, locale)
    user_content = (
        "Patient data (entities + raw_quotes):\n\n"
        f"{entities_text}\n\n"
        "Source documents (for verbatim citation lookup):\n\n"
        + "\n\n".join(f"--- {doc_id} ---\n{text[:4000]}" for doc_id, text in source_raw_texts.items())
    )

    parsed, tokens_used = await _llm_structured_call(client, system_prompt, user_content, model)
    items_raw = parsed.get("items", [])
    items = _enforce_raw_quote(items_raw, source_raw_texts)

    cost_estimate_usd = (tokens_used / 1_000_000) * 5.4

    meta = LLMMeta(model=model, tokens_used=tokens_used, cost_estimate_usd=cost_estimate_usd)
    return items, meta
