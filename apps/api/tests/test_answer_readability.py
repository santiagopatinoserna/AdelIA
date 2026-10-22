"""Readable output must be requested too, not only supported by the renderer."""
import pytest

from adelia.services.answer_contract import CONTRACTS, answer_contract


@pytest.mark.parametrize("locale, list_word", [
    ("es", "viñetas"), ("en", "bullets"), ("fr", "puces"),
])
def test_output_can_use_short_lists_without_weakening_the_citation_contract(locale, list_word):
    rule = CONTRACTS[locale].language_rule
    assert list_word in rule
    assert "Markdown" in rule
    contract = answer_contract(locale)
    assert "[ev_1]" in contract
    assert "NO interpretes ni aconsejes sin respaldo de investigación" in contract


@pytest.mark.parametrize("locale, required", [
    ("es", (
        "Empieza con una respuesta directa y breve",
        "Como máximo 3 viñetas cortas y accionables",
        "solo si la evidencia las respalda",
        "Todas las precauciones, condiciones y señales de alarma",
        "visibles de inmediato junto al consejo pertinente",
        "no en una explicación posterior",
        "Nunca omitas seguridad por un límite de palabras o de viñetas",
    )),
    ("en", (
        "Start with a short, direct answer",
        "At most 3 short, actionable bullets",
        "only if supported by evidence",
        "All caveats, conditions and warning signs",
        "immediately visible alongside the relevant advice",
        "not in a later explanation",
        "Never omit safety for a word or bullet limit",
    )),
    ("fr", (
        "Commence par une réponse courte et directe",
        "Au maximum 3 puces courtes et concrètes",
        "seulement si les preuves les étayent",
        "Toutes les précautions, conditions et signes d’alerte",
        "immédiatement visibles avec le conseil concerné",
        "pas dans une explication ultérieure",
        "Ne sacrifie jamais la sécurité à une limite de mots ou de puces",
    )),
])
def test_first_read_is_actionable_without_hiding_safety(locale, required):
    """The first read must suffice even if a mother cannot open anything else."""
    rule = CONTRACTS[locale].language_rule
    for clause in required:
        assert clause in rule


@pytest.mark.parametrize("locale, required", [
    ("es", (
        "madre ocupada con un bebé llorando",
        "historial personal solo si está realmente en el contexto y cítalo",
        "No prometas un diagnóstico ni inventes consejos tranquilizadores",
        "No impongas secciones fijas ni vacías",
        "lectura opcional para después está en las fuentes",
        "sin necesitar un resumen clínico heurístico de la interfaz",
    )),
    ("en", (
        "busy mother with a crying baby",
        "personal history only if actually present in context and cite it",
        "Do not promise a diagnosis or invent soothing advice",
        "Do not impose fixed or empty sections",
        "optional later reading belongs in the sources",
        "without needing a heuristic clinical summary from the interface",
    )),
    ("fr", (
        "mère occupée avec un bébé qui pleure",
        "antécédents personnels que s’ils figurent réellement dans le contexte et cite-les",
        "Ne promets pas de diagnostic et n’invente pas de conseils rassurants",
        "N’impose pas de rubriques fixes ou vides",
        "lecture facultative pour plus tard se trouve dans les sources",
        "sans nécessiter un résumé clinique heuristique de l’interface",
    )),
])
def test_personalization_is_grounded_and_later_reading_is_optional(locale, required):
    rule = CONTRACTS[locale].language_rule
    for clause in required:
        assert clause in rule
