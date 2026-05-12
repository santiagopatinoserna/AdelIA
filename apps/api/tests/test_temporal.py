from datetime import date, timedelta

from adelia.services.temporal import TemporalIntent, detect_temporal_intent


def test_detect_curva_pattern():
    intent = detect_temporal_intent("dame la curva de glucosa de los últimos 5 años")
    assert intent is not None
    assert intent.entity_name == "glucosa"
    assert intent.from_date <= date.today() - timedelta(days=5 * 365 - 30)
    assert intent.to_date == date.today()


def test_detect_tendencia_pattern():
    intent = detect_temporal_intent("¿cuál es la tendencia de mi colesterol en los últimos 2 años?")
    assert intent is not None
    assert intent.entity_name == "colesterol"


def test_detect_evolution_pattern():
    intent = detect_temporal_intent("muéstrame la evolución de mi presión arterial")
    assert intent is not None
    assert intent.entity_name == "presión arterial"
    assert intent.from_date is None
    assert intent.to_date is None


def test_non_temporal_query_returns_none():
    assert detect_temporal_intent("¿qué medicamentos tomo actualmente?") is None


def test_temporal_with_explicit_date_range():
    intent = detect_temporal_intent("curva de hemoglobina desde 2020 hasta 2024")
    assert intent is not None
    assert intent.entity_name == "hemoglobina"
    assert intent.from_date == date(2020, 1, 1)
    assert intent.to_date == date(2024, 12, 31)


def test_temporal_intent_emits_lowercase_normalized_entity_name():
    intent = detect_temporal_intent("Curva de GLUCOSA últimos 3 años")
    assert intent.entity_name == "glucosa"


def test_temporal_with_meses():
    intent = detect_temporal_intent("evolución de mi azúcar los últimos 6 meses")
    assert intent is not None
    assert intent.from_date >= date.today() - timedelta(days=6 * 31)


def test_temporal_handles_del_contraction():
    intent = detect_temporal_intent("curva del colesterol últimos 3 años")
    assert intent is not None
    assert intent.entity_name == "colesterol"
