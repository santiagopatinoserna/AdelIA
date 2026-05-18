"""Validation tests for specialty templates loader."""
import pytest

from adelia.schemas import Specialty
from adelia.specialty_templates import (
    SpecialtyTemplate,
    load_template,
    list_specialties,
)


def test_load_default_template():
    tpl = load_template(Specialty.DEFAULT)
    assert tpl.specialty == "default"
    assert tpl.include_immunizations is False
    assert tpl.include_family_history is False


def test_load_pediatrics_includes_immunizations():
    tpl = load_template(Specialty.PEDIATRICS)
    assert tpl.include_immunizations is True


def test_load_cardiology_includes_family_history():
    tpl = load_template(Specialty.CARDIOLOGY)
    assert tpl.include_family_history is True


def test_load_endocrinology_highlights_labs():
    tpl = load_template(Specialty.ENDOCRINOLOGY)
    assert "HbA1c" in tpl.highlight_observations or "glucose" in tpl.highlight_observations


def test_all_8_specialties_have_templates():
    specs = list_specialties()
    expected = {
        "pediatrics",
        "endocrinology",
        "cardiology",
        "gynecology",
        "gastroenterology",
        "dermatology",
        "general_medicine",
        "default",
    }
    assert specs == expected


def test_template_has_required_fields():
    tpl = load_template(Specialty.DEFAULT)
    assert tpl.rules_version
    assert isinstance(tpl.include_immunizations, bool)
    assert isinstance(tpl.include_family_history, bool)
    assert isinstance(tpl.highlight_observations, list)
    assert isinstance(tpl.vital_emphasis, list)
    assert isinstance(tpl.qa_pre_baker_hints, str)
