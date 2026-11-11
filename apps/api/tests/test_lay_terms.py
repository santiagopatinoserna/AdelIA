"""A mother's words, rendered in the corpus's clinical Spanish for the search.

Measured in production on 2026-11-05 (30 real questions, cut-off 0.19): the
library has diaper dermatitis, hand-foot-mouth, conjunctivitis and croup, and
"Tiene el culito muy rojo del pañal", "Le han salido granitos en las manos y en
la boca", "Tiene un ojo con legañas amarillas" and "Lleva 4 días sin hacer caca"
were refused as if it had none. The fragments name the condition ("Tema:
síntomas y causas de la dermatitis del pañal"); her sentence names what she
sees. docs/specs/RECUPERACION_LENGUAJE_MADRE.md has the diagnosis.

What these tests pin about the lexicon (agent/lay_terms.py):

  * each entry turns her words into the terms the fragments use;
  * no false friend: "cacahuete" is not "caca", a dog in the house is not a
    barking cough, a red stool in the nappy is not diaper dermatitis;
  * every term it adds is written somewhere in the pediatric corpus, so the
    lexicon can only point at what the library holds;
  * none of the group B questions of the golden set gets a single term: a
    near miss must stay as far from the corpus as it is today.
"""
from __future__ import annotations

import json
import unicodedata

import pytest

from adelia.agent.lay_terms import LEXICON, clinical_terms, expanded_query
from adelia.clinical.golden import CORPUS_DATA_DIR, questions, written_2026_11_06


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


# --- each entry, in her words -------------------------------------------------

@pytest.mark.parametrize(("message", "expected"), [
    # The seven production misses (2026-11-05) that the lexicon can reach.
    ("Lleva 4 días sin hacer caca y toma pecho, ¿es normal?", {"estreñimiento", "deposiciones"}),
    ("Tiene el culito muy rojo del pañal", {"dermatitis del pañal"}),
    ("Le han salido granitos en las manos y en la boca", {"síndrome boca mano pie", "exantema"}),
    ("Tiene un ojo con legañas amarillas", {"conjuntivitis", "secreción"}),
    ("¿Cuándo se le cae el cordón umbilical y cómo lo cuido?", {"muñón"}),
    ("Tiene tos de perro por la noche", {"laringitis", "crup"}),
    # The rest of the corpus's topics, said the way a mother says them.
    ("No ha hecho caca desde el sábado", {"estreñimiento"}),
    ("Le cuesta mucho hacer caca y llora", {"estreñimiento"}),
    ("Hace las cacas muy duras", {"estreñimiento"}),
    ("¿Cuántas cacas al día son normales?", {"deposiciones", "heces"}),
    ("Tiene el culete irritado", {"dermatitis del pañal"}),
    ("Tiene rozaduras del pañal", {"dermatitis del pañal"}),
    ("Le han salido ampollas en los pies y llagas en la boca", {"síndrome boca mano pie"}),
    ("Le ha salido un sarpullido en la tripa", {"exantema"}),
    ("Se levanta con los ojos pegados", {"conjuntivitis"}),
    ("Le llora un ojo todo el rato", {"lagrimeo", "obstrucción del conducto lagrimal"}),
    ("Tiene muchos mocos y la nariz tapada", {"congestión nasal", "catarro"}),
    ("Tose como un perro", {"laringitis", "crup"}),
    ("Tiene una tos perruna muy fea", {"laringitis", "crup"}),
    ("Le huele mal el ombligo", {"cordón umbilical"}),
    ("Tiene el ombligo salido", {"hernia umbilical"}),
    ("Echa la leche después de cada toma", {"regurgitación", "reflujo"}),
    ("Le están saliendo los dientes y babea muchísimo", {"dentición"}),
    ("Se toca mucho la oreja y llora", {"otitis"}),
    ("Creo que está un poco bizca", {"estrabismo"}),
    ("Tiene la cabeza plana por detrás", {"plagiocefalia"}),
    ("Tiene costras en la cabeza", {"costra láctea"}),
    ("Llora al hacer pis y le huele fuerte", {"infección de orina"}),
    ("Tiene un bulto en la ingle", {"hernia inguinal"}),
    ("Tiene la piel muy seca y áspera", {"dermatitis atópica"}),
    # When the translation fails, her French or English reaches the lexicon as written.
    ("My 8-month-old hasn't had a poo in four days", {"estreñimiento"}),
    ("Il a les fesses rouges", {"dermatitis del pañal"}),
    ("Mon bébé a les fesses toutes rouges", {"dermatitis del pañal"}),
    ("She has a red sore bottom from the nappy", {"dermatitis del pañal"}),
    ("Il a des boutons sur les mains et dans la bouche", {"síndrome boca mano pie"}),
    ("He has spots on his hands and feet", {"síndrome boca mano pie"}),
    ("Elle a les yeux collés le matin", {"conjuntivitis"}),
    ("He has a sticky eye", {"conjuntivitis"}),
    ("Il a le nez bouché", {"congestión nasal"}),
    ("She has a runny nose", {"congestión nasal"}),
    ("Il a une toux de phoque", {"laringitis", "crup"}),
    ("He has a barking cough at night", {"laringitis", "crup"}),
    ("Quand tombe le cordon du nombril ?", {"cordón umbilical"}),
    ("When does the belly button stump fall off?", {"cordón umbilical"}),
])
def test_her_words_get_the_corpus_terms(message, expected):
    terms = set(clinical_terms(message))
    assert expected <= terms, f"{message!r} -> {sorted(terms)}"


