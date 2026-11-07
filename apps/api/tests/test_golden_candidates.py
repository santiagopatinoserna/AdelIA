"""scripts/golden_candidates.py: a candidate corpus measured before it reaches data/.

Several agents are gathering hundreds of new sources in many languages,
summarised in Spanish in the shape of enrichment/data/evidence_*.json. Before
any of them moves into data/ (and so into production at the next boot), the
gate loads them into its scratch copy of the production corpus and measures
the golden set without a model, with and without them
(docs/GOLDEN_GATE_DESPLIEGUE.md). These tests pin that the files are loaded
only into a scratch database, that a bad file stops the load before anything
is written, that boot never reads them, and how the two runs are compared.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest

from adelia.config import settings
from tests.pg_gate import PG_AVAILABLE

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "golden_candidates.py"
_spec = importlib.util.spec_from_file_location("golden_candidates", _PATH)
gc = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gc
_spec.loader.exec_module(gc)

API_DIR = Path(__file__).resolve().parents[1]


def _source(title: str, **extra) -> dict:
    return {
        "source_type": "guideline", "title": title, "organization": "AEP",
        "publication_year": 2025, "url": "https://example.org/x", "language": "es",
        "specialties": ["pediatrics"], "chunks": [f"{title}: primer fragmento."], **extra,
    }


def _file(tmp_path: Path, name: str, sources: list[dict]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"sources": sources}, ensure_ascii=False), encoding="utf-8")
    return path


# --- which files ------------------------------------------------------------------


def test_the_glob_is_read_from_the_repo_root_or_from_apps_api(tmp_path):
    cand = tmp_path / "adelia" / "enrichment" / "candidates"
    cand.mkdir(parents=True)
    for name in ("evidence_b.json", "evidence_a.json"):
        _file(cand, name, [_source(name)])
    want = [cand / "evidence_a.json", cand / "evidence_b.json"]
    assert gc.resolve("apps/api/adelia/enrichment/candidates/*.json", api_dir=tmp_path) == want
    assert gc.resolve("adelia/enrichment/candidates/*.json", api_dir=tmp_path) == want
    assert gc.resolve(str(cand / "*.json"), api_dir=tmp_path) == want


def test_a_glob_that_matches_nothing_is_an_error_not_an_empty_load(tmp_path):
    with pytest.raises(gc.CandidateError, match="ningún fichero"):
        gc.resolve("apps/api/adelia/enrichment/candidates/*.json", api_dir=tmp_path)


def test_a_production_corpus_file_is_not_a_candidate():
    """data/ is what boot loads: it is already in the corpus being measured."""
    with pytest.raises(gc.CandidateError, match="data/"):
        gc.resolve("apps/api/adelia/enrichment/data/evidence_*.json", api_dir=API_DIR)


# 2026-11-07: the second server run of the 2026-11-06 batch was still NOT FIT,
# with one A and one B broken by two or three files out of twelve. A domain that
# keeps failing must not hold the others back, so a subset is measured on its
# own: files separated by commas, each a path or a glob.


def _lote(tmp_path, *names):
    cand = tmp_path / "adelia" / "enrichment" / "candidates" / "lote"
    cand.mkdir(parents=True)
    for name in names:
        _file(cand, name, [_source(name)])
    return cand


def test_a_comma_separated_list_names_exactly_those_files(tmp_path):
    cand = _lote(tmp_path, "seguridad.json", "neonatal.json", "digestivo_piel.json")
    got = gc.resolve("apps/api/adelia/enrichment/candidates/lote/seguridad.json, "
                     "adelia/enrichment/candidates/lote/neonatal.json", api_dir=tmp_path)
    assert got == [cand / "neonatal.json", cand / "seguridad.json"]


def test_a_list_may_mix_globs_and_files_and_names_each_file_once(tmp_path):
    cand = _lote(tmp_path, "salud.json", "seguridad.json", "neonatal.json")
    got = gc.resolve("adelia/enrichment/candidates/lote/s*.json,"
                     "adelia/enrichment/candidates/lote/seguridad.json,", api_dir=tmp_path)
    assert got == [cand / "salud.json", cand / "seguridad.json"]


def test_a_listed_file_that_is_not_there_is_an_error_naming_it(tmp_path):
    """A typo must not measure eleven files as if they were twelve."""
    _lote(tmp_path, "seguridad.json")
    with pytest.raises(gc.CandidateError, match="seguridda.json"):
        gc.resolve("adelia/enrichment/candidates/lote/seguridad.json,"
                   "adelia/enrichment/candidates/lote/seguridda.json", api_dir=tmp_path)


def test_a_list_still_refuses_a_production_corpus_file(tmp_path):
    cand = _lote(tmp_path, "seguridad.json")
    with pytest.raises(gc.CandidateError, match="ya está en enrichment/data/"):
        gc.resolve(f"{cand / 'seguridad.json'},"
                   f"{API_DIR / 'adelia' / 'enrichment' / 'data' / 'evidence_seguridad.json'}",
                   api_dir=API_DIR)


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"fuentes": []}, "sources"),
        ({"sources": []}, "sources"),
        ({"sources": [{"title": "Sin fragmentos", "source_type": "guideline", "chunks": []}]},
         "chunks"),
        ({"sources": [{**_source("Experiencia"), "tier": "experience"}]}, "experience"),
        ({"sources": [{**_source("Tipo raro"), "source_type": "blog"}]}, "source_type"),
    ],
)
def test_a_malformed_file_is_refused_with_its_reason(tmp_path, payload, why):
    path = tmp_path / "evidence_x.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gc.CandidateError, match=why):
        gc.validate(path)


def test_only_a_scratch_copy_may_receive_candidates():
    for name in ("adelia", "adelia_test", "golden_gate_adelia"):
        with pytest.raises(gc.CandidateError, match="_golden_gate"):
            gc.refuse_unless_scratch(name)
    gc.refuse_unless_scratch("adelia_golden_gate")


async def test_a_bad_file_stops_the_load_before_anything_is_written(tmp_path, monkeypatch):
    good = _file(tmp_path, "evidence_a.json", [_source("Buena")])
    bad = tmp_path / "evidence_b.json"
    bad.write_text("{", encoding="utf-8")
    loaded: list = []

    async def _load_sources(sources, origin, **kwargs):
        loaded.append(origin)
        return len(sources), len(sources)

    monkeypatch.setattr(gc.evidence_loader, "load_sources", _load_sources)
    with pytest.raises(gc.CandidateError):
        await gc.load_candidates([good, bad], db_name="adelia_golden_gate")
    assert loaded == []


async def test_the_live_database_is_refused_before_any_file_is_read(tmp_path, monkeypatch):
    async def _never(*args, **kwargs):
        raise AssertionError("loaded into the live database")

    monkeypatch.setattr(gc.evidence_loader, "load_sources", _never)
    with pytest.raises(gc.CandidateError, match="_golden_gate"):
        await gc.load_candidates([_file(tmp_path, "evidence_a.json", [_source("X")])],
                                 db_name="adelia")


# --- boot never loads them --------------------------------------------------------


async def test_boot_never_loads_a_candidate_file(monkeypatch):
    """main.load_startup_corpora reads enrichment/data/evidence_*.json only."""
    from adelia import main
    from adelia.enrichment import evidence_loader, experience_loader

    seen: list[Path] = []

    async def _record(path):
        seen.append(Path(path))
        return 0, 0

    async def _nothing(*args, **kwargs):
        return 0, 0

    monkeypatch.setattr(settings, "mistral_api_key", "placeholder-not-a-key")
    monkeypatch.setattr(evidence_loader, "load_evidence_file", _record)
    monkeypatch.setattr(evidence_loader, "load_seed_if_empty", _nothing)
    monkeypatch.setattr(experience_loader, "load_experience_dir", _nothing)
    await main.load_startup_corpora()
    assert seen, "boot loads the data/ files"
    data_dir = (API_DIR / "adelia" / "enrichment" / "data").resolve()
    assert all(p.resolve().parent == data_dir for p in seen), seen
    assert gc.CANDIDATES_DIR.resolve() != data_dir


# --- the load, into a real scratch database ------------------------------------------


@pytest.mark.skipif(not PG_AVAILABLE, reason="needs Postgres running")
@pytest.mark.timeout(60)
async def test_candidates_load_into_the_scratch_copy_and_nowhere_else(tmp_path, monkeypatch):
    """A throwaway `*_golden_gate` database with the evidence tables: the
    candidate sources land there with their chunks, a title the corpus already
    has is skipped, a second load adds nothing, and the dev database the
    suite runs on never sees them."""
    import asyncpg
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from adelia.db import AsyncSessionLocal, Base
    from adelia.enrichment import evidence_loader
    from adelia.models import EvidenceChunk, EvidenceSource

    scratch = f"adelia_cand_{uuid.uuid4().hex[:8]}_golden_gate"
    dsn = dict(host=settings.postgres_host, port=settings.postgres_port,
               user=settings.postgres_user, password=settings.postgres_password)
    admin = await asyncpg.connect(database=settings.postgres_db, **dsn)
    await admin.execute(f'CREATE DATABASE "{scratch}"')
    engine = create_async_engine(settings.database_url.rsplit("/", 1)[0] + f"/{scratch}")
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.run_sync(lambda c: Base.metadata.create_all(
                c, tables=[EvidenceSource.__table__, EvidenceChunk.__table__]))
        scratch_sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with scratch_sessions() as session:
            session.add(EvidenceSource(source_type="guideline", title="Ya en producción",
                                       specialties=["pediatrics"], language="es"))
            await session.commit()

        async def _embed(texts):
            return [[0.01] * 1024 for _ in texts]

        monkeypatch.setattr(evidence_loader, "AsyncSessionLocal", scratch_sessions)
        monkeypatch.setattr(evidence_loader, "embed_texts", _embed)
        monkeypatch.setattr(evidence_loader, "SOURCE_PACING_S", 0)
        tag = uuid.uuid4().hex[:8]
        path = _file(tmp_path, "evidence_cand.json", [
            _source(f"Candidata {tag} uno"),
            _source(f"Candidata {tag} dos", chunks=["a", "b"]),
            _source("Ya en producción"),
        ])

        rows = await gc.load_candidates([path], db_name=scratch)
        assert [(r.path.name, r.sources, r.added, r.chunks) for r in rows] == [
            ("evidence_cand.json", 3, 2, 3)
        ]
        # No name given: the guard asks the connection itself which database it is.
        assert (await gc.load_candidates([path]))[0].added == 0

        async with scratch_sessions() as session:
            titles = set((await session.scalars(select(EvidenceSource.title))).all())
            n_chunks = await session.scalar(select(func.count()).select_from(EvidenceChunk))
        assert {f"Candidata {tag} uno", f"Candidata {tag} dos"} <= titles and n_chunks == 3
        async with AsyncSessionLocal() as session:
            leaked = await session.scalar(
                select(func.count()).select_from(EvidenceSource)
                .where(EvidenceSource.title.like(f"Candidata {tag}%"))
            )
        assert leaked == 0
    finally:
        await engine.dispose()
        await admin.execute(f'DROP DATABASE IF EXISTS "{scratch}" WITH (FORCE)')
        await admin.close()


# --- with and without -----------------------------------------------------------------


def _report(*, recall=1.0, results=None, mode="no_model", reached=None) -> dict:
    return {
        "mode": mode, "recall_at_4": recall, "refusal_rate": 1.0, "red_flag_rate": 1.0,
        "skipped_reason": None, "results": results or {}, "b_reached_model": reached or [],
    }


_A_OK = {"group": "A", "locale": "es", "kind": "", "passed": True}
_A_KO = {**_A_OK, "passed": False}
_B_OK = {"group": "B", "locale": "es", "kind": "adjacent", "passed": True}
_B_MODEL = {**_B_OK, "passed": None, "reached_model": True}


def test_a_b_that_reaches_the_model_only_with_the_candidates_is_a_broken_refusal():
    without = _report(results={"A1": _A_OK, "B1": _B_OK, "B8": _B_MODEL}, reached=["B8"])
    with_ = _report(results={"A1": _A_OK, "B1": _B_MODEL, "B8": _B_MODEL}, reached=["B1", "B8"])
    text, status = gc.compare(without, with_)
    assert status == 1
    assert "B1" in text and "rechazo" in text
    assert "B8" not in text.split("B que pasan a llegar al modelo")[1].splitlines()[0]


def test_a_gained_and_lost_and_the_recall_on_both_sides():
    without = _report(recall=0.8, results={"A1": _A_KO, "A2": _A_OK})
    with_ = _report(recall=0.9, results={"A1": _A_OK, "A2": _A_OK})
    text, status = gc.compare(without, with_)
    assert status == 0
    assert "0.80" in text and "0.90" in text
    assert "A que pasan con los candidatos: A1" in text


def test_a_recall_under_the_bar_with_the_candidates_fails_the_evaluation():
    without = _report(recall=0.9, results={"A1": _A_OK, "A2": _A_OK})
    with_ = _report(recall=0.7, results={"A1": _A_KO, "A2": _A_OK})
    text, status = gc.compare(without, with_)
    assert status == 1 and "A que dejan de pasar con los candidatos: A1" in text


def test_the_preview_of_the_candidate_questions_is_compared_too():
    run = _report(results={"A1": _A_OK})
    before = [{"id": "A20", "group": "A", "passed": False},
              {"id": "B19", "group": "B", "passed": True}]
    after = [{"id": "A20", "group": "A", "passed": True},
             {"id": "B19", "group": "B", "passed": False}]
    text, status = gc.compare(run, run, before, after)
    assert status == 1
    assert "A20" in text.split("    pasan con los candidatos")[1].splitlines()[0]
    assert "B19" in text


@pytest.mark.parametrize(
    "broken",
    [
        {"skipped_reason": "sin corpus"},
        {"mode": "model"},
    ],
)
def test_a_run_that_did_not_measure_or_used_the_model_cannot_be_compared(broken):
    text, status = gc.compare(_report(), {**_report(), **broken})
    assert status == 2 and text


def test_main_reads_the_files_and_returns_the_status(tmp_path, capsys):
    a, b = tmp_path / "sin.json", tmp_path / "con.json"
    a.write_text(json.dumps(_report(results={"B1": _B_OK})), encoding="utf-8")
    b.write_text(json.dumps(_report(results={"B1": _B_MODEL}, reached=["B1"])), encoding="utf-8")
    assert gc.main(["compare", "--without", str(a), "--with", str(b)]) == 1
    assert "B1" in capsys.readouterr().out
    assert gc.main(["compare", "--without", str(a), "--with", str(tmp_path / "no.json")]) == 2


def test_the_cli_load_refuses_the_live_database(tmp_path, monkeypatch, capsys):
    _file(tmp_path, "evidence_a.json", [_source("X")])
    monkeypatch.setattr(settings, "postgres_db", "adelia")
    assert gc.main(["load", str(tmp_path / "*.json")]) == 2
    assert "_golden_gate" in capsys.readouterr().out


def test_a_load_that_cannot_embed_says_why_and_exits_two(tmp_path, monkeypatch, capsys):
    """No embedding key, or Mistral down: a sentence in the gate's log, not a traceback."""
    _file(tmp_path, "evidence_a.json", [_source("X")])

    async def _down(sources, origin, **kwargs):
        raise RuntimeError("MISTRAL_API_KEY not set")

    async def _scratch() -> str:
        return "adelia_golden_gate"

    monkeypatch.setattr(settings, "postgres_db", "adelia_golden_gate")
    monkeypatch.setattr(gc, "_connected_database", _scratch)
    monkeypatch.setattr(gc.evidence_loader, "load_sources", _down)
    assert gc.main(["load", str(tmp_path / "*.json")]) == 2
    out = capsys.readouterr().out
    assert "no se pudieron cargar" in out and "MISTRAL_API_KEY not set" in out


