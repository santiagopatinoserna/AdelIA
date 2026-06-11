import json
import logging
import re

from pydantic import ValidationError

from adelia.llm import get_mistral_client
from adelia.schemas import ExtractedEntity

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
    client = get_mistral_client()

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
        except ValidationError as exc:
            logger.warning("entity validation failed, dropping: %s", exc)
            continue
        # Anti-hallucination: raw_quote MUST appear verbatim in the input text.
        if entity.raw_quote and entity.raw_quote in text:
            validated.append(entity)
        else:
            logger.warning(
                "hallucinated raw_quote dropped: %.60r", entity.raw_quote
            )
    return validated
