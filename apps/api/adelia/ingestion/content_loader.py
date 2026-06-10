"""Load platform guides + GDPR templates from markdown files with frontmatter.

Minimal YAML-frontmatter parser (no pyyaml dep) — supports flat key: value pairs
between leading `---` delimiters. Full YAML can be added in v0.1.1 if needed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_GUIDES_DIR = Path(__file__).parent.parent / "ingestion_guides"
_GDPR_DIR = Path(__file__).parent.parent / "gdpr_templates"


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Extract leading `---`-delimited frontmatter and remaining body.

    Returns (front_matter_dict, body_markdown). Frontmatter values are stripped.
    """
    if not text.startswith("---"):
        return {}, text

    end = text.find("\n---", 3)
    if end < 0:
        return {}, text

    frontmatter_raw = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")

    fm: dict[str, str] = {}
    for line in frontmatter_raw.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm, body


@dataclass(frozen=True)
class GuideFile:
    slug: str
    title: str
    description: str
    estimated_time: str | None
    markdown: str
    front_matter: dict[str, str]


@dataclass(frozen=True)
class GDPRTemplateFile:
    country: str
    authority: str
    legal_basis: str
    response_deadline: str
    output_language: str
    markdown: str


def list_guides() -> list[GuideFile]:
    """Return all platform guides sorted by slug."""
    guides: list[GuideFile] = []
    if not _GUIDES_DIR.exists():
        return guides
    for path in sorted(_GUIDES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        guides.append(
            GuideFile(
                slug=fm.get("slug", path.stem),
                title=fm.get("title", path.stem),
                description=fm.get("description", ""),
                estimated_time=fm.get("estimated_time"),
                markdown=body,
                front_matter=fm,
            )
        )
    return guides


def load_guide(slug: str) -> GuideFile | None:
    """Load a single guide by slug. Returns None if not found."""
    path = _GUIDES_DIR / f"{slug}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text)
    return GuideFile(
        slug=fm.get("slug", path.stem),
        title=fm.get("title", path.stem),
        description=fm.get("description", ""),
        estimated_time=fm.get("estimated_time"),
        markdown=body,
        front_matter=fm,
    )


def list_gdpr_templates() -> list[GDPRTemplateFile]:
    """Return all GDPR/HIPAA templates."""
    templates: list[GDPRTemplateFile] = []
    if not _GDPR_DIR.exists():
        return templates
    for path in sorted(_GDPR_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)
        templates.append(
            GDPRTemplateFile(
                country=fm.get("country", "UNKNOWN"),
                authority=fm.get("authority", ""),
                legal_basis=fm.get("legal_basis", ""),
                response_deadline=fm.get("response_deadline", ""),
                output_language=fm.get("output_language", ""),
                markdown=body,
            )
        )
    return templates


def load_gdpr_template(country: str) -> GDPRTemplateFile | None:
    """Load a single template by country code (case-insensitive)."""
    country_upper = country.upper()
    for tpl in list_gdpr_templates():
        if tpl.country.upper() == country_upper:
            return tpl
    return None
