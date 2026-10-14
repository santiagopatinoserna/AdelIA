"""The red-flag detector, language by language (golden set work, hole 1).

`tests/test_red_flags.py` pins the Spanish-first behaviour and a handful of
cross-language phrases. This file asks a different question: for each of the
eleven flags, does the detector know how a parent actually WRITES it in each
of the three shipped locales?

The phrases below are not translations of one another. A French parent says
"il a avalé de travers", not "il s'est étouffé"; an English parent says "she
went floppy" and "a 2-month-old", not "hypotonia" and "2 months". A detector
that only knows the Spanish symptom words (or that knows the French words but
not the French way of writing an age) passes every Spanish test and fails the
child it exists for, which is why the corpus of phrases lives here rather
than being derived from the Spanish table.

Rules for adding a case, which keep this file honest:

* A positive is a sentence a real parent would send. If the detector misses
  it, fix the detector; do not reword the sentence until it passes.
* Every flag must have at least two positives in every language, enforced by
  `test_every_flag_has_two_positives_in_every_language`.
* A negative is an ordinary question the detector must leave alone. A
  detector that fires on everything is ignored, so the negatives are as
  load-bearing as the positives.
"""
from __future__ import annotations

import pytest

from adelia.clinical.red_flags import PRIORITY, age_months_in, detect, temperature_in

LOCALES = ("es", "en", "fr")

