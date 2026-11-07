"""Candidate sources of 2026-11-06, one file per domain of data/, measured before boot.

Six research agents gathered pages in thirteen languages (German, Dutch, the
Nordic languages, English, French, Italian, Portuguese, Polish, Arabic,
Japanese, Korean and Spanish) and summarised each one in Spanish
(~/dev/adelia-night/research/corpus-*). They were merged, deduplicated against
data/ and between themselves, and filtered (docs/corpus/CANDIDATOS_2026_11_06.md):
pages whose terms forbid adapting, translating or commercial use are out,
other countries' vaccine calendars are out, emergency numbers and services of
other health systems were rewritten in words with the source's urgency, and
every chunk about alarm signs, urgency, fever, breathing, seizures,
dehydration, jaundice or sepsis was checked again against the page text
downloaded with curl, because the verifier agent had only seen WebFetch's
summary of it.

They live in adelia/enrichment/candidates/lote_2026_11_06/, which boot never
reads, until the golden gate has measured them (scripts/golden_gate.sh
--candidates). The directory is its own so that the Europe PMC candidate
rules (verbatim CC BY abstracts in English, tests/test_harvest_europepmc.py)
and these (Spanish paraphrases of pages in other languages) never apply to
each other's files. Moving one into production is a single rename:

    git mv adelia/enrichment/candidates/lote_2026_11_06/<domain>.json \\
           adelia/enrichment/data/evidence_<domain>_2026_11.json

and these tests follow it there, where tests/test_evidence_files.py also
starts reading it. Each file passes now the same rules as the domain files
in data/ (tests/evidence_corpus_checks.py), plus the three a translated
source needs: the page's language kept apart from the chunks' language, no
service of another health system, and no second copy of a page under another
URL or of a document under another title spelling.
"""
from __future__ import annotations

import fnmatch
import re
import importlib.util
import sys
from pathlib import Path

import pytest

from tests import evidence_corpus_checks as checks
from tests import test_evidence_files as files_rules

API_DIR = Path(__file__).resolve().parents[1]
BATCH_DIR = checks.CANDIDATES_DIR / "lote_2026_11_06"
GENERIC = ("signos_alarma", "cuando_consultar")

