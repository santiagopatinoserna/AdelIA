"""The deploy's clinical gate for groups A and B, driven with fake ssh and docker.

Until 2026-11-06 `scripts/deploy-prod.sh` ran the golden set on the Mac, where
there is no evidence database and no key: groups A and B always skipped and
the deploy went on with a warning (three deploys in one night). The gate now
runs on the server, in a container of the NEW image, against a scratch copy
of the production corpus migrated to the new head, and only a pass lets
`up -d` replace the container that serves the mothers.

Three scripts, three layers, each tested with the next one faked:

* `scripts/deploy-prod.sh` (the Mac): fake `ssh` on the PATH.
* `scripts/prod-golden-gate.sh` (the server): fake `docker` on the PATH.
* `apps/api/scripts/golden_gate.sh` (inside the golden container): fake
  `.venv/bin/alembic` and `.venv/bin/python`.

None of them touches a network, a database or production.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
DEPLOY = REPO / "scripts" / "deploy-prod.sh"
SERVER_GATE = REPO / "scripts" / "prod-golden-gate.sh"
CONTAINER_GATE = REPO / "apps" / "api" / "scripts" / "golden_gate.sh"
OVERLAY = REPO / "infra" / "docker-compose.golden.yml"
DOCKERFILE = REPO / "apps" / "api" / "Dockerfile"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def _executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _index(lines: list[str], needle: str) -> int:
    for i, line in enumerate(lines):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# deploy-prod.sh, with ssh faked and the parts that need git, rsync and curl
# replaced by stubs after sourcing (the same guard scripts/test-deploy-args.sh
# relies on keeps main from running on source)
# ---------------------------------------------------------------------------

_HARNESS = """
set -euo pipefail
source "$DEPLOY"
check_tree_is_deployable() { :; }
run_golden_gate() { log "local golden stub (skip=$1)"; }
discover_host() { printf '10.0.0.9\\n'; }
sync_code() { log "sync stub"; }
verify() { log "verify stub"; }
main "$@"
"""


def _deploy(tmp_path: Path, *args: str, gate_rc: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "ssh.log"
    _executable(
        bin_dir / "ssh",
        f"""#!/usr/bin/env bash
cmd="${{@: -1}}"
printf '%s\\n' "$cmd" >> "{log}"
case "$cmd" in
  *prod-golden-gate.sh*)
    printf 'Golden set (auditoría 3.1/3.2)\\n  grupo A, recall@4:      0.94 sobre 18\\n'
    exit "${{FAKE_GATE_RC:-0}}" ;;
