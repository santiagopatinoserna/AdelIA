"""Tests for content_loader (frontmatter parser + guide/template listing)."""
from __future__ import annotations

from adelia.ingestion.content_loader import (
    _parse_frontmatter,
    list_gdpr_templates,
    list_guides,
    load_gdpr_template,
    load_guide,
)


def test_parse_frontmatter_extracts_key_value_pairs():
    text = """---
slug: test
title: Test Title
description: A test description
---

# Body content here
"""
    fm, body = _parse_frontmatter(text)
    assert fm["slug"] == "test"
    assert fm["title"] == "Test Title"
    assert fm["description"] == "A test description"
    assert body.startswith("# Body content here")


def test_parse_frontmatter_returns_empty_dict_when_no_frontmatter():
    text = "Just plain markdown body, no frontmatter."
    fm, body = _parse_frontmatter(text)
    assert fm == {}
    assert body == text


def test_list_guides_returns_5_v01_platforms():
    guides = list_guides()
    slugs = {g.slug for g in guides}
    expected = {
        "apple-health",
        "mychart",
        "mon-espace-sante-fr",
        "google-health-connect",
        "generic-ccd",
    }
    assert expected.issubset(slugs)


def test_load_guide_apple_health():
    guide = load_guide("apple-health")
    assert guide is not None
    assert guide.title == "Apple Health"
    assert "export" in guide.markdown.lower()


def test_load_guide_missing_returns_none():
    assert load_guide("nonexistent-platform") is None


def test_list_gdpr_templates_returns_3_v01_countries():
    templates = list_gdpr_templates()
    countries = {t.country for t in templates}
    assert "ES" in countries
    assert "FR" in countries
    assert "US" in countries


def test_load_gdpr_template_spain():
    tpl = load_gdpr_template("ES")
    assert tpl is not None
    assert tpl.country == "ES"
    assert "AEPD" in tpl.authority
    assert "RGPD" in tpl.legal_basis


def test_load_gdpr_template_case_insensitive():
    tpl_lower = load_gdpr_template("fr")
    tpl_upper = load_gdpr_template("FR")
    assert tpl_lower is not None
    assert tpl_upper is not None
    assert tpl_lower.country == tpl_upper.country


def test_load_gdpr_template_missing_returns_none():
    assert load_gdpr_template("ZZ") is None