# (locale, expected code, sentence, profile age in months or None)
POSITIVES: list[tuple[str, str, str, int | None]] = [
    # --- choking -----------------------------------------------------------
    ("es", "choking", "Se atragantó con una uva y se puso morado", 11),
    ("es", "choking", "Se ha tragado una moneda", 11),
    ("en", "choking", "She is choking on a grape and can't cough", 11),
    ("en", "choking", "He's gagging on a piece of apple and can't make a sound", 11),
    ("fr", "choking", "Il s'est étouffé avec une cacahuète", 11),
    ("fr", "choking", "Elle a avalé de travers et n'arrive plus à tousser", 11),
    # --- anaphylaxis -------------------------------------------------------
    ("es", "anaphylaxis", "Se le hincharon los labios y la cara después del cacahuete", 12),
    ("es", "anaphylaxis", "Le ha salido una reacción alérgica grave tras probar el huevo", 12),
    ("en", "anaphylaxis", "Her face and lips swelled up after peanut butter", 12),
    ("en", "anaphylaxis", "He came out in hives and his tongue is swollen after egg", 12),
    ("fr", "anaphylaxis", "Son visage et ses lèvres ont gonflé après l'arachide", 12),
    ("fr", "anaphylaxis", "Il a fait un œdème de Quincke après l'œuf", 12),
    # --- cyanosis ----------------------------------------------------------
    ("es", "cyanosis", "Tiene los labios azules", 3),
    ("es", "cyanosis", "Se ha puesto morado mientras lloraba", 3),
    ("en", "cyanosis", "His lips look blue", 3),
    ("en", "cyanosis", "She's gone grey and blue around the mouth", 3),
    ("fr", "cyanosis", "Ses lèvres sont bleues", 3),
    ("fr", "cyanosis", "Elle devient bleue quand elle pleure", 3),
    # --- seizure -----------------------------------------------------------
    ("es", "seizure", "Ha tenido una convulsión de un minuto", 10),
    ("es", "seizure", "Se quedó rígido, con los ojos en blanco y sacudidas en los brazos", 10),
    ("en", "seizure", "She had a seizure ten minutes ago", 10),
    ("en", "seizure", "He went stiff, his eyes rolled back and his arms were jerking", 10),
    ("fr", "seizure", "Il a fait une crise convulsive", 10),
    ("fr", "seizure", "Elle s'est raidie, les yeux révulsés, avec des secousses des bras", 10),
    # --- respiratory distress ---------------------------------------------
    ("es", "respiratory_distress", "Respira muy rápido y se le hunden las costillas", 5),
    ("es", "respiratory_distress", "Mi bebé no respira bien y hace un ruido como un quejido", 5),
    ("en", "respiratory_distress", "He's grunting with every breath", 5),
    ("en", "respiratory_distress", "She is breathing really fast and the skin under her ribs pulls in", 5),
    ("fr", "respiratory_distress", "Elle a un geignement à chaque respiration", 5),
    ("fr", "respiratory_distress", "Il respire très vite et le ventre se creuse à chaque respiration", 5),
    # --- non-blanching rash -----------------------------------------------
    ("es", "non_blanching_rash", "Tiene puntitos rojos que no desaparecen al apretar con un vaso", 14),
    ("es", "non_blanching_rash", "Tiene petequias en las piernas", 14),
    ("en", "non_blanching_rash", "She has spots on her tummy that don't go away when I press a glass on them", 14),
    ("en", "non_blanching_rash", "A rash that doesn't fade when I press it", 14),
    ("fr", "non_blanching_rash", "Il a des taches rouges qui ne disparaissent pas quand j'appuie dessus", 14),
    ("fr", "non_blanching_rash", "Des petits points rouges qui ne s'effacent pas avec le test du verre", 14),
    # --- bulging fontanelle -----------------------------------------------
    ("es", "bulging_fontanelle", "La fontanela de la cabeza la tiene abombada y dura", 4),
    ("es", "bulging_fontanelle", "Le noto la mollera hinchada", 4),
    ("en", "bulging_fontanelle", "The soft spot on top of his head looks swollen and bulging", 4),
    ("en", "bulging_fontanelle", "Her fontanelle looks tense and raised", 4),
    ("fr", "bulging_fontanelle", "La fontanelle sur le dessus de sa tête est bombée", 4),
    ("fr", "bulging_fontanelle", "On dirait que sa fontanelle est gonflée et tendue", 4),
    # --- lethargy ----------------------------------------------------------
    ("es", "lethargy", "No hay forma de despertarlo para la toma", 4),
    ("es", "lethargy", "No consigo despertarla y está muy flojita", 4),
    ("en", "lethargy", "He is floppy and I can't wake him", 4),
    ("en", "lethargy", "She won't wake up for her feed", 4),
    ("fr", "lethargy", "Elle est molle et je n'arrive pas à la réveiller", 4),
    ("fr", "lethargy", "Il ne se réveille pas pour le biberon", 4),
    # --- dehydration -------------------------------------------------------
    ("es", "dehydration", "Tiene los ojos hundidos y llora sin lágrimas", 9),
    ("es", "dehydration", "Tiene la boca muy seca y la mollera hundida", 9),
    ("en", "dehydration", "Her eyes look sunken and she cries without tears", 9),
    ("en", "dehydration", "He has a very dry mouth and sunken eyes", 9),
    ("fr", "dehydration", "Il a les yeux creux et pleure sans larmes", 9),
    ("fr", "dehydration", "Elle a la bouche sèche et les yeux enfoncés", 9),
    # --- no wet nappy ------------------------------------------------------
    ("es", "no_wet_nappy_12h", "Lleva 14 horas sin mojar el pañal", 8),
    ("es", "no_wet_nappy_12h", "El pañal está seco desde hace 13 horas", 8),
    ("en", "no_wet_nappy_12h", "No wet nappy for 14 hours", 8),
    ("en", "no_wet_nappy_12h", "Her nappy has stayed dry since last night, about 15 hours", 8),
    ("fr", "no_wet_nappy_12h", "Pas de couche mouillée depuis 14 heures", 8),
    ("fr", "no_wet_nappy_12h", "Il n'a pas mouillé sa couche depuis 14 h", 8),
    # --- fever under 3 months: age and temperature written the local way ---
    ("es", "fever_under_3_months", "Mi bebé de dos meses tiene 38,5 de fiebre", None),
    ("es", "fever_under_3_months", "Tiene 3 semanas y 38 de fiebre", None),
    ("en", "fever_under_3_months", "My 2-month-old has a temperature of 38.4", None),
    ("en", "fever_under_3_months", "She is 7 weeks old and she feels really hot", None),
    ("en", "fever_under_3_months",
     "She's only six weeks old, she feels burning hot and the thermometer says 100.8 F", None),
    ("fr", "fever_under_3_months", "Elle a 38,2 et elle a 2 mois, je lui donne du Doliprane ?", None),
    ("fr", "fever_under_3_months", "Mon bébé de deux mois est brûlant, le thermomètre indique 38", None),
]


@pytest.mark.parametrize(
    "locale,code,sentence,age",
    POSITIVES,
    ids=[f"{loc}-{code}-{i}" for i, (loc, code, _s, _a) in enumerate(POSITIVES)],
)
def test_a_parent_in_each_language_triggers_the_right_flag(locale, code, sentence, age):
    flag = detect(sentence, locale=locale, age_months=age)
    got = flag.code if flag else None
    assert got == code, f"[{locale}] {sentence!r} -> {got}"


def test_every_flag_has_two_positives_in_every_language():
    """A flag added to PRIORITY without all three languages fails here."""
    for code in PRIORITY:
        for locale in LOCALES:
            n = sum(1 for loc, c, _s, _a in POSITIVES if loc == locale and c == code)
            assert n >= 2, f"{code} has {n} positive(s) for locale {locale!r}; need 2"


