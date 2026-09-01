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

    type: Literal["token", "tool_call", "card", "final", "error"]
    content: str = ""
    card: dict | None = None
    tool_name: str = ""
    citations: list[dict] = field(default_factory=list)
    evidence_citations: list[dict] = field(default_factory=list)
