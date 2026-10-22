"""Demo examples should start with a parent's concern, not a lab value."""
import re

import pytest

from adelia.demo.fixture import DEMO_LOCALES, demo_profile


@pytest.mark.parametrize("locale", DEMO_LOCALES)
def test_suggestions_do_not_ask_a_parent_to_interpret_a_lab_number(locale):
    profile = demo_profile(locale)
    for question in profile["suggested"]:
        assert not re.search(r"10[.,]8|g/dl|h[eé]moglob|haemoglob", question, re.I)
    # Numbers remain in the fictional report. They are context, not homework.
    lab = next(item for item in profile["items"] if item["kind"] == "lab")
    assert any(re.search(r"10[.,]8", line) for line in lab["lines"])


@pytest.mark.parametrize("locale, phrase", [
    ("es", "Está comiendo menos"),
    ("en", "She is feeding less"),
    ("fr", "Elle mange moins"),
])
def test_third_suggestion_starts_with_an_observation(locale, phrase):
    assert demo_profile(locale)["suggested"][2].startswith(phrase)


@pytest.mark.parametrize("locale, history_word, advice_word", [
    ("es", "revisiones", "pediatra"),
    ("en", "check-ups", "pediatrician"),
    ("fr", "consultations", "pédiatre"),
])
def test_contextual_examples_invite_using_the_record_not_just_general_sources(
    locale, history_word, advice_word,
):
    suggestions = demo_profile(locale)["suggested"]
    assert advice_word in suggestions[1]
    assert history_word in suggestions[2]
