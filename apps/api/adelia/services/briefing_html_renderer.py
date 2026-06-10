"""Briefing HTML renderer — Jinja2 server-side render + nh3 sanitization.

The same template is reused by M6 WeasyPrint PDF render (single source of truth).
nh3 sanitizes LLM-generated text fields BEFORE templating, not after, to prevent
HTML injection via answers/narrative strings.
"""
from __future__ import annotations

import logging
from pathlib import Path

import nh3
from jinja2 import Environment, FileSystemLoader, select_autoescape

from adelia.schemas import BriefingPayload
from adelia.services.briefing_i18n import briefing_labels

logger = logging.getLogger(__name__)


_TEMPLATE_DIR = Path(__file__).parent.parent / "templates"
_NH3_ALLOWED_TAGS: set[str] = set()
_NH3_ALLOWED_ATTRS: dict[str, set[str]] = {}


def _make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return env


def _sanitize_payload(payload: BriefingPayload) -> BriefingPayload:
    """Run nh3.clean over every user-visible string field that could carry LLM HTML."""
    p = payload.model_copy(deep=True)

    if p.sections.reason_for_consult:
        p.sections.reason_for_consult = nh3.clean(
            p.sections.reason_for_consult,
            tags=_NH3_ALLOWED_TAGS,
            attributes=_NH3_ALLOWED_ATTRS,
        )

    for qa in p.sections.open_questions:
        qa.question = nh3.clean(qa.question, tags=_NH3_ALLOWED_TAGS, attributes=_NH3_ALLOWED_ATTRS)
        qa.answer = nh3.clean(qa.answer, tags=_NH3_ALLOWED_TAGS, attributes=_NH3_ALLOWED_ATTRS)
        for c in qa.citations:
            c.raw_quote = nh3.clean(
                c.raw_quote, tags=_NH3_ALLOWED_TAGS, attributes=_NH3_ALLOWED_ATTRS
            )

    return p


def render_briefing_html(payload: BriefingPayload) -> str:
    """Render the briefing payload to a complete HTML document.

    Args:
        payload: validated BriefingPayload.
    Returns:
        Full HTML string (DOCTYPE + html + head + body).
    Raises:
        jinja2.TemplateError if template syntax fails.
    """
    sanitized = _sanitize_payload(payload)
    env = _make_env()
    template = env.get_template("briefing/briefing.html.j2")
    html = template.render(payload=sanitized, labels=briefing_labels(payload.locale))
    return html
