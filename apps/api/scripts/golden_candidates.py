"""A candidate corpus, measured by the golden set without a model, before it reaches data/.

    # inside the api-golden container, on the scratch copy (golden_gate.sh does this)
    python scripts/golden_candidates.py load "apps/api/adelia/enrichment/candidates/*.json"
    python scripts/golden_candidates.py compare --without golden_report.sin_candidatos.json \\
        --with golden_report.con_candidatos.json \\
        --preview-without golden_preview.sin_candidatos.json \\
        --preview-with golden_preview.con_candidatos.json
    python scripts/golden_candidates.py explain --without golden_explain.sin_candidatos.json \\
        --with golden_explain.con_candidatos.json

Why. On 2026-11-06 several agents started gathering hundreds of new sources in
many languages, summarised in Spanish in the shape of
enrichment/data/evidence_*.json. A file in data/ is in production at the next
boot (main.load_startup_corpora), and the corpus grows by measuring, not by
counting (docs/HANDOFF_CLAUDE_CODE.md 1): before a file moves there we need to
know whether recall@4 of group A goes up and whether any refusal of group B
breaks. With GOLDEN_CANDIDATE_GLOB the deploy gate measures its scratch copy of
the production corpus twice, without a model (no Anthropic call, only
embeddings): as it is, and with these files loaded on top
(docs/GOLDEN_GATE_DESPLIEGUE.md).

`load` writes only into a database whose name ends in `_golden_gate`, the
scratch copy prod-golden-gate.sh makes and drops; every file is validated
before the first row is written. It goes through the boot loader's own
`load_sources` (same embedding, same idempotency by title), not through
`load_evidence_file`, so a candidate that repeats a production title is
skipped without touching that source's metadata: the "with" run measures
production plus the new sources, nothing else. Boot never reads this
directory.

`compare` reads the two gate reports (and, when given, the two previews of
the CANDIDATES questions) and prints what moved. Exit status 0: no group B
question got worse and recall@4 with the candidates still clears its bar; 1:
one did, or it does not; 2: a run did not measure, or was not the run without
a model, so there is nothing to compare.

`explain` (2026-11-07) reads the --explain previews of the questions the
operator named (golden_gate.sh --explain IDS) and prints them side by side:
each nearest source with its distance, under the cut or not, expected or not,
new with the candidates or not, and its file. The first server run of the
2026-11-06 candidates said which questions broke, not which sources broke
them; this is the run that says it. It always exits 0: a diagnostic.

Without a model a group B question has three outcomes: refused by code (red
flag, age scope, nothing under the cut), "reaches the model" (cards under
the cut, a refusal only the model can write) or answered by code (a bug).
Moving from the first to either of the others with the candidates is a
broken refusal until the full pass (GOLDEN_WITH_MODEL=1) says otherwise.
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from adelia.clinical.golden import RECALL_AT_4_MIN, source_matches
from adelia.config import settings
from adelia.enrichment import evidence_loader

API_DIR = Path(__file__).resolve().parents[1]
#: Where the agents put candidate files. Nothing at boot reads it.
CANDIDATES_DIR = API_DIR / "adelia" / "enrichment" / "candidates"
_DATA_DIR = API_DIR / "adelia" / "enrichment" / "data"
SCRATCH_SUFFIX = "_golden_gate"
#: The source types evidence_sources accepts, minus the experience tier's.
_SOURCE_TYPES = {"guideline", "paper", "protocol", "reference"}
#: The operator writes the glob from the repo root; the container runs in apps/api.
_REPO_PREFIXES = ("./apps/api/", "apps/api/")


class CandidateError(Exception):
    """The candidates cannot be loaded or compared (exit status 2)."""


# --- which files ------------------------------------------------------------------


def resolve(pattern: str, *, api_dir: Path = API_DIR) -> list[Path]:
    """The files `pattern` names, sorted, from the repo root or from apps/api."""
    p = pattern.strip()
    if not p:
        raise CandidateError("GOLDEN_CANDIDATE_GLOB está vacío")
    for prefix in _REPO_PREFIXES:
        if p.startswith(prefix):
            p = p[len(prefix):]
            break
    full = p if os.path.isabs(p) else str(api_dir / p)
    files = sorted(Path(f) for f in glob.glob(full) if Path(f).is_file())
    if not files:
        raise CandidateError(f"ningún fichero coincide con {pattern!r} (buscado en {full})")
    data_dir = (api_dir / "adelia" / "enrichment" / "data").resolve()
    in_data = [f.name for f in files if f.resolve().parent == data_dir]
    if in_data:
        raise CandidateError(
            f"{', '.join(in_data)} ya está en enrichment/data/: lo carga el arranque y ya está "
            "en el corpus que se mide; un candidato vive fuera de data/"
        )
    return files


def validate(path: Path) -> dict:
    """The file's payload, or the reason it cannot be a candidate."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CandidateError(f"{path.name}: no se puede leer como JSON ({exc})") from exc
    sources = data.get("sources") if isinstance(data, dict) else None
    if not isinstance(sources, list) or not sources:
        raise CandidateError(f"{path.name}: falta la lista `sources` o está vacía")
    for n, src in enumerate(sources):
        where = f"{path.name}, fuente {n}"
        if not isinstance(src, dict) or not str(src.get("title") or "").strip():
            raise CandidateError(f"{where}: sin `title`")
        if src.get("tier", "evidence") != "evidence":
            raise CandidateError(
                f"{where}: tier {src.get('tier')!r}; la experience de otras madres tiene su "
                "propio cargador y no se mide con el golden clínico"
            )
        if src.get("source_type") not in _SOURCE_TYPES:
            raise CandidateError(f"{where}: source_type {src.get('source_type')!r} no admitido")
        chunks = src.get("chunks")
        if not isinstance(chunks, list) or not chunks or not all(
            isinstance(c, str) and c.strip() for c in chunks
        ):
            raise CandidateError(f"{where}: `chunks` tiene que ser una lista de textos no vacía")
    return data