@pytest.mark.parametrize(("message", "expected"), [
    # Prod 2026-11-06 (lay-language-eval.json): L22 stayed at 0.217 with 19 sleep
    # sources in the corpus, and L21 reached the lexicon translated as "manchas".
    ("No duerme nada por la noche, se despierta cada hora",
     {"despertares nocturnos", "sueño del bebé"}),
    ("Tiene manchas en las manos y en la boca", {"síndrome boca mano pie"}),
    ("Se despierta cinco veces cada noche", {"despertares nocturnos"}),
    ("Duerme fatal desde hace una semana", {"despertares nocturnos"}),
    ("Il se réveille toutes les heures la nuit", {"despertares nocturnos"}),
    ("She wakes up every hour at night", {"despertares nocturnos"}),
    # Other complaints mothers of 0-24 months bring every day.
    ("No come nada desde hace dos días", {"falta de apetito", "inapetencia"}),
    ("No quiere comer y come muy poco", {"falta de apetito"}),
    ("No quiere el biberón", {"rechazo del alimento"}),
    ("Il ne mange plus rien", {"falta de apetito"}),
    ("He won't eat anything", {"falta de apetito"}),
    ("Ha vomitado dos veces esta mañana", {"vómitos"}),
    ("Vomita después de comer", {"vómitos"}),
    ("He has been throwing up since lunch", {"vómitos"}),
    ("Suda mucho cuando duerme", {"sudoración"}),
    ("Se queda empapado de sudor por la noche", {"sudoración"}),
    ("Ronca mucho por la noche", {"ronquido"}),
    ("Respira con mucho ruido pero no tiene fiebre", {"respiración ruidosa", "ronquido"}),
    ("He snores every night", {"ronquido"}),
])
def test_her_everyday_complaints_get_the_corpus_terms(message, expected):
    terms = set(clinical_terms(message))
    assert expected <= terms, f"{message!r} -> {sorted(terms)}"


def test_milk_that_comes_back_up_stays_reflux_not_vomiting():
    """"Vomita la leche" after a feed is what the reflux entry was written for;
    the vomiting entry yields to it rather than pulling gastroenteritis in."""
    terms = clinical_terms("Vomita la leche después de cada toma")
    assert "regurgitación" in terms
    assert "vómitos" not in terms


@pytest.mark.parametrize(("message", "absent"), [
    ("No se despierta para comer", "despertares nocturnos"),   # hard to wake, not wakings
    ("Me cuesta despertarlo por la mañana", "despertares nocturnos"),
    ("Le he puesto una sudadera", "sudoración"),               # sudadera is a jumper
    ("¿Qué come un bebé de 8 meses?", "falta de apetito"),      # what to eat, not refusing
    ("Il a vomi une fois", "vómitos"),                          # French: B13 is why
    ("Tose como un perro y está ronca", "ronquido"),            # hoarse, not snoring
    ("Tiene la voz ronca", "ronquido"),
])
def test_an_everyday_false_friend_gets_no_term(message, absent):
    assert absent not in clinical_terms(message)


# --- false friends ----------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "¿Puedo darle cacahuete a mi bebé de 8 meses?",          # caca-
    "Le da miedo el perro del vecino",                        # perro, no cough
    "Mi hija de 10 meses tiene los labios de la vulva pegados",  # pegados, no eye
    "Me saco leche con el sacaleches, ¿cuánto dura?",         # her milk, not reflux
    "¿Cómo le cepillo los dientes?",                          # teeth, not teething
    "Llora mucho por las tardes",                             # crying, not a weeping eye
    "¿A qué edad suelen empezar a gatear?",                   # no gap: the corpus says gatear
    "Le compré un cordón para el chupete",                    # a cord, not the navel
])
def test_a_false_friend_gets_no_term(message):
    assert clinical_terms(message) == ()


