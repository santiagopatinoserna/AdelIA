"""The e2e CI job must not depend on Ubuntu's apt mirrors.

`playwright install --with-deps` runs apt-get, and on PR #80 (2026-11-11) it failed twice in a
row with "Temporary failure resolving 'azure.archive.ubuntu.com'" and exit code 100: no PR could
pass CI while the mirror was down, whatever the code. The job now runs inside the official
Playwright image, which already carries the browsers and their system libraries.

That image only works if its tag is the exact @playwright/test version in pnpm-lock.yaml: a
newer package looks for a browser build the image does not have. Dependabot bumps the npm
package weekly and knows nothing about the image tag, so these tests fail the bump PR in the
api job instead of letting e2e die later on "Executable doesn't exist".

Plain text parsing on purpose: pyyaml is only a transitive dependency of the API.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PNPM_LOCK = REPO_ROOT / "pnpm-lock.yaml"

IMAGE_RE = re.compile(r"mcr\.microsoft\.com/playwright:v(?P<version>[0-9][0-9.]*)-(?P<distro>\w+)")


def _e2e_job() -> str:
    """Text of the `e2e:` job, up to the next top-level job or the end of the file."""
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    assert "  e2e:" in lines, "ci.yml has no e2e job"
    body: list[str] = []
    for line in lines[lines.index("  e2e:") + 1 :]:
        if line.strip() and not line.startswith("    "):
            break
        body.append(line)
    assert any("pnpm e2e" in line for line in body), "e2e job parsed short"
    return "\n".join(body)


def _locked_playwright_versions() -> set[str]:
    text = PNPM_LOCK.read_text(encoding="utf-8")
    return set(re.findall(r"^  '@playwright/test@([0-9][0-9.]*)':$", text, re.MULTILINE))


def test_lockfile_resolves_one_playwright_version() -> None:
    versions = _locked_playwright_versions()
    assert len(versions) == 1, f"expected one @playwright/test in pnpm-lock.yaml, got {versions}"


def test_e2e_job_runs_in_the_playwright_image_of_the_locked_version() -> None:
    job = _e2e_job()
    container = re.search(r"^    container:\n\s+image:\s*(?P<image>\S+)", job, re.MULTILINE)
    assert container, "the e2e job must run in a container (the official Playwright image)"
    image = IMAGE_RE.fullmatch(container.group("image"))
    assert image, f"unexpected e2e image: {container.group('image')}"
    (locked,) = _locked_playwright_versions()
    assert image.group("version") == locked, (
        f"e2e image is Playwright {image.group('version')} but pnpm-lock.yaml has {locked}: "
        "bump the image tag in .github/workflows/ci.yml together with @playwright/test"
    )
    # noble is Ubuntu 24.04, the same base as the runner the job is pinned to.
    assert image.group("distro") == "noble"


def test_e2e_job_never_calls_apt() -> None:
    # Comments may tell the apt story; only what runs counts.
    job = "\n".join(line for line in _e2e_job().splitlines() if not line.lstrip().startswith("#"))
    assert "--with-deps" not in job
    assert "apt-get" not in job
    assert "install-deps" not in job