async def test_with_no_name_the_guard_asks_the_connection_which_database_it_is(
    tmp_path, monkeypatch
):
    """settings may say one thing and the session factory point elsewhere: the
    database that would receive the rows is the one checked."""
    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalar(self, statement):
            return "adelia"

    async def _never(*args, **kwargs):
        raise AssertionError("loaded into the live database")

    monkeypatch.setattr(settings, "postgres_db", "adelia_golden_gate")
    monkeypatch.setattr(gc.evidence_loader, "AsyncSessionLocal", lambda: _Session())
    monkeypatch.setattr(gc.evidence_loader, "load_sources", _never)
    with pytest.raises(gc.CandidateError, match="_golden_gate"):
        await gc.load_candidates([_file(tmp_path, "evidence_a.json", [_source("X")])])


# --- explain: the same questions, without and with the candidates (2026-11-07) ----


def _explained(qid: str, group: str, nearest, cards=(), origins=None, expect=None) -> dict:
    return {"id": qid, "group": group, "question": f"pregunta {qid}", "expect_source": expect,
            "passed": True, "guard": None,
            "cards": [{"title": t, "distance": d} for t, d in cards],
            "nearest": [list(n) for n in nearest], "origins": origins or {}}


def test_explain_puts_both_runs_side_by_side_and_names_the_newcomers():
    without = [_explained("A5", "A", [("Sueño seguro (AEP)", 0.10), ("SMSL (AEP)", 0.11)],
                          cards=[("Sueño seguro (AEP)", 0.10)], expect="sueño",
                          origins={"Sueño seguro (AEP)": "data/evidence_respiratorio_sueno.json"})]
    with_ = [_explained("A5", "A", [("Krybbedød (Helsenorge)", 0.08), ("Sueño seguro (AEP)", 0.10)],
                        cards=[("Krybbedød (Helsenorge)", 0.08)], expect="sueño",
                        origins={"Krybbedød (Helsenorge)": "candidato respiratorio_sueno.json",
                                 "Sueño seguro (AEP)": "data/evidence_respiratorio_sueno.json"})]
    text = gc.explain(without, with_)
    assert "[A5]" in text and "sueño" in text
    sin, con = text.split("con candidatos")[0], text.split("con candidatos")[1]
    assert "Sueño seguro (AEP)" in sin and "0.1000" in sin
    new = next(x for x in con.splitlines() if "Krybbedød" in x)
    assert "nueva" in new and "candidato respiratorio_sueno.json" in new and "bajo el corte" in new
    assert "sale con los candidatos: SMSL (AEP)" in text