#: domain -> (sources in the file, its topic vocabulary, the sub-topics that
#: hold at least two sources). The counts are pinned: a source added to or
#: dropped from a file without a measurement is a drift, like a golden
#: question changed silently. 2026-11-07: the gap rule (below) took feeding
#: from 120 to 38 and respiratory and sleep from 77 to 46, and B6 took one
#: cow's-milk allergy source out of digestive and skin (55 to 54), after the
#: server run that measured them (docs/corpus/CANDIDATOS_2026_11_06.md, 16).
DOMAINS: dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]] = {
    "alimentacion_bebes": (
        38,
        (
            "lactancia", "lactancia_tecnica", "problemas_lactancia",
            "extraccion_conservacion_leche", "destete", "biberon_retirada", "biberon_formula",
            "alimentacion_complementaria", "cuando_solidos", "senales_listo", "texturas",
            "alergenos", "alimentacion_12_24m", "bebidas", "suplementos",
            "seguridad_alimentaria", "inapetencia",
        ),
        (
            "lactancia", "lactancia_tecnica", "problemas_lactancia", "biberon_retirada",
            "biberon_formula", "alimentacion_complementaria", "texturas", "alergenos",
            "alimentacion_12_24m", "bebidas", "seguridad_alimentaria", "inapetencia",
        ),
    ),
    "desarrollo_0_24m": (
        54,
        (
            "hitos_motores", "lenguaje", "desarrollo_social", "sueno_horas", "denticion",
            "crecimiento", "revisiones", "vacunas",
        ),
        (
            "hitos_motores", "lenguaje", "desarrollo_social", "sueno_horas", "denticion",
            "crecimiento", "revisiones", "vacunas",
        ),
    ),
    "digestivo_piel": (
        54,
        (
            "colico", "llanto", "estrenimiento", "heces", "diarrea", "deshidratacion", "vomitos",
            "aplv", "dermatitis_atopica", "costra_lactea", "dermatitis_panal", "ictericia",
            "proteccion_solar", "molusco_contagioso", "bano_higiene",
        ),
        (
            "colico", "llanto", "estrenimiento", "heces", "diarrea", "deshidratacion", "vomitos",
            "aplv", "dermatitis_atopica", "costra_lactea", "dermatitis_panal",
            "proteccion_solar", "molusco_contagioso", "bano_higiene",
        ),
    ),
    "guarderia_adaptacion": (
        1,
        (
            "exclusion_guarderia",
        ),
        (),
    ),
    "infecciones_fiebre": (
        30,
        (
            "fiebre", "varicela", "roseola", "mano_pie_boca", "conjuntivitis", "infeccion_orina",
            "convulsion_febril",
        ),
        (
            "fiebre", "varicela", "roseola", "conjuntivitis", "convulsion_febril",
        ),
    ),
    "neonatal": (
        35,
        (
            "primeras_semanas", "cordon_umbilical", "ictericia_neonatal", "prueba_talon",
            "cribado_auditivo", "perdida_peso_inicial", "deposiciones_recien_nacido",
            "prematuros",
        ),
        (
            "primeras_semanas", "cordon_umbilical", "ictericia_neonatal", "prueba_talon",
            "cribado_auditivo", "perdida_peso_inicial", "deposiciones_recien_nacido",
            "prematuros",
        ),
    ),
    "ojos_oidos_boca_uro_neuro": (
        10,
        (
            "lagrimal_obstruido", "caries_fluor", "hernias", "plagiocefalia", "ortopedia",
            "espasmo_del_sollozo", "pendientes_perforacion",
        ),
        (
            "caries_fluor", "pendientes_perforacion",
        ),
    ),
    "pediatric_reflux": (
        2,
        (
            "reflujo_regurgitacion",
        ),
        (
            "reflujo_regurgitacion",
        ),
    ),
    "respiratorio_sueno": (
        46,
        (
            "resfriado_mocos", "lavados_nasales", "tos", "bronquiolitis", "laringitis",
            "sibilancias", "otitis", "respiracion_normal", "pausas_brue",
            "muerte_subita_sueno_seguro", "colecho", "chupete",
        ),
        (
            "resfriado_mocos", "lavados_nasales", "tos", "bronquiolitis", "sibilancias",
            "otitis", "respiracion_normal", "muerte_subita_sueno_seguro",
        ),
    ),
    "salud_madre_familia": (
        18,
        (
            "depresion_posparto", "cansancio_extremo", "llanto_inconsolable", "bebe_sacudido",
            "puerperio",
        ),
        (
            "depresion_posparto", "cansancio_extremo", "llanto_inconsolable", "bebe_sacudido",
            "puerperio",
        ),
    ),
    "seguridad": (
        47,
        (
            "caidas", "quemaduras", "intoxicaciones", "ahogamiento", "atragantamiento_objetos",
            "silla_coche", "juguetes", "sol_calor", "pantallas",
        ),
        (
            "caidas", "quemaduras", "intoxicaciones", "ahogamiento", "atragantamiento_objetos",
            "silla_coche", "juguetes", "sol_calor", "pantallas",
        ),
    ),
    "urgencias_lactante": (
        6,
        (
            "primeros_auxilios", "rcp_lactante",
        ),
        (
            "primeros_auxilios", "rcp_lactante",
        ),
    ),
}

#: The one place "dosis" is a word for injections, as in data/.
VACCINE_TOPICS = frozenset({"vacunas"})


def path_of(domain: str):
    candidate = BATCH_DIR / f"{domain}.json"
    moved = checks.DATA_DIR / f"evidence_{domain}_2026_11.json"
    return candidate if candidate.exists() else moved


def _others(domain: str):
    mine = path_of(domain).resolve()
    pool = sorted(checks.DATA_DIR.glob(checks.BOOT_GLOB)) + sorted(BATCH_DIR.glob("*.json"))
    return [p for p in pool if p.resolve() != mine]


def _data(domain: str) -> dict:
    return checks.load(path_of(domain))


NAMES = sorted(DOMAINS)