def refuse_unless_scratch(db_name: str) -> None:
    """Candidates go into the gate's scratch copy only, never the live database."""
    if not db_name.endswith(SCRATCH_SUFFIX):
        raise CandidateError(
            f"POSTGRES_DB={db_name} no es una copia efímera (*{SCRATCH_SUFFIX}); los candidatos "
            "nunca se cargan en la base viva"
        )


# --- the load -----------------------------------------------------------------------


@dataclass
class Loaded:
    path: Path
    sources: int
    added: int
    chunks: int
    #: Sources without the "pediatrics" tag: retrieval for a baby never sees them.
    untagged: int = 0


async def _connected_database() -> str:
    """The database the loader's sessions actually reach, asked of the connection."""
    from sqlalchemy import text

    async with evidence_loader.AsyncSessionLocal() as session:
        return str(await session.scalar(text("SELECT current_database()")))


async def load_candidates(paths: list[Path], *, db_name: str | None = None) -> list[Loaded]:
    """Load every file into the scratch copy, after validating all of them.

    `db_name` is for tests that check the guard alone; without it the guard
    reads the name from the connection the rows would go through, not from
    settings, so no misconfigured factory can point the load at the live
    database."""
    refuse_unless_scratch(db_name if db_name is not None else await _connected_database())
    payloads = [validate(path) for path in paths]
    out: list[Loaded] = []
    for path, data in zip(paths, payloads, strict=True):
        sources = data["sources"]
        added, chunks = await evidence_loader.load_sources(sources, path.name)
        untagged = sum(1 for s in sources if "pediatrics" not in (s.get("specialties") or []))
        out.append(Loaded(path, len(sources), added, chunks, untagged))
    return out


def _render_load(rows: list[Loaded]) -> str:
    lines = [f"candidatos: {len(rows)} fichero(s)"]
    for r in rows:
        skipped = r.sources - r.added
        line = f"  {r.path.name}: +{r.added} fuentes, +{r.chunks} fragmentos"
        if skipped:
            line += f"; {skipped} ya estaban (mismo título), sin tocar"
        if r.untagged:
            line += f"; {r.untagged} sin «pediatrics»: la recuperación no las ve"
        lines.append(line)
    total = sum(r.added for r in rows), sum(r.chunks for r in rows)
    lines.append(f"  total: +{total[0]} fuentes, +{total[1]} fragmentos")
    return "\n".join(lines)


# --- with and without ---------------------------------------------------------------


def _b_state(r: dict) -> str:
    if r.get("reached_model"):
        return "llega al modelo"
    return "rechaza" if r.get("passed") else "responde"


def _ids(items) -> str:
    return ", ".join(items) or "ninguna"


