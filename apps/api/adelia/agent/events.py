from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class AgentEvent:
    """One SSE frame of an agent turn.

    `citations` and `evidence_citations` ride on the terminal `final` event
    and carry the same dicts the chat sends (audit 3.7). Before that, the
    agent's stream had no citation channel at all, so the answer contract
    demanded [ev_N] markers on a surface that could only paint them as text
    pointing at nothing.
    """

    type: Literal["token", "tool_call", "card", "final", "error", "status"]
    #: A token's text, an error's message, or a status's stage ("searching",
    #: "writing"): what the turn is doing while she waits (2026-11-11).
    content: str = ""
    card: dict | None = None
    tool_name: str = ""
    #: With the "writing" status: how many sources the answer is written from.
    sources: int = 0
    citations: list[dict] = field(default_factory=list)
    evidence_citations: list[dict] = field(default_factory=list)