def test_the_batch_holds_one_file_per_domain_and_nothing_else():
    on_disk = {p.stem for p in BATCH_DIR.glob("*.json")}
    moved = {d for d in DOMAINS if (checks.DATA_DIR / f"evidence_{d}_2026_11.json").exists()}
    assert on_disk | moved == set(DOMAINS)
    assert not on_disk & moved, "a domain is both a candidate and in data/"
    in_data = {p.stem.removeprefix("evidence_") for p in checks.DATA_DIR.glob(checks.BOOT_GLOB)}
    assert set(DOMAINS) <= in_data, "a domain that data/ does not have"


@pytest.mark.parametrize("domain", NAMES)
def test_a_candidate_is_outside_what_boot_loads(domain):
    path = path_of(domain)
    if path.parent == BATCH_DIR:
        assert not fnmatch.fnmatch(path.name, checks.BOOT_GLOB)
        assert not path.resolve().is_relative_to(checks.DATA_DIR.resolve())
    else:
        assert fnmatch.fnmatch(path.name, checks.BOOT_GLOB)


@pytest.mark.parametrize("domain", NAMES)
def test_the_file_has_meta(domain):
    checks.check_meta(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_the_number_of_sources_is_the_one_measured(domain):
    n = DOMAINS[domain][0]
    checks.check_size(_data(domain), low=n, high=n)


@pytest.mark.parametrize("domain", NAMES)
def test_sources_have_the_shape_the_loader_and_cards_need(domain):
    checks.check_source_shape(_data(domain), (*DOMAINS[domain][1], *GENERIC))


@pytest.mark.parametrize("domain", NAMES)
def test_the_original_language_is_kept_apart_from_the_chunks(domain):
    checks.check_original_language(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_no_title_or_url_is_already_in_another_file(domain):
    checks.check_disjoint_from_other_files(path_of(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_no_page_or_document_is_already_in_another_file(domain):
    checks.check_disjoint_documents(path_of(domain), _others(domain))


@pytest.mark.parametrize(
    ("domain", "topic"), [(d, t) for d in NAMES for t in DOMAINS[d][2]]
)
def test_every_listed_subtopic_has_at_least_two_sources(domain, topic):
    checks.check_subtopic(_data(domain), topic)


@pytest.mark.parametrize("domain", NAMES)
def test_chunks_are_sized_attributed_and_spanish(domain):
    checks.check_chunks_are_sized_attributed_and_spanish(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_no_chunk_carries_a_dose(domain):
    checks.check_no_dose(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_no_chunk_names_a_medicine_or_remedy_except_to_warn(domain):
    allow = frozenset({"flúor"}) if domain == "ojos_oidos_boca_uro_neuro" else frozenset()
    checks.check_no_medicine(_data(domain), allow_near_miss=allow, vaccine_topics=VACCINE_TOPICS)


@pytest.mark.parametrize("domain", NAMES)
def test_ages_stay_inside_the_first_years(domain):
    checks.check_ages_stay_in_the_first_years(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_no_chunk_sends_a_parent_to_another_health_system(domain):
    checks.check_no_foreign_service(_data(domain))


@pytest.mark.parametrize("domain", NAMES)
def test_it_passes_the_rules_every_file_in_data_passes(domain):
    """tests/test_evidence_files.py reads data/ only; the same functions, here, now."""
    path = path_of(domain)
    files_rules.test_evidence_file_respects_db_constraints(path)
    files_rules.test_no_chunk_sends_a_parent_to_a_foreign_emergency_number(path)
    files_rules.test_every_source_has_a_publisher_that_is_not_a_url(path)
    files_rules.test_every_organization_is_spelled_the_canonical_way(path)
    files_rules.test_every_source_has_a_year_or_says_why_it_has_none(path)


@pytest.mark.parametrize("domain", NAMES)
def test_the_golden_gate_accepts_it_as_a_candidate(domain):
    """scripts/golden_candidates.py validates every file before loading any."""
    path = API_DIR / "scripts" / "golden_candidates.py"
    spec = importlib.util.spec_from_file_location("golden_candidates_for_lote", path)
    gc = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gc
    spec.loader.exec_module(gc)
    assert gc.validate(path_of(domain))["sources"]


@pytest.mark.parametrize("domain", NAMES)
def test_the_loader_reads_it(domain, monkeypatch):
    checks.check_the_loader_reads_it(path_of(domain), monkeypatch)


# --- the two new rules bite --------------------------------------------------------


def _one(chunk: str, **extra) -> dict:
    return {"sources": [{"title": "Feber hos barn (1177)", "language": "es",
                         "original_language": "sv", "chunks": [chunk], **extra}]}


@pytest.mark.parametrize("chunk", [
    "Si no puedes contactar, llama al 1177 para pedir consejo.",
    "En Portugal se llama a SNS 24 (808 24 24 24).",
    "Lo valora la enfermera del consultatiebureau.",
    "In Australia call 000 for an ambulance.",
])
def test_a_service_of_another_health_system_is_refused(chunk):
    with pytest.raises(AssertionError):
        checks.check_no_foreign_service(_one(chunk))


def test_the_publisher_named_in_the_attribution_is_not_a_service_to_call():
    """1177 Vårdguiden and SNS 24 publish pages; the attribution that opens
    every chunk names them like NHS or ameli. Only what the chunk tells a
    parent to do, after «Tema:», is about calling a service."""
    checks.check_no_foreign_service(_one(
        "Feber hos barn (1177 Vårdguiden, 2023). Tema: fiebre. Hallazgo: llama a emergencias."
    ))
    with pytest.raises(AssertionError):
        checks.check_no_foreign_service(_one(
            "Feber hos barn (1177 Vårdguiden, 2023). Tema: fiebre. Hallazgo: llama al 1177."
        ))


def test_a_french_service_is_a_service_of_a_mother_ameli_serves():
    """France is one of the two countries AdelIA serves: 15, 112 and 114 (by
    text message, for deaf people) are its own numbers."""
    checks.check_no_foreign_service(
        _one("Tema: urgencias. Hallazgo: llama al 15, al 112 o al 114 por SMS si no oyes.")
    )


def test_a_large_number_is_not_mistaken_for_an_emergency_line():
    checks.check_no_foreign_service(_one("Unos 4,8 casos por 100.000 niños; llama a emergencias."))
    checks.check_no_foreign_service(_one("La revisión reúne 116 ensayos con 98 000 mujeres."))


@pytest.mark.parametrize("extra", [
    {"language": "sv"}, {"original_language": "swedish"}, {"original_language": None},
    {"original_license": "CC BY-NC-ND"},
])
def test_the_language_rule_refuses_a_page_language_where_the_chunks_language_goes(extra):
    with pytest.raises(AssertionError):
        checks.check_original_language(_one("texto", **extra))


def test_the_same_page_under_another_spelling_of_its_url_is_a_duplicate(tmp_path):
    import json

    a, b = tmp_path / "a.json", tmp_path / "b.json"
    src = {"title": "Bronchiolitis (KidsHealth NZ)", "organization": "KidsHealth",
           "url": "https://www.kidshealth.org.nz/bronchiolitis/"}
    a.write_text(json.dumps({"sources": [src]}), encoding="utf-8")
    b.write_text(json.dumps({"sources": [{**src, "title": "Bronchiolitis (KidsHealth)",
                                          "url": "http://kidshealth.org.nz/bronchiolitis"}]}),
                 encoding="utf-8")
    with pytest.raises(AssertionError, match="same page"):
        checks.check_disjoint_documents(a, [b])


# --- titles a mother reads (2026-11-07) --------------------------------------------
#
# The first server run of this batch put «pludselig uventet spædbarnsdød
# (sundhed.dk)» and «krybbedød (SIDS)» on the cards of a Spanish question. A
# source read in a language other than Spanish, English or French shows its
# title translated into Spanish (the real title, translated, nothing added) and
# keeps the page's own in `original_title`, which the loader ignores.


@pytest.mark.parametrize("domain", NAMES)
def test_every_title_is_in_a_language_she_reads(domain):
    checks.check_title_in_a_language_she_reads(_data(domain))


@pytest.mark.parametrize(("title", "extra"), [
    ("Krybbedød (SIDS) (Helsenorge)", {"original_title": "Krybbedød (SIDS) (Helsenorge)"}),
    ("Muerte en la cuna (Helsenorge)", {}),
    ("النوم الآمن للرضيع", {"original_title": "النوم الآمن للرضيع"}),
    ("Muerte en la cuna (Helsenorge)", {"original_title": "Krybbedød (Helsenorge)",
                                        "chunks": ["Krybbedød (Helsenorge, 2024). Tema: x."]}),
])
def test_a_title_she_cannot_read_is_refused(title, extra):
    src = {"title": title, "original_language": "no",
           "chunks": [f"{title} (Helsenorge, 2024). Tema: x."], **extra}
    with pytest.raises(AssertionError):
        checks.check_title_in_a_language_she_reads({"sources": [src]})


def test_a_translated_title_keeps_the_publisher_s_own_name():
    """Kind en Gezin, Sundhed.dk and Kinder- und Jugendärzte im Netz are names, as NHS is."""
    checks.check_title_in_a_language_she_reads({"sources": [{
        "title": "Ictericia del recién nacido (Kinder- und Jugendärzte im Netz)",
        "original_title": "Neugeborenen-Gelbsucht (Kinder- und Jugendärzte im Netz)",
        "original_language": "de",
        "chunks": ["Ictericia del recién nacido (BVKJ, 2018). Tema: x."]}]})
    with pytest.raises(AssertionError):
        checks.check_title_in_a_language_she_reads({"sources": [{
            "title": "Sudden infant death (NHS)", "original_title": "Sudden infant death (NHS)",
            "original_language": "en", "chunks": ["x"]}]})


# --- the gap rule (2026-11-07) -----------------------------------------------------
#
# The same server run: recall@4 of group A fell from 0.97 to 0.86. A1, A5, A13
# and A37 lost their source to candidates that say again, often in another
# language, what data/ already says well about breastfeeding (141 data/
# sources mention it), complementary feeding (55) and safe sleep (40). On those
# three themes a candidate is worth only what data/ lacks:
#
#   1. A fragment of a candidate tagged with one of COVERED_TOPICS enters only
#      if its theme (what it says after «Tema:») is a gap: a sub-theme in GAPS,
#      which no fragment of data/ has as its theme. In a source tagged only
#      with those topics every fragment is on a covered theme; in a source that
#      also has another topic, the fragments whose theme is COVERED_THEME are.
#   2. A source left with fewer than two fragments goes (the batch's rule: two
#      to four fragments).
#   3. A gap stops being one when three candidates fill it: GAP_CAP sources at
#      most, first those of the two countries AdelIA serves, then those read in
#      Spanish, English or French.
#
# Applied on 2026-11-07 (docs/corpus/CANDIDATOS_2026_11_06.md, 16): 113 of the
# 455 sources went, every safe-sleep one among them.

COVERED_TOPICS = frozenset({
    "lactancia", "alimentacion_complementaria", "cuando_solidos", "senales_listo", "texturas",
    "alergenos", "muerte_subita_sueno_seguro", "colecho", "chupete",
})
COVERED_THEME = re.compile(
    r"lactancia|leche materna|leche de la madre|amamant|dar el pecho|\bal pecho\b|el pecho\b|"
    r"calostro|tomas?\b.{0,20}pecho|leche extra[ií]da|extraer (la )?leche|"
    r"extracci[oó]n (manual )?de (la )?leche|sacaleches|conserva\w* (y \w+ )?(de )?la leche|"
    r"congelar (la )?leche|"
    r"alimentaci[oó]n complementaria|s[oó]lidos|papillas?|pur[eé]s|texturas?|diversificaci|"
    r"primeros (alimentos|bocados)|\bblw\b|empezar (con|a comer)|introducir (los |otros )?alimentos|"
    r"alimentos complementarios|otros alimentos|"
    r"alimentaci[oó]n (de|entre|desde|a partir de) (los )?(4|6) |"
    r"muerte s[uú]bita|sueño seguro|colecho|compartir (la )?cama|chupete|boca arriba|"
    r"asfixia (durante|en) el sueño|dormir (seguro|boca)|superficie para dormir|"
    r"postura (para|al) dormir|cama propia|misma cama"
)
GAPS = {
    "problemas del pecho": r"grieta|mastitis|ingurgitaci|pez[oó]n|dolor (de pecho|al amamantar|en el "
                           r"pecho)|pechos? hinchados?|conductos? (de leche )?obstruidos?.{0,5}(y|o) "
                           r"mastitis",
    "agarre y posturas": r"agarre|posturas? (para dar el pecho|de lactancia)|colocar al beb[eé] al "
                         r"pecho",
    "crisis de lactancia": r"crisis (transitoria )?de (la )?lactancia|crisis de los 3 meses|baches? de "
                           r"lactancia|brotes? de crecimiento",
    "tetanalgesia": r"tetanalgesia|pecho durante",
    "colapso posnatal": r"colapso",
    "muerte súbita en la guardería": r"muerte s[uú]bita en la guarder",
    "lactancia del prematuro": r"(pecho|lactancia|leche|extraer|mamar).{0,60}(prematur|ingresad)|"
                               r"(prematur|ingresad).{0,60}(pecho|lactancia|leche|mamar)",
    "alérgenos pronto": r"cacahuete|man[ií]\b|al[eé]rgenos|alerg[eé]nicos|huevo|"
                        r"mantener\w* (el alimento |los al[eé]rgenos |el cacahuete )?en la dieta",
    "piel con piel": r"piel con piel",
    "contraindicaciones": r"contraindica",
    "monitores": r"monitor",
    "vitamina D": r"vitamina d",
}
GAP_CAP = 3


def _theme(chunk: str) -> str:
    m = re.search(r"Tema: (.*?)\. Hallazgo", chunk) or re.search(r"Tema: ([^.]*)\.", chunk)
    return (m.group(1) if m else "").lower()


def _gaps_of(chunk: str) -> list[str]:
    return [g for g, p in GAPS.items() if re.search(p, _theme(chunk))]


def _repeats_a_covered_theme(source: dict) -> list[int]:
    """The fragments of `source` the rule keeps out."""
    own = set(source.get("topics") or ()) - set(GENERIC)
    if not own & COVERED_TOPICS:
        return []
    pure = own <= COVERED_TOPICS
    return [i for i, c in enumerate(source["chunks"])
            if not _gaps_of(c) and (pure or COVERED_THEME.search(_theme(c)))]


def _batch_names() -> set[str]:
    return {path_of(d).name for d in DOMAINS}


@pytest.mark.parametrize("gap", sorted(GAPS))
def test_every_gap_is_a_theme_no_fragment_of_data_has(gap):
    files = [p for p in sorted(checks.DATA_DIR.glob(checks.BOOT_GLOB))
             if p.name not in _batch_names()]
    found = [s["title"] for p in files for s in checks.load(p)["sources"]
             for c in s["chunks"] if re.search(GAPS[gap], _theme(c))]
    assert not found, f"data/ already covers «{gap}»: {found[:3]}"


@pytest.mark.parametrize("domain", NAMES)
def test_a_candidate_on_a_covered_theme_brings_only_what_data_lacks(domain):
    for s in _data(domain)["sources"]:
        out = _repeats_a_covered_theme(s)
        assert not out, f"{s['title'][:50]}: fragments {out} repeat a theme data/ covers"


def test_no_gap_is_filled_by_more_than_three_candidates():
    filled: dict[str, list[str]] = {g: [] for g in GAPS}
    for d in NAMES:
        for s in _data(d)["sources"]:
            if not set(s.get("topics") or ()) & COVERED_TOPICS:
                continue
            for g in {g for c in s["chunks"] for g in _gaps_of(c)}:
                filled[g].append(s["title"])
    over = {g: t for g, t in filled.items() if len(t) > GAP_CAP}
    assert not over, over


@pytest.mark.parametrize(("topics", "themes", "kept"), [
    (["lactancia"], ["duración de la lactancia", "beneficios para la madre"], False),
    (["lactancia"], ["mastitis", "grietas en el pezón"], True),
    (["muerte_subita_sueno_seguro", "chupete"], ["postura para dormir", "cuándo consultar"], False),
    (["lactancia", "extraccion_conservacion_leche"], ["duración de la lactancia materna",
                                                      "cómo congelar la leche extraída"], False),
    (["fiebre"], ["lactancia y fiebre", "cuándo consultar"], True),
])
def test_the_gap_rule_bites(topics, themes, kept):
    src = {"topics": topics, "chunks": [f"X (Y, 2024). Tema: {t}. Hallazgo: z." for t in themes]}
    assert (not _repeats_a_covered_theme(src)) is kept