# --- the choking manoeuvre, asked in calm (A39, 2026-11-06) ----------------------
#
# Measured in production: "¿Cómo se hace la maniobra de los golpes en la espalda?"
# left «Soporte vital pediátrico» (ERC 2021) at 0.1977, past the 0.19 cut, with
# nothing under it. Her sentence names the manoeuvre; the fragments name what it
# is for. Any word of choking itself ("atragant...", "choking", "s'étouffe") is
# the red flag and never reaches the lexicon, so the entry reads the manoeuvre.

@pytest.mark.parametrize("message", [
    "¿Cómo se hace la maniobra de los golpes en la espalda? Quiero aprenderla antes de "
    "empezar con los sólidos",
    "Quiero aprender los golpes en la espalda de primeros auxilios para bebés",
    "¿Qué es la maniobra de desobstrucción del lactante?",
    "How do I do back blows on a baby? I want to learn before starting solids",
    "Comment on fait les claques dans le dos à un bébé ?",
])
def test_the_manoeuvre_she_wants_to_learn_gets_choking(message):
    assert "atragantamiento" in clinical_terms(message), message


@pytest.mark.parametrize("message", [
    "¿Le doy golpecitos en la espalda para que eche los gases?",   # burping
    "¿Cómo le doy golpes en la espalda para que eructe?",
    "Quiero aprender a darle golpes en la espalda para que eche el aire",
    "Se dio un golpe en la espalda al caerse de la cama",          # a fall
    "Le doy palmaditas en la espalda para que se duerma",
    "Should I pat her back to burp her?",
    "Je lui tapote le dos pour son rot",
])
def test_a_pat_on_the_back_is_not_the_choking_manoeuvre(message):
    assert "atragantamiento" not in clinical_terms(message), message


@pytest.mark.parametrize(("message", "locale"), [
    ("Se está atragantando, ¿le hago la maniobra de los golpes en la espalda?", "es"),
    ("Se ha puesto morado comiendo, ¿le hago la maniobra de los golpes en la espalda?", "es"),
    ("He's choking, should I do back blows?", "en"),
    ("Il s'étouffe, je fais les claques dans le dos ?", "fr"),
])
def test_choking_now_is_a_red_flag_before_the_lexicon_reads_it(message, locale):
    """The entry matches these too; the guard answers them first, with the
    referral, on her original text (agent/graph.py: guard before retrieve)."""
    from adelia.clinical.red_flags import detect

    assert detect(message, locale=locale, age_months=6) is not None, message
    assert "atragantamiento" in clinical_terms(message), message


# --- a bump on the head (the battery with the real model, 2026-11-11) -------------
#
# "se ha caido de la cama y se ha dado en la cabeza" found one fragment on preventing
# falls and a plan that opened on "puede causar fractura de cráneo" with nothing to
# do; the SEUP sheet for parents ("Tema: qué hacer en casa tras un golpe en la
# cabeza", then "signos de empeoramiento y cuándo acudir a urgencias") only came on
# the next turn, when she wrote "chichón". Her sentence says what happened; the
# sheet names the injury.

@pytest.mark.parametrize("message", [
    "se ha caido de la cama y se ha dado en la cabeza",
    "Se ha caído de la cama y se ha dado un golpe",
    "se ha dado en la cabeza",
    "Se ha dado un golpe en la cabeza con la mesa",
    "se dio con la cabeza contra el suelo",
    "Se ha golpeado la cabeza",
    "se cayó del cambiador",
    "Se me ha caído de los brazos",
    "se ha caido del sofa y llora",
    "Le ha salido un chichón en la frente",
    "se ha dado un cabezazo con la cuna",
    "Se ha caído de la cama y se ha dado un golpe\nllora pero se calma en brazos",  # held
    "He fell off the bed and hit his head",
    "She bumped her head on the table",
    "Il est tombé du lit",
    "Elle s'est cognée la tête contre la table",
])
def test_a_bump_on_the_head_gets_the_head_injury_terms(message):
    terms = clinical_terms(message)
    assert "traumatismo craneal" in terms, f"{message!r} -> {terms}"
    assert "golpe en la cabeza" in terms or "golpe en la cabeza" in _plain(message)


@pytest.mark.parametrize("message", [
    "Se ha caído y se ha dado un golpe en la rodilla",       # another part of the body
    "Se dio un golpe en la espalda al caerse de la cama",    # the back, not the head
    "Se ha caído de la cama y se ha hecho daño en el brazo",
    "Se ha caído y se ha dado en la boca, le sangra el labio",
    "¿Le doy golpecitos en la espalda para que eche los gases?",
    "Se le cae mucho el pelo",
    "¿Cuándo se le cae el cordón?",
    "Se me ha caído el chupete al suelo, ¿lo lavo?",
    "Le duele la cabeza",                                    # a headache, not a bump
    "Tiene la cabeza plana por detrás",
    "He hit his knee on the table",
    "Il est tombé et s'est cogné le genou",
])
def test_a_bump_elsewhere_or_a_fall_of_something_else_gets_no_head_terms(message):
    assert "traumatismo craneal" not in clinical_terms(message), message


