from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass
class AgentEvent:
    type: Literal["token", "tool_call", "card", "final", "error"]
    content: str = ""
    card: dict | None = None
    tool_name: str = ""