def _check_run(report: dict, label: str) -> None:
    if report.get("skipped_reason"):
        raise CandidateError(f"la pasada {label} no midió A y B: {report['skipped_reason']}")
    if (report.get("mode") or "model") != "no_model":
        raise CandidateError(f"la pasada {label} no es la del golden sin modelo")


def compare(
    without: dict,
    with_: dict,
    preview_without: list[dict] | None = None,
    preview_with: list[dict] | None = None,
) -> tuple[str, int]:
    """(text, exit status) for the gate run without and with the candidates."""
    try:
        _check_run(without, "sin candidatos")
        _check_run(with_, "con candidatos")
    except CandidateError as exc:
        return f"candidatos: NO SE PUEDE COMPARAR: {exc}", 2

    before, after = without.get("results") or {}, with_.get("results") or {}
    a_ids = [q for q in before if before[q]["group"] == "A" and q in after]
    a_gained = [q for q in a_ids if not before[q]["passed"] and after[q]["passed"]]
    a_lost = [q for q in a_ids if before[q]["passed"] and not after[q]["passed"]]
    b_ids = [q for q in before if before[q]["group"] == "B" and q in after]
    b_to_model = [q for q in b_ids
                  if _b_state(before[q]) == "rechaza" and _b_state(after[q]) == "llega al modelo"]
    b_answered = [q for q in b_ids
                  if _b_state(before[q]) != "responde" and _b_state(after[q]) == "responde"]
    b_back = [q for q in b_ids
              if _b_state(before[q]) == "llega al modelo" and _b_state(after[q]) == "rechaza"]
    recall_with = with_.get("recall_at_4")

    def _rate(value) -> str:
        return "no medido" if value is None else f"{value:.2f}"

    lines = [
        "Golden sin modelo, sin y con candidatos",
        f"  grupo A, recall@4:           {_rate(without.get('recall_at_4'))} sin, "
        f"{_rate(recall_with)} con (umbral {RECALL_AT_4_MIN})",
        f"  A que pasan con los candidatos: {_ids(a_gained)}",
        f"  A que dejan de pasar con los candidatos: {_ids(a_lost)}",
        f"  grupo B que llega al modelo: {_ids(without.get('b_reached_model') or [])} sin; "
        f"{_ids(with_.get('b_reached_model') or [])} con",
        f"  B que pasan a llegar al modelo con los candidatos: {_ids(b_to_model)} "
        "(un rechazo que el código hacía y ahora queda en manos del modelo)",
        f"  B que el código deja de rechazar: {_ids(b_answered)}",
        f"  B que vuelven a rechazarse por código: {_ids(b_back)}",
        f"  grupo C, banderas rojas:     {_rate(without.get('red_flag_rate'))} sin, "
        f"{_rate(with_.get('red_flag_rate'))} con",
    ]
    status = 1 if (b_to_model or b_answered) else 0
    if recall_with is not None and recall_with < RECALL_AT_4_MIN:
        status = 1

    if preview_without is not None and preview_with is not None:
        p_before = {v["id"]: v for v in preview_without}
        p_after = {v["id"]: v for v in preview_with}
        common = [i for i in p_before if i in p_after]
        gained = [i for i in common if not p_before[i]["passed"] and p_after[i]["passed"]]
        lost = [i for i in common if p_before[i]["passed"] and not p_after[i]["passed"]]
        b_lost = [i for i in lost if p_before[i].get("group") == "B"]
        lines += [
            f"  previsualización de CANDIDATES: {sum(v['passed'] for v in p_before.values())} de "
            f"{len(p_before)} pasan sin, {sum(v['passed'] for v in p_after.values())} de "
            f"{len(p_after)} con",
            f"    pasan con los candidatos: {_ids(gained)}",
            f"    dejan de pasar con los candidatos: {_ids(lost)}",
        ]
        if b_lost:
            status = 1
    elif preview_without is not None or preview_with is not None:
        lines.append("  previsualización de CANDIDATES: no medida en una de las dos pasadas")

    lines.append(
        "  candidatos: APTOS para medirse con modelo y pasar a data/" if status == 0 else
        "  candidatos: NO APTOS (un rechazo de B se rompe o recall@4 no llega al umbral)"
    )
    return "\n".join(lines), status


# --- explain: named questions, source by source --------------------------------------