def test_a_head_injury_with_a_red_flag_is_referred_before_the_lexicon():
    """The entry reads it too; the guard refers it first, on her own words."""
    from adelia.clinical.red_flags import detect

    message = "Se ha caído de la cama, se ha dado en la cabeza y ahora no se despierta"
    assert detect(message, locale="es", age_months=11) is not None
    assert "traumatismo craneal" in clinical_terms(message)


def test_red_stool_in_the_nappy_is_stool_not_diaper_dermatitis():
    terms = clinical_terms("Tiene caca roja en el pañal")
    assert "deposiciones" in terms
    assert "dermatitis del pañal" not in terms


def test_spots_in_the_nappy_area_are_the_nappy_not_a_rash():
    terms = clinical_terms("Le han salido granitos en el culito")
    assert "dermatitis del pañal" in terms
    assert "exantema" not in terms


def test_a_navel_that_sticks_out_is_the_hernia_not_the_cord():
    terms = clinical_terms("Tiene el ombligo salido")
    assert "hernia umbilical" in terms
    assert "cordón umbilical" not in terms


# --- what the lexicon may add -------------------------------------------------

def _corpus_text() -> str:
    parts: list[str] = []
    for path in sorted(CORPUS_DATA_DIR.glob("evidence_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for source in payload["sources"]:
            if "pediatrics" in (source.get("specialties") or []):
                parts.append(source["title"])
                parts.extend(source["chunks"])
    return _plain(" ".join(parts))


def test_every_term_is_written_in_the_pediatric_corpus():
    """The lexicon points at what the library holds, never at a word of its own."""
    corpus = _corpus_text()
    missing = sorted({t for e in LEXICON for t in e.terms if _plain(t) not in corpus})
    assert missing == []


def test_every_entry_has_a_name_patterns_and_terms():
    names = [e.name for e in LEXICON]
    assert len(names) == len(set(names))
    for entry in LEXICON:
        assert entry.patterns and entry.terms, entry.name


def test_a_term_she_already_wrote_is_not_repeated():
    terms = clinical_terms("¿Cuándo se le cae el cordón umbilical y cómo lo cuido?")
    assert "cordón umbilical" not in terms


def test_terms_come_once_in_lexicon_order():
    terms = clinical_terms("Lleva 4 días sin hacer caca, y las cacas son duras")
    assert len(terms) == len(set(terms))


def test_the_expanded_query_is_her_text_then_the_terms():
    message = "Tiene el culito muy rojo del pañal"
    out = expanded_query(message)
    assert out is not None
    assert out.startswith(message + "\n")
    assert "dermatitis del pañal" in out.split("\n", 1)[1]


@pytest.mark.parametrize("message", ["", "   ", "¿Cuánto tiempo de pantalla puede ver?"])
def test_nothing_to_add_is_none(message):
    assert expanded_query(message) is None


def test_the_lexicon_is_accent_and_case_blind():
    assert clinical_terms("TIENE LEGANAS") == clinical_terms("tiene legañas")


# --- group B of the golden set ------------------------------------------------

@pytest.mark.parametrize("question", questions("B"), ids=lambda q: q.id)
def test_no_group_b_question_gets_a_term(question):
    """Each of the 18 group B questions read against the lexicon, one by one.

    B2 ("¿Es normal que no gatee a los 9 meses?") is the reason there is no
    crawling entry: the corpus already writes gatear, gatean and gateo, so
    there is no gap to close, and any entry for it would pull B2 towards the
    motor-milestone fragments. B8 (yellow skin at 4 months) is why yellow is
    not mapped to jaundice, B11 (trapped wind) why gas is not mapped to colic,
    and B13 and B14 why French diarrhoea and first teeth have no entry.
    """
    assert clinical_terms(question.question) == ()
    assert expanded_query(question.question) is None


def test_the_b_group_is_the_eighteen_this_review_covered():
    """The fifteen, plus B18, B20 and B26 since they passed in production on
    2026-11-06 (each read against the lexicon as a candidate first)."""
    assert [q.id for q in questions("B")] == [
        "B1", "B2", "B3", "B4", "B6", "B7", "B8", "B9",
        "B11", "B12", "B13", "B14", "B15", "B16", "B17", "B18", "B20", "B26",
    ]


@pytest.mark.parametrize(
    "question", [q for q in written_2026_11_06() if q.group == "B"], ids=lambda q: q.id
)
def test_no_candidate_b_question_gets_a_term(question):
    """The B questions of 2026-11-06 (clinical/golden.CANDIDATES until they
    join the gate) obey the same rule first: the expansion is on in production,
    so a term here would pull a near miss towards the corpus. B24 says
    "bolitas" and not "granitos" for this reason."""
    assert clinical_terms(question.question) == ()