esac
exit 0
""",
    )
    harness = tmp_path / "harness.sh"
    harness.write_text(_HARNESS, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DEPLOY": str(DEPLOY),
        "FAKE_GATE_RC": str(gate_rc),
    }
    proc = subprocess.run(
        ["bash", str(harness), *args], env=env, capture_output=True, text=True, timeout=60
    )
    return proc, _lines(log)


def test_an_api_deploy_runs_the_server_gate_before_up(tmp_path):
    proc, ssh = _deploy(tmp_path, "api")
    assert proc.returncode == 0, proc.stderr
    gate = _index(ssh, "prod-golden-gate.sh")
    up = _index(ssh, "up -d")
    assert gate < up
    assert ssh[gate] == "cd /opt/adelia && bash scripts/prod-golden-gate.sh"
    assert "up -d --build api" in ssh[up]
    # The report reaches the deploy log, prefixed like the rest of it.
    assert "[deploy]   " in proc.stderr and "recall@4:      0.94 sobre 18" in proc.stderr


def test_the_default_deploy_of_api_and_web_is_gated(tmp_path):
    proc, ssh = _deploy(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert _index(ssh, "prod-golden-gate.sh") < _index(ssh, "up -d --build api web")


def test_a_failed_gate_never_reaches_up_and_exits_non_zero(tmp_path):
    proc, ssh = _deploy(tmp_path, "api", "web", gate_rc=1)
    assert proc.returncode != 0
    assert not [line for line in ssh if "up -d" in line], ssh
    assert "golden set FAILED" in proc.stderr
    assert "previous version is still serving" in proc.stderr
    assert "verify stub" not in proc.stderr
    assert "--skip-golden" in proc.stderr


def test_a_gate_that_could_not_run_also_stops_the_deploy(tmp_path):
    proc, ssh = _deploy(tmp_path, "api", gate_rc=2)
    assert proc.returncode != 0
    assert not [line for line in ssh if "up -d" in line], ssh
    assert "golden set DID NOT RUN" in proc.stderr
    assert "previous version is still serving" in proc.stderr


def test_an_ssh_failure_during_the_gate_is_a_gate_that_did_not_run(tmp_path):
    proc, ssh = _deploy(tmp_path, "api", gate_rc=255)
    assert proc.returncode != 0
    assert not [line for line in ssh if "up -d" in line], ssh
    assert "golden set DID NOT RUN" in proc.stderr


def test_skip_golden_still_deploys_without_the_gate_and_says_so(tmp_path):
    proc, ssh = _deploy(tmp_path, "api", "--skip-golden")
    assert proc.returncode == 0, proc.stderr
    assert not [line for line in ssh if "prod-golden-gate.sh" in line], ssh
    assert "up -d --build api" in ssh[_index(ssh, "up -d")]
    assert "local golden stub (skip=1)" in proc.stderr
    assert "WARNING: --skip-golden" in proc.stderr
    assert "groups A and B did not run" in proc.stderr


def test_a_web_only_deploy_does_not_run_groups_a_and_b(tmp_path):
    proc, ssh = _deploy(tmp_path, "web")
    assert proc.returncode == 0, proc.stderr
    assert not [line for line in ssh if "prod-golden-gate.sh" in line], ssh
    assert "up -d --build web" in ssh[_index(ssh, "up -d")]
    assert "web only" in proc.stderr


def test_a_service_merely_named_like_api_does_not_trigger_the_gate(tmp_path):
    """`api` as a whole word: a future `api-worker` alone is not the api."""
    proc, ssh = _deploy(tmp_path, "web", "apiary")
    assert not [line for line in ssh if "prod-golden-gate.sh" in line], ssh


# ---------------------------------------------------------------------------
# prod-golden-gate.sh, on the server, with docker faked
# ---------------------------------------------------------------------------


def _server_gate(
    tmp_path: Path, *, build_rc: int = 0, copy_rc: int = 0, run_rc: int = 0
) -> tuple[subprocess.CompletedProcess, list[str]]:
    root = tmp_path / "opt-adelia"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SERVER_GATE, root / "scripts" / SERVER_GATE.name)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    _executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
# One line per call: the scripts handed to `bash -c` span several.
printf '%s\\n' "$(printf '%s ' "$@" | tr '\\n' ' ')" >> "{log}"
case " $* " in
  *" build "*) exit "${{FAKE_BUILD_RC:-0}}" ;;
  *pg_dump*) exit "${{FAKE_COPY_RC:-0}}" ;;
  *" run "*) printf '{{"recall_at_4": 0.94}}\\n'; exit "${{FAKE_RUN_RC:-0}}" ;;
esac
exit 0
""",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_BUILD_RC": str(build_rc),
        "FAKE_COPY_RC": str(copy_rc),
        "FAKE_RUN_RC": str(run_rc),
    }
    proc = subprocess.run(
        ["bash", str(root / "scripts" / SERVER_GATE.name)],
        env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path,
    )
    return proc, _lines(log)


