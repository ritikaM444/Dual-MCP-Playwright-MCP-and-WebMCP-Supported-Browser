"""Shared normalized result + task-state types for the Agent Controller Layer."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

EngineName = Literal["webmcp", "playwright"]


@dataclass
class NormalizedResult:
    """
    One common result shape both engines get mapped into (BUILD_STEPS.md
    Phase 3 step 2: Engine 1 returns structured JSON, Engine 2 returns DOM
    text/screenshots), so the agent layer (Phase 4) never has to know
    which engine actually produced a result.
    """

    engine: EngineName
    success: bool
    data: Any  # the useful payload: text, a WebMCP tool's JSON result, PNG bytes, etc.
    raw: Any = None  # the engine-native, unprocessed result -- kept for debugging/logging
    error: Optional[str] = None


@dataclass
class ActionSchema:
    """
    One entry in the action menu the controller currently exposes --
    either a WebMCP tool schema (Engine 1) or one of the five fixed
    Playwright actions (Engine 2). Phase 4's agent reads this list to know
    what it can call next; it does not need to know which engine backs
    each entry.
    """

    name: str
    description: str
    input_schema: Optional[dict[str, Any]]
    engine: EngineName


@dataclass
class TaskState:
    """
    Phase 3 step 3: basic task-state tracking so the controller doesn't
    lose context when it switches engines mid-task.
    """

    current_url: Optional[str] = None
    current_engine: Optional[EngineName] = None
    history: list[NormalizedResult] = field(default_factory=list)

    def record(self, result: NormalizedResult) -> None:
        self.history.append(result)
