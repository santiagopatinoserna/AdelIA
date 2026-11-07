"""agent/implicit_subject.py: the baby she does not name, put back for the search only.

Measured in production on 2026-11-06 (demo and container, read only): "Tiene
38,3 de fiebre desde esta mañana, ¿qué hago?" and "Tiene diarrea desde ayer,
¿qué hago?" were refused, their sources at 0.197-0.229, just past the 0.19
cut-off, while "Mi bebé de 10 meses tiene 38,5 de fiebre pero juega" found five
sources at 0.12-0.14. These tests pin, with no key and no database, which
sentences get the second search, what it says, and that the golden set's
group B questions that get it are the ones the supervisor measures.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from adelia.agent.implicit_subject import names_someone, subject_prefix, subject_query
from adelia.clinical.golden import CANDIDATES, questions

FEVER = "Tiene 38,3 de fiebre desde esta mañana, ¿qué hago?"
DIARRHOEA = "Tiene diarrea desde ayer, ¿qué hago?"


def test_the_setting_is_off_by_default():
    from adelia.config import Settings

    assert Settings.model_fields["implicit_subject_expansion"].default is False


def test_the_prod_compose_passes_the_setting_off_by_default():
    compose = Path(__file__).resolve().parents[3] / "infra" / "docker-compose.prod.yml"
    assert (
        "IMPLICIT_SUBJECT_EXPANSION: ${IMPLICIT_SUBJECT_EXPANSION:-false}"
        in compose.read_text(encoding="utf-8")
    )


# --- who the sentence is about -------------------------------------------------


@pytest.mark.parametrize("text, locale", [
    (FEVER, "es"),
    (DIARRHOEA, "es"),
    ("No come nada desde hace dos días", "es"),
    ("No duerme bien por las noches, ¿es normal?", "es"),
    ("Le están saliendo los dientes", "es"),
    ("¿Cuándo tengo que llevarlo al médico si tiene fiebre?", "es"),
    ("Estoy muy preocupada, tiene mocos desde hace una semana", "es"),
    ("Tengo una duda: ¿puedo bañarlo con fiebre?", "es"),
    ("Il a de la fièvre depuis ce matin, que faire ?", "fr"),
    ("Elle ne dort pas la nuit, c’est normal ?", "fr"),
    ("J’ai une question : il tousse la nuit", "fr"),
    ("She has had diarrhoea since yesterday, what should I do?", "en"),
    ("He won't eat anything, I am worried", "en"),
])
def test_a_sentence_that_names_nobody(text, locale):
    assert names_someone(text, locale) is False


@pytest.mark.parametrize("text, locale", [
    ("Mi bebé tiene fiebre", "es"),
    ("Mi BEBE tiene fiebre", "es"),
    ("¿Es normal que mi hija no gatee?", "es"),
    ("El niño tiene mocos", "es"),
    ("La nena no come", "es"),
    ("El peque tose mucho", "es"),
    ("Mi pequeña no duerme", "es"),
    ("¿Cuánto debe dormir un recién nacido?", "es"),
    ("Mon bébé a de la fièvre", "fr"),
    ("Mon fils tousse", "fr"),
    ("Ma petite ne mange pas", "fr"),
    ("Mon enfant de 3 ans", "fr"),
    ("My baby has a fever", "en"),
    ("My 4-month-old has a fever", "en"),
    ("My son won't eat", "en"),
    ("Our little one has a cough", "en"),
])
def test_a_sentence_about_the_baby(text, locale):
    assert names_someone(text, locale) is True


@pytest.mark.parametrize("text, locale", [
    ("Tengo fiebre y estoy dando el pecho, ¿qué tomo?", "es"),
    ("Me duele mucho el pecho al dar de mamar", "es"),
    ("Estoy agotada y lloro todos los días desde el parto", "es"),
    ("Yo tengo gastroenteritis, ¿lo puedo coger en brazos?", "es"),
    ("Mi pareja tiene gripe, ¿qué hago?", "es"),
    ("Mi madre tiene tos desde hace semanas", "es"),
    ("Mi marido tiene fiebre", "es"),
    ("Estoy embarazada otra vez", "es"),
    ("J'ai de la fièvre, puis-je allaiter ?", "fr"),
    ("Mon mari tousse beaucoup", "fr"),
    ("Je suis enceinte", "fr"),
    ("I have a fever, can I still breastfeed?", "en"),
    ("I'm exhausted since the birth", "en"),
    ("My husband has the flu", "en"),
])
def test_a_sentence_about_someone_else(text, locale):
    """She, her partner, her mother: the baby is not the subject, so none is added."""
    assert names_someone(text, locale) is True


def test_the_baby_s_name_is_a_subject():
    assert names_someone("Nora tiene fiebre", "es", name="Nora") is True
    assert names_someone("NORA tiene fiebre", "es", name="Nóra") is True
    assert names_someone("Tiene fiebre", "es", name="Nora") is False
    assert names_someone("Noraima tiene fiebre", "es", name="Nora") is False


def test_spanish_son_is_a_verb_not_a_son():
    """`son` is the English son only in English."""
    assert names_someone("¿Son normales estas cacas?", "es") is False
    assert names_someone("My son has a rash", "en") is True


# --- what the second search says ---------------------------------------------------


@pytest.mark.parametrize("locale, age, expected", [
    ("es", None, "Mi bebé: "),
    ("es", 5, "Mi bebé de 5 meses: "),
    ("es", 1, "Mi bebé de 1 mes: "),
    ("es", 0, "Mi bebé: "),
    ("en", None, "My baby: "),
    ("en", 10, "My 10-month-old baby: "),
    ("fr", None, "Mon bébé : "),
    ("fr", 8, "Mon bébé de 8 mois : "),
    ("de", 8, "Mi bebé de 8 meses: "),
])
def test_the_prefix(locale, age, expected):
    assert subject_prefix(locale, age) == expected


@pytest.mark.parametrize("age", [37, 120, 420])
def test_an_age_past_early_childhood_never_goes_into_the_prefix(age):
    """The active profile can be her own ("Mi perfil", relationship self) with
    her date of birth: "Mi bebé de 420 meses" is no baby. AdelIA covers 0-24
    months; up to 36 keeps a toddler's age, past that the prefix has none."""
    assert subject_prefix("es", age) == "Mi bebé: "
    assert subject_prefix("en", age) == "My baby: "
    assert subject_prefix("fr", age) == "Mon bébé : "
    assert subject_query(DIARRHOEA, locale="es", age_months=age) == f"Mi bebé: {DIARRHOEA}"
    assert subject_prefix("es", 36) == "Mi bebé de 36 meses: "


