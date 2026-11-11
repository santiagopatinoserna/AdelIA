"""Every switch in config.py that changes an answer reaches the production api container.

infra/docker-compose.prod.yml passes only the variables it names, so a setting with no
line there is ignored in production whatever .env.prod says. It happened twice: PLAN_BREVITY
(fixed with its own line and test) and the four settings of #73 (FOLLOW_UP_BREVITY and the
three ANSWER_EFFORT_*), which a .env.prod could set and the container never saw. The
battery and the golden gate would then measure "on" while the mothers got "off".

So this reads Settings instead of keeping a list: every field that is a switch, off by
default (a bool that defaults to False, or a value that defaults to None), must have its
line in the api service, with the default that keeps today's behaviour. A new switch
without its line fails here, unless it is named below with the reason it stays out.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from adelia.config import Settings

INFRA = Path(__file__).resolve().parents[3] / "infra"
PROD = INFRA / "docker-compose.prod.yml"
GOLDEN = INFRA / "docker-compose.golden.yml"

#: Switches that are not passed as an off switch, each with its reason.
NOT_AN_OFF_LINE = {
    # Which address the rate limit counts, not what an answer says. Production has it
    # ON (Cloudflare tunnel); tests/test_ratelimit.py pins that line.
    "trust_cf_connecting_ip": "on in production, pinned by test_ratelimit",
    # Mistral's reasoning effort. config.py: do not set it in production before the
    # evaluation in docs/MODELOS.md, and it also needs MISTRAL_CHAT_MODEL (or
    # MISTRAL_BRIEFING_MODEL) pinned, which production does not pass either.
    "chat_reasoning_effort": "unmeasured, needs a pinned Mistral model first",
    "briefing_reasoning_effort": "unmeasured, needs a pinned Mistral model first",
    # Fused retrieval order. Never passed to production; adding its line is the step that
    # makes it reachable, once the eval harness shows the fused order is better.
    "retrieval_hybrid_enabled": "not reachable in production yet",
}

#: Named in the 2026-11-11 report: each must be found by the rule above.
KNOWN_ANSWER_SWITCHES = {
    "follow_up_brevity", "answer_effort_question", "answer_effort_plan",
    "answer_effort_follow_up", "plan_brevity", "lay_query_expansion",
    "warning_signs_retrieval", "no_unasked_refusals", "implicit_subject_expansion",
}


def _switches() -> dict[str, str]:
    """name -> the compose default that keeps the code's own default."""
    found = {}
    for name, field in Settings.model_fields.items():
        if field.annotation is bool and field.default is False:
            found[name] = "false"
        elif field.default is None:
            found[name] = ""
    return found


def _api_environment() -> dict[str, str]:
    data = yaml.safe_load(PROD.read_text(encoding="utf-8"))
    return data["services"]["api"]["environment"]


def test_the_rule_finds_every_switch_named_so_far():
    assert KNOWN_ANSWER_SWITCHES <= set(_switches())


def test_every_exception_is_still_a_switch():
    assert set(NOT_AN_OFF_LINE) <= set(_switches())
    assert not set(NOT_AN_OFF_LINE) & KNOWN_ANSWER_SWITCHES


@pytest.mark.parametrize("name", sorted(set(_switches()) - set(NOT_AN_OFF_LINE)))
def test_production_passes_the_switch_off_by_default(name):
    env_name = name.upper()
    default = _switches()[name]
    want = f"${{{env_name}:-{default}}}"
    got = _api_environment().get(env_name)
    assert got == want, (
        f"infra/docker-compose.prod.yml must pass `{env_name}: {want}` to the api service; "
        f"without it {env_name} in .env.prod never reaches the container (got {got!r})"
    )


@pytest.mark.parametrize("value, want", [
    ("", None), ("low", "low"), ("medium", "medium"), ("high", "high"),
])
def test_an_empty_effort_from_the_compose_is_today_s_behaviour(monkeypatch, value, want):
    # `${ANSWER_EFFORT_PLAN:-}` hands the container an empty string when .env.prod is
    # silent: it must read as unset, never fail the boot.
    for name in ("ANSWER_EFFORT_QUESTION", "ANSWER_EFFORT_PLAN", "ANSWER_EFFORT_FOLLOW_UP"):
        monkeypatch.setenv(name, value)
    s = Settings(_env_file=None)
    assert (s.answer_effort_question, s.answer_effort_plan, s.answer_effort_follow_up) == (
        want, want, want)


def test_the_golden_gate_measures_with_the_production_switches():
    # api-golden extends the api service; an environment of its own would let the gate
    # measure with other switches than the ones the mothers get.
    data = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))
    svc = data["services"]["api-golden"]
    assert svc["extends"] == {"file": "docker-compose.prod.yml", "service": "api"}
    assert "environment" not in svc and "env_file" not in svc
