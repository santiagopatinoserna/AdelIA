import json
import re

from mistralai.client.sdk import Mistral
from pydantic import ValidationError

from adelia.config import settings
from adelia.schemas import ExtractedEntity


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

Return ONLY a JSON object: {"entities": [...]}. No prose, no markdown fence, just JSON.

If the document contains no medical information, return {"entities": []}.
"""


JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


async def extract_entities(text: str) -> list[ExtractedEntity]:
    """Extract FHIR-aligned medical entities from raw text via Mistral LLM.

    Args:
        text: raw_text from a document (post-OCR or post-transcription).

    Returns:
        List of ExtractedEntity. Entities whose raw_quote does NOT appear verbatim
        in the input text are filtered out (anti-hallucination guard per spec 6.1).

    Raises:
        RuntimeError: if MISTRAL_API_KEY is not configured. Configuration error —
            do NOT retry; alert.
        mistralai.SDKError: on API failure (transient — caller may retry).
    """
    if not settings.mistral_api_key:
        raise RuntimeError("MISTRAL_API_KEY not set")

    client = Mistral(api_key=settings.mistral_api_key)

    response = await client.chat.complete_async(
        model="mistral-medium-latest",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Document:\n\n{text}"},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    content = response.choices[0].message.content if response.choices else ""
    if not isinstance(content, str):
        content = str(content)

    # Strip optional markdown fences in case the model violates response_format.
    match = JSON_BLOCK_RE.search(content)
    if not match:
        return []
    payload = json.loads(match.group(0))

    raw_entities = payload.get("entities", []) if isinstance(payload, dict) else []
    validated: list[ExtractedEntity] = []
    for raw in raw_entities:
        try:
            entity = ExtractedEntity(**raw)
        except ValidationError:
            continue
        # Anti-hallucination: raw_quote MUST appear verbatim in the input text.
        if entity.raw_quote and entity.raw_quote in text:
            validated.append(entity)
    return validated