def test_the_server_gate_builds_copies_runs_and_cleans_up_in_that_order(tmp_path):
    proc, docker = _server_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    build = _index(docker, " build api-golden")
    copy = _index(docker, "pg_dump")
    run = _index(docker, " run ")
    drop = max(i for i, line in enumerate(docker) if "dropdb" in line and "pg_dump" not in line)
    assert build < copy < run < drop
    for line in docker:
        assert line.startswith(
            "compose -f infra/docker-compose.prod.yml -f infra/docker-compose.golden.yml "
            "--env-file .env.prod --profile golden "
        ), line
    assert "run --rm --no-deps -e POSTGRES_DB=adelia_golden_gate api-golden bash scripts/golden_gate.sh" in docker[run]
    assert '{"recall_at_4": 0.94}' in proc.stdout
    assert "duración del gate" in proc.stdout


def test_the_server_gate_never_rebuilds_the_image_that_serves(tmp_path):
    """Building `api` in the gate would retag the serving image before the
    verdict: after a failed gate, any later `docker compose up -d api` (an
    .env.prod change, a restart) would quietly roll out the code that failed.
    The gate builds only `api-golden`; `up -d --build` builds `api` after."""
    proc, docker = _server_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    builds = [line for line in docker if " build " in line]
    assert builds, docker
    for line in builds:
        assert line.rstrip().endswith(" build api-golden"), line


def test_the_server_gate_never_starts_stops_or_migrates_the_live_stack(tmp_path):
    proc, docker = _server_gate(tmp_path)
    for line in docker:
        for verb in (" up ", " down ", " restart ", " stop ", " rm "):
            assert verb not in f" {line} ", line
        assert "alembic upgrade" not in line, "migrations run inside the container, on the scratch db"
    # The scratch copy and the drop work on the scratch name, guarded against
    # ever being the live database.
    copy = docker[_index(docker, "pg_dump")]
    assert "SCRATCH_DB=adelia_golden_gate" in copy and '"$POSTGRES_DB"' in copy
    assert '[ "$SCRATCH_DB" != "$POSTGRES_DB" ]' in copy


@pytest.mark.parametrize("run_rc", [1, 2])
def test_the_server_gate_passes_the_verdict_through_and_still_cleans_up(tmp_path, run_rc):
    proc, docker = _server_gate(tmp_path, run_rc=run_rc)
    assert proc.returncode == run_rc
    assert "dropdb" in docker[-1]


def test_a_build_that_fails_is_a_gate_that_did_not_run(tmp_path):
    proc, docker = _server_gate(tmp_path, build_rc=1)
    assert proc.returncode == 2
    assert not [line for line in docker if " run " in line or "pg_dump" in line], docker


def test_a_corpus_copy_that_fails_is_a_gate_that_did_not_run_and_is_cleaned(tmp_path):
    proc, docker = _server_gate(tmp_path, copy_rc=1)
    assert proc.returncode == 2
    assert not [line for line in docker if " run " in line], docker
    assert "dropdb" in docker[-1] and "pg_dump" not in docker[-1]


def test_the_server_gate_never_reads_the_env_file():
    text = SERVER_GATE.read_text(encoding="utf-8")
    for line in text.splitlines():
        if ".env.prod" in line and not line.lstrip().startswith("#"):
            assert "--env-file" in line, line


# ---------------------------------------------------------------------------
# golden_gate.sh, inside the container, with the venv faked
# ---------------------------------------------------------------------------

_REPORT_RAN = '{\n  "recall_at_4": 0.94,\n  "skipped_reason": null,\n  "results": {}\n}\n'
_REPORT_SKIPPED = '{\n  "recall_at_4": null,\n  "skipped_reason": "sin corpus",\n  "results": {}\n}\n'