def test_explain_of_a_b_names_the_cards_that_fell_under_the_cut():
    without = [_explained("B6", "B", [("Alergia a la leche de vaca (AEP)", 0.1901)])]
    with_ = [_explained("B6", "B", [("Food allergies (NHS)", 0.185)],
                        cards=[("Food allergies (NHS)", 0.185)],
                        origins={"Food allergies (NHS)": "candidato alimentacion_bebes.json"})]
    text = gc.explain(without, with_)
    assert "B6" in text and "tarjetas bajo el corte: ninguna sin; 1 con" in text


def test_explain_with_one_run_only_prints_that_run():
    text = gc.explain([_explained("A16", "A", [("Pas à pas (SPF)", 0.18)], expect="Pas à pas")],
                      None)
    assert "[A16]" in text and "con candidatos" not in text


def test_the_cli_explain_reads_the_previews_and_never_fails_the_gate(tmp_path, capsys):
    a = tmp_path / "sin.json"
    a.write_text(json.dumps([_explained("A1", "A", [("X", 0.1)])]), encoding="utf-8")
    assert gc.main(["explain", "--without", str(a)]) == 0
    assert "[A1]" in capsys.readouterr().out
    assert gc.main(["explain", "--without", str(tmp_path / "no.json")]) == 2


def _block(name: str, top, cards=(), note: str = "") -> dict:
    return {"name": name, "text": f"texto de {name}", "cut": 0.19, "note": note,
            "top": [list(t) for t in top], "cards": list(cards)}