#: The gate reads the top four cards (golden.TOP_K): a source pushed below
#: them is a source lost.
_TOP = 4


def _explain_block(v: dict, *, before: dict | None) -> list[str]:
    cut = {c.get("title") for c in v.get("cards") or []}
    origins = v.get("origins") or {}
    known = {n[0] for n in (before or {}).get("nearest") or []}
    rows = []
    for title, distance in v.get("nearest") or []:
        marks = ["bajo el corte" if title in cut else "fuera del corte"]
        if v.get("group") == "A" and source_matches(v.get("expect_source") or "", title):
            marks.append("esperada")
        if before is not None and title not in known:
            marks.append("nueva")
        where = origins.get(title, "sin fichero (crawler u otra carga)")
        rows.append(f"    {distance:.4f} {', '.join(marks)}: {title[:90]} [{where}]")
    if v.get("guard"):
        rows.append(f"    el guard la para ({v['guard']}), sin búsqueda")
    return rows or ["    (ninguna fuente)"]


def explain(without: list[dict], with_: list[dict] | None) -> str:
    """Each named question's nearest sources, without and (if given) with the candidates."""
    after = {v["id"]: v for v in with_ or []}
    lines = ["Explicación sin modelo: fuentes más cercanas, una por fuente, con su fichero"]
    for v in without:
        w = after.get(v["id"])
        head = f"\n[{v['id']}] ({v.get('group')}) {v.get('question', '')}"
        if v.get("group") == "A":
            head += f"\n  espera: {v.get('expect_source')}"
        lines.append(head)
        n_sin = len(v.get("cards") or [])
        if w is None:
            lines.append(f"  tarjetas bajo el corte: {n_sin or 'ninguna'}")
            lines += ["  sin candidatos", *_explain_block(v, before=None)]
            continue
        n_con = len(w.get("cards") or [])
        lines.append(f"  tarjetas bajo el corte: {n_sin or 'ninguna'} sin; {n_con or 'ninguna'} con")
        lines += ["  sin candidatos", *_explain_block(v, before=None)]
        lines += ["  con candidatos", *_explain_block(w, before=v)]
        top_after = {n[0] for n in (w.get("nearest") or [])[:_TOP]}
        gone = [n[0] for n in (v.get("nearest") or [])[:_TOP] if n[0] not in top_after]
        lines.append(f"  sale con los candidatos: {_ids(gone)}")
    return "\n".join(lines)


# --- the command line ---------------------------------------------------------------


def _read_json(path: str | None):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CandidateError(f"no se puede leer {path}: {exc}") from exc


async def _load_cli(pattern: str) -> int:
    from adelia.db import engine

    try:
        refuse_unless_scratch(settings.postgres_db)
        paths = resolve(pattern)
        try:
            rows = await load_candidates(paths)
        except CandidateError:
            raise
        except Exception as exc:  # noqa: BLE001 - no key, Mistral down: said, not a traceback
            raise CandidateError(
                f"no se pudieron cargar ({type(exc).__name__}: {exc}); la copia efímera puede "
                "quedar a medias, y se borra al acabar el gate"
            ) from exc
    finally:
        await engine.dispose()
    print(_render_load(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="load the candidate files into the scratch copy")
    load.add_argument("glob", help="e.g. apps/api/adelia/enrichment/candidates/*.json")
    cmp_ = sub.add_parser("compare", help="compare the gate runs without and with them")
    cmp_.add_argument("--without", required=True)
    cmp_.add_argument("--with", dest="with_", required=True)
    cmp_.add_argument("--preview-without")
    cmp_.add_argument("--preview-with")
    exp = sub.add_parser("explain", help="named questions source by source, without and with")
    exp.add_argument("--without", required=True)
    exp.add_argument("--with", dest="with_")
    args = parser.parse_args(argv)
    try:
        if args.command == "load":
            return asyncio.run(_load_cli(args.glob))
        if args.command == "explain":
            # A diagnostic: it prints, and never decides the gate.
            print(explain(_read_json(args.without), _read_json(args.with_)))
            return 0
        text, status = compare(
            _read_json(args.without), _read_json(args.with_),
            _read_json(args.preview_without), _read_json(args.preview_with),
        )
    except CandidateError as exc:
        print(f"candidatos: {exc}")
        return 2
    print(text)
    return status


if __name__ == "__main__":
    sys.exit(main())