def _container_gate(
    tmp_path: Path,
    *,
    db: str = "adelia_golden_gate",
    alembic_rc: int = 0,
    load_rc: int = 0,
    pytest_rc: int = 0,
    report: str | None = _REPORT_RAN,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    app = tmp_path / "app"
    (app / "scripts").mkdir(parents=True)
    (app / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(CONTAINER_GATE, app / "scripts" / CONTAINER_GATE.name)
    log = tmp_path / "venv.log"
    _executable(
        app / ".venv" / "bin" / "alembic",
        f"""#!/usr/bin/env bash
printf 'alembic %s\\n' "$*" >> "{log}"
exit {alembic_rc}
""",
    )
    report_src = tmp_path / "report.json"
    if report is not None:
        report_src.write_text(report, encoding="utf-8")
    _executable(
        app / ".venv" / "bin" / "python",
        f"""#!/usr/bin/env bash
if [ "$1" = "-m" ] && [ "$2" = "pytest" ]; then
  printf 'pytest deploy=%s %s\\n' "${{ADELIA_GOLDEN_DEPLOY:-}}" "$*" >> "{log}"
  [ -f "{report_src}" ] && cp "{report_src}" golden_report.json
  exit {pytest_rc}
fi
printf 'python %s\\n' "$(printf '%s ' "$@" | tr '\\n' ' ')" >> "{log}"
exit {load_rc}
""",
    )
    env = {**os.environ, "POSTGRES_DB": db}
    env.pop("ADELIA_GOLDEN_DEPLOY", None)
    proc = subprocess.run(
        ["bash", str(app / "scripts" / CONTAINER_GATE.name)],
        env=env, capture_output=True, text=True, timeout=60, cwd=tmp_path,
    )
    return proc, _lines(log)


def test_inside_the_container_it_migrates_loads_the_corpus_then_runs_the_set(tmp_path):
    proc, calls = _container_gate(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert calls[0] == "alembic upgrade head"
    assert calls[1].startswith("python -c ") and "load_startup_corpora" in calls[1]
    assert calls[2].startswith("pytest deploy=1 -m pytest")
    assert "tests/test_rag_golden.py" in calls[2]
    assert '"recall_at_4": 0.94' in proc.stdout


def test_inside_the_container_it_refuses_a_database_that_is_not_the_scratch_copy(tmp_path):
    """The live database must never be migrated by the gate, whatever the env says."""
    proc, calls = _container_gate(tmp_path, db="adelia")
    assert proc.returncode == 2
    assert calls == []
    assert "adelia" in proc.stdout and "_golden_gate" in proc.stdout


@pytest.mark.parametrize(
    ("pytest_rc", "report", "want"),
    [
        (1, _REPORT_RAN, 1),  # A and B ran and missed: failed
        (1, _REPORT_SKIPPED, 2),  # A and B could not run: not run
        (2, None, 2),  # collection error, no report: not run
    ],
)
def test_inside_the_container_failed_and_not_run_are_told_apart(tmp_path, pytest_rc, report, want):
    proc, _ = _container_gate(tmp_path, pytest_rc=pytest_rc, report=report)
    assert proc.returncode == want, proc.stdout


def test_inside_the_container_a_migration_that_fails_stops_before_the_set(tmp_path):
    proc, calls = _container_gate(tmp_path, alembic_rc=1)
    assert proc.returncode == 2
    assert not [c for c in calls if c.startswith("pytest")], calls


def test_inside_the_container_a_corpus_load_that_crashes_stops_before_the_set(tmp_path):
    proc, calls = _container_gate(tmp_path, load_rc=1)
    assert proc.returncode == 2
    assert not [c for c in calls if c.startswith("pytest")], calls


# ---------------------------------------------------------------------------
# The image and the compose overlay the gate runs on
# ---------------------------------------------------------------------------


def _stages() -> list[tuple[str, str]]:
    """(FROM line, body) per stage of apps/api/Dockerfile."""
    stages: list[tuple[str, list[str]]] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM "):
            stages.append((line, []))
        elif stages:
            stages[-1][1].append(line)
    return [(head, "\n".join(body)) for head, body in stages]


def test_the_default_image_is_still_the_production_one_without_tests():
    """`docker compose build api` and the Fly build use the LAST stage."""
    head, body = _stages()[-1]
    assert " AS golden" not in head
    assert "tests" not in body and "pytest" not in body
    joined = "\n".join(b for _, b in _stages())
    assert "uv sync --frozen --no-dev" in joined
    assert 'CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn' in joined


def test_the_golden_stage_carries_the_tests_and_the_dev_tools_on_the_same_code():
    golden = [(h, b) for h, b in _stages() if h.endswith(" AS golden")]
    assert len(golden) == 1
    head, body = golden[0]
    base = head.split()[1]
    assert any(h.endswith(f" AS {base}") for h, _ in _stages()), "golden builds on the runtime base"
    assert _stages()[-1][0] == f"FROM {base} AS runtime"
    assert "uv sync --frozen\n" in body + "\n" and "--no-dev" not in body
    assert "COPY tests ./tests" in body


def test_the_overlay_adds_a_golden_service_that_is_the_api_with_another_target():
    data = yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    assert set(data["services"]) == {"api-golden"}
    svc = data["services"]["api-golden"]
    assert svc["extends"] == {"file": "docker-compose.prod.yml", "service": "api"}
    assert svc["build"] == {"context": "../apps/api", "target": "golden"}
    # Never started by an `up` that forgets to name its services.
    assert svc["profiles"] == ["golden"]
    assert svc["restart"] == "no"
    assert svc["healthcheck"] == {"disable": True}


# ---------------------------------------------------------------------------
# verify() must ask the API itself, not only the pages the web serves
# ---------------------------------------------------------------------------
# 2026-11-06: right after a deploy printed "Deployment verified OK", nginx
# logged five 503s on POST /api/demo/ask (the API container was still
# starting). Every check in verify() was served by the web container or read
# the database directly, so an API that was starting, or crash-looping, passed.
# /healthz is the API's readiness endpoint, mapped by nginx and reaching
# Postgres (routers/health.py): verify waits for it like the browser would.

_VERIFY_HARNESS = """
set -euo pipefail
source "$DEPLOY"
check_url() {
  printf 'check %s\\n' "$1" >> "$CALLS"
  case "$1" in */es/demo) printf '307' ;; */foo.txt) printf '404' ;; *) printf '200' ;; esac
}
wait_for_url() {
  printf 'wait %s\\n' "$1" >> "$CALLS"
  case "$1" in
    */healthz) printf '%s\\n' "$API_CODE"; [[ "$API_CODE" == "200" ]] ;;
    *) printf '200\\n' ;;
  esac
}
curl() { printf 'https://adelia.godi.ai/es'; }
check_pwa() { return 0; }
expected_alembic_head() { printf 'head1\\n'; }
verify 10.0.0.9 "$SERVICES"
"""


def _verify(tmp_path: Path, services: str, api_code: str) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _executable(bin_dir / "ssh", "#!/usr/bin/env bash\nprintf 'head1\\n'\n")
    calls = tmp_path / "calls.log"
    harness = tmp_path / "verify.sh"
    harness.write_text(_VERIFY_HARNESS, encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "DEPLOY": str(DEPLOY), "CALLS": str(calls), "SERVICES": services, "API_CODE": api_code,
    }
    proc = subprocess.run(["bash", str(harness)], env=env, capture_output=True, text=True, timeout=60)
    return proc, _lines(calls)


@pytest.mark.parametrize("services", ["api", "web", "api web"])
def test_verify_waits_for_the_api_to_answer_through_nginx(tmp_path, services):
    proc, calls = _verify(tmp_path, services, "200")
    assert proc.returncode == 0, proc.stderr
    assert "wait https://adelia.godi.ai/healthz" in calls
    assert "GET /healthz:" in proc.stderr and "Deployment verified OK." in proc.stderr


def test_an_api_that_does_not_answer_fails_the_verification(tmp_path):
    proc, calls = _verify(tmp_path, "api", "503")
    assert proc.returncode != 0
    assert "FAIL: GET /healthz -> 503" in proc.stderr
    assert "Deployment verified OK." not in proc.stderr