def test_explain_puts_each_search_side_by_side_and_names_its_newcomers():
    """A21, 2026-11-07: the merged list showed the tear-duct sources on top, the
    gate's own search had the crying ones first. Each search is its own block."""
    lagrimeo, llanto = ("Lagrimeo en el lactante (AEPap)", 0.1816), ("Llanto (Kind en Gezin)", 0.1797)
    bloqueado = ("Conducto lagrimal bloqueado (AAP)", 0.1092)
    without = [_explained("A21", "A", [bloqueado, lagrimeo], expect="lagrimal|Lagrimeo")]
    without[0]["queries"] = [_block("gate", [("Qué hacer cuando llora mucho", 0.1764), lagrimeo],
                                    cards=["Qué hacer cuando llora mucho", lagrimeo[0]]),
                             _block("léxico de madre", [bloqueado])]
    with_ = [_explained("A21", "A", [bloqueado, llanto, lagrimeo], expect="lagrimal|Lagrimeo",
                        origins={llanto[0]: "candidato digestivo_piel.json"})]
    with_[0]["queries"] = [_block("gate", [llanto, ("Qué hacer cuando llora mucho", 0.1764)],
                                  cards=[llanto[0], "Qué hacer cuando llora mucho"]),
                           _block("léxico de madre", [bloqueado])]
    text = gc.explain(without, with_)
    gate = text.split("consulta gate")[1].split("consulta léxico de madre")[0]
    new = next(x for x in gate.split("con candidatos")[1].splitlines() if "Llanto" in x)
    assert "nueva" in new and "bajo el corte" in new and "candidato digestivo_piel.json" in new
    assert f"sale con los candidatos: {lagrimeo[0]}" in gate
    lexicon = text.split("consulta léxico de madre")[1]
    assert "sale con los candidatos: ninguna" in lexicon


def test_explain_of_one_run_prints_its_searches_too():
    v = _explained("A21", "A", [("Lagrimeo en el lactante (AEPap)", 0.1816)], expect="Lagrimeo")
    v["queries"] = [_block("gate", [("Llanto (Kind en Gezin)", 0.1797)],
                           cards=["Llanto (Kind en Gezin)"])]
    text = gc.explain([v], None)
    assert "consulta gate" in text and "0.1797 bajo el corte" in text
    assert "con candidatos" not in text