def test_a_sentence_without_subject_gets_the_baby_with_the_profile_age():
    assert subject_query(FEVER, locale="es", age_months=5) == f"Mi bebé de 5 meses: {FEVER}"
    assert subject_query(DIARRHOEA, locale="es") == f"Mi bebé: {DIARRHOEA}"


def test_a_sentence_with_a_subject_gets_nothing():
    assert subject_query("Mi bebé de 10 meses tiene 38,5", locale="es", age_months=10) is None
    assert subject_query("Mi pareja tiene fiebre", locale="es", age_months=10) is None
    assert subject_query("Nora tiene fiebre", locale="es", name="Nora") is None
    assert subject_query("   ", locale="es") is None


def test_an_age_she_wrote_is_not_contradicted_by_the_profile():
    """"Mi bebé de 5 meses: tiene 4 meses" would be two ages; hers stays alone."""
    text = "Tiene 4 meses y no duerme"
    assert subject_query(text, locale="es", age_months=5) == f"Mi bebé: {text}"
    clarified = "No come\nEdad: De 3 a 11 meses"
    assert subject_query(clarified, locale="es", age_months=3) == f"Mi bebé: {clarified}"


def test_a_translated_question_gets_the_spanish_prefix():
    """The corpus text is Spanish once corpus_query translated it; her own
    French sentence must name nobody too."""
    spoken = "Il a de la fièvre depuis ce matin"
    corpus = "Tiene fiebre desde esta mañana"
    assert subject_query(corpus, locale="fr", spoken=spoken, age_months=8) == (
        f"Mi bebé de 8 meses: {corpus}"
    )
    # The translation fell back to her words: the French prefix.
    assert subject_query(spoken, locale="fr", spoken=spoken, age_months=8) == (
        f"Mon bébé de 8 mois : {spoken}"
    )
    # Her French names her husband: nothing, whatever the translation says.
    assert subject_query("Tiene fiebre", locale="fr", spoken="Mon mari a de la fièvre") is None
    # The translation added a subject: nothing either.
    assert subject_query("Mi bebé tiene fiebre", locale="fr", spoken=spoken) is None


def test_a_fever_without_a_reading_answered_through_the_button_gets_the_baby():
    """The clarify flow: "Tiene fiebre, ¿qué hago?" then "38 a 38,9 °C". The
    message the retrieve step sees still names nobody."""
    absorbed = "Tiene fiebre, ¿qué hago?\nTemperatura: 38 a 38,9 °C"
    assert subject_query(absorbed, locale="es", age_months=5) == f"Mi bebé de 5 meses: {absorbed}"
    unmeasured = "Tiene fiebre, ¿qué hago?\nTemperatura: no la he medido"
    assert subject_query(unmeasured, locale="es", age_months=5) is not None
    with_baby = "Mi bebé tiene fiebre, ¿qué hago?\nTemperatura: 38 a 38,9 °C"
    assert subject_query(with_baby, locale="es", age_months=5) is None


# --- the golden set: which group B questions the supervisor must measure ------------


def _variant(q) -> str | None:
    return subject_query(q.question, locale=q.locale, spoken=q.question, age_months=q.age_months)


def test_the_group_b_questions_that_get_the_second_search():
    """Only these three name nobody. B2 sits close to the crawling fragments,
    B3 to the nursery ones and B18 (head lice at nursery, promoted to the gate
    on 2026-11-06) to both nursery and skin, so all three are what
    scripts/eval_implicit_subject.py must show still above the cut before the
    setting goes on. A change to the rules or to the golden set that moves this
    list needs that measurement again."""
    got = [q.id for q in questions("B") if _variant(q) is not None]
    assert got == ["B2", "B3", "B18"]


def test_the_candidate_b_questions_that_get_the_second_search():
    got = [q.id for q in CANDIDATES if q.group == "B" and _variant(q) is not None]
    assert got == sorted(got, key=lambda i: int(i[1:]))
    # Pinned so a new candidate that names nobody is seen, not slipped in.
    assert got == _CANDIDATE_B_WITH_VARIANT


#: Valerian drops, grinding teeth, a sacral dimple and ringworm: none names the
#: child. Candidates are not in the deploy gate yet, but a promotion would be
#: (B18, lice at nursery, was promoted and is pinned with group B above). B19
#: and B24 left the list on 2026-11-07, when they became A40 and A42.
_CANDIDATE_B_WITH_VARIANT: list[str] = ["B23", "B28", "B29", "B30"]


def test_the_group_a_questions_that_get_the_second_search():
    got = [q.id for q in questions("A") if _variant(q) is not None]
    assert got == [
        "A6", "A10", "A11", "A19", "A21", "A23", "A25", "A29", "A30", "A31", "A32",
        "A34", "A35", "A36", "A37", "A38",
    ]
