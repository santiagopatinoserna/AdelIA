from __future__ import annotations
from typing import Any

def _card(card_type: str, card_id: str, payload: dict, actions: list[dict] | None = None) -> dict:
    return {"type": card_type, "id": card_id, "payload": payload, "actions": actions or []}

def card_action(card_id: str, title: str, body: str, action_label: str, action_intent: str) -> dict:
    return _card("action", card_id, {"title": title, "body": body},
                 [{"label": action_label, "intent": action_intent}])

def card_confirm(card_id: str, title: str, tool_name: str, tool_args: dict[str, Any]) -> dict:
    return _card("confirm", card_id, {"title": title, "tool_name": tool_name, "tool_args": tool_args},
                 [{"label": "Sí", "intent": "confirm"}, {"label": "No", "intent": "cancel"}])

def card_question(card_id: str, field: str, prompt: str, input_type: str = "text") -> dict:
    return _card("question", card_id, {"field": field, "prompt": prompt, "input_type": input_type},
                 [{"label": "Guardar", "intent": "answer"}])

def card_lab(card_id: str, name: str, value: Any, unit: str, flag: str, range_str: str, interpretation: str) -> dict:
    return _card("lab", card_id, {"name": name, "value": value, "unit": unit, "flag": flag,
                                  "range": range_str, "interpretation": interpretation})

def card_briefing(card_id: str, briefing_id: str, specialty: str, status: str, preview: str) -> dict:
    return _card("briefing", card_id, {"briefing_id": briefing_id, "specialty": specialty,
                                       "status": status, "preview": preview},
                 [{"label": "Ver PDF", "intent": "open_briefing"}, {"label": "Compartir", "intent": "share_briefing"}])

def card_document(card_id: str, document_id: str, filename: str, status: str, entities: int) -> dict:
    return _card("document", card_id, {"document_id": document_id, "filename": filename,
                                       "status": status, "entities": entities})

def card_profile(card_id: str, profiles: list[dict], active_id: str | None) -> dict:
    return _card("profile", card_id, {"profiles": profiles, "active_id": active_id})

def card_insight(card_id: str, title: str, body: str, tone: str = "neutral") -> dict:
    return _card("insight", card_id, {"title": title, "body": body, "tone": tone})