# Ordinary questions. Several carry a number or a word that sits next to a
# red-flag pattern on purpose (37,2; 38 weeks; "sleepy"), because that is
# where a widened pattern starts to over-fire.
NEGATIVES: list[tuple[str, str, int | None]] = [
    ("es", "¿A qué edad puede empezar mi bebé con el huevo?", 7),
    ("es", "Mi bebé de 8 meses tiene 37,2, ¿es normal?", None),
    ("es", "Mi bebé de 2 meses pesa 5,4 kg y mide 58 cm, ¿va bien?", None),
    ("es", "Nació a las 38 semanas y ahora tiene 2 meses, ¿cuándo toca la vacuna?", None),
    ("es", "Está muy dormilón después de las vacunas pero come bien", 5),
    ("es", "¿Cuántos pañales mojados al día son normales?", 5),
    ("en", "At what age can my baby start eating eggs?", 7),
    ("en", "My 8-month-old has a temperature of 37.2, is that normal?", None),
    ("en", "My 2-month-old weighs 5.4 kg and is 58 cm long, is that on track?", None),
    ("en", "She was born at 38 weeks and is now 2 months old, when is the next jab?", None),
    ("en", "He is sleepy after his vaccines but he is feeding well", 5),
    ("en", "How many wet nappies a day are normal?", 5),
    ("en", "My baby's bath water feels hot, is that safe for a 2-month-old?", None),
    ("fr", "À quel âge mon bébé peut-il manger des œufs ?", 7),
    ("fr", "Mon bébé de 8 mois a 37,2, est-ce normal ?", None),
    ("fr", "Mon bébé de 2 mois pèse 5,4 kg et mesure 58 cm, est-ce que ça va ?", None),
    ("fr", "Elle est née à 38 semaines et a maintenant 2 mois, quand est le prochain vaccin ?", None),
    ("fr", "Il est un peu endormi après le vaccin mais il boit bien", 5),
    ("fr", "Combien de couches mouillées par jour sont normales ?", 5),
    # Words that sit next to a flag's vocabulary without being the flag: a gait,
    # a newborn's startle, a bath. Each is a real thing a parent asks.
    ("en", "My 14-month-old has a limp since yesterday, should I worry?", 14),
    ("es", "Mi bebé de 3 meses da sacudidas al dormirse, ¿es el reflejo de Moro?", 3),
    ("en", "He gets little jerks when he falls asleep, is that the startle reflex?", 3),
    ("fr", "Il a des secousses quand il s'endort, est-ce le réflexe de Moro ?", 3),
    ("fr", "L'eau du bain est chaude, est-ce sans danger pour un bébé de 2 mois ?", None),
]


@pytest.mark.parametrize(
    "locale,sentence,age",
    NEGATIVES,
    ids=[f"{loc}-{i}" for i, (loc, _s, _a) in enumerate(NEGATIVES)],
)
def test_ordinary_questions_in_each_language_do_not_fire(locale, sentence, age):
    flag = detect(sentence, locale=locale, age_months=age)
    assert flag is None, f"[{locale}] {sentence!r} fired {flag}"


def test_matching_is_language_agnostic_whatever_the_locale():
    """Locale picks the language of the ANSWER; it never narrows the detection.

    A Spanish-locale session where the grandmother types in French is real,
    and the safe direction is to fire.
    """
    assert detect("Il a fait une crise convulsive", locale="es", age_months=10) is not None
    assert detect("Se atragantó con una uva", locale="fr", age_months=10) is not None
    assert detect("He's grunting with every breath", locale="fr", age_months=5) is not None


# --- how a parent writes an age -------------------------------------------


@pytest.mark.parametrize("text,months", [
    ("a 2-month-old", 2),
    ("my 6-week-old", 1),
    ("mi bebé de dos meses", 2),
    ("mi bebé de tres semanas", 0),
    ("my baby is two months old", 2),
    ("she is six weeks old", 1),
    ("mon bébé a deux mois", 2),
    ("il a trois semaines", 0),
    ("elle a 5 semaines", 1),
])
def test_ages_written_with_words_or_hyphens_are_read(text, months):
    assert age_months_in(text) == months


# --- how a parent writes a temperature --------------------------------------


@pytest.mark.parametrize("text,celsius", [
    ("the thermometer says 100.8 F", 38.2),
    ("fever of 101°F", 38.3),
    ("100.4 fahrenheit", 38.0),
    ("le thermomètre indique 38", 38.0),
    ("el termómetro marca 38,4", 38.4),
])
def test_temperatures_in_fahrenheit_or_after_a_thermometer_word_are_read(text, celsius):
    assert temperature_in(text) == pytest.approx(celsius, abs=0.1)


def test_a_fahrenheit_looking_number_without_a_unit_is_not_a_temperature():
    """100 is a weight in grams, a count, a price; only "100.8 F" is a reading."""
    assert temperature_in("pesa 100 gramos más que el mes pasado") is None
    assert temperature_in("he has gained 100 grams") is None
