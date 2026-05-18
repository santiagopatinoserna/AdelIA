"""Loader for specialty filter rule JSON templates."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from adelia.schemas import Specialty


class SpecialtyTemplate(BaseModel):
    specialty: str
    rules_version: str
    include_immunizations: bool
    include_family_history: bool
    include_social_history: bool = False
    highlight_observations: list[str] = Field(default_factory=list)
    exclude_observations: list[str] = Field(default_factory=list)
    vital_emphasis: list[str] = Field(default_factory=list)
    qa_pre_baker_hints: str


_TEMPLATES_DIR = Path(__file__).parent


def load_template(specialty: Specialty) -> SpecialtyTemplate:
    """Load a SpecialtyTemplate by enum value. Raises FileNotFoundError if missing."""
    path = _TEMPLATES_DIR / f"{specialty.value}.json"
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return SpecialtyTemplate(**data)


def list_specialties() -> set[str]:
    """Return the set of specialty filenames present (without .json extension)."""
    return {p.stem for p in _TEMPLATES_DIR.glob("*.json")}
