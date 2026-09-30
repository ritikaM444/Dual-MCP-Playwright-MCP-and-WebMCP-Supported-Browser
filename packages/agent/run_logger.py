"""
Phase 5 instrumentation: per-task, per-engine logging.

This is the data the Parameter 3 research contribution needs -- success
rate, latency, and token cost, broken down by which engine executed each
step. Writes newline-delimited JSON (.jsonl) so runs append safely and
analysis is a one-liner in pandas later.

One row per completed task, written to packages/agent/logs/runs.jsonl:
  {task, provider, model, ok, seconds, steps, engine_counts,
   prompt_tokens, completion_tokens, total_tokens, error, timestamp}

Start collecting NOW and keep it running for weeks -- reconstructing this
data the night before Review 3 is not possible.
"""
from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOG_DIR = Path(__file__).parent / "logs"
LOG_PATH = LOG_DIR / "runs.jsonl"


class RunLogger:
    """Tracks one task run. Use as a context manager around run_task()."""

    def __init__(self, task: str, provider: str, model: str) -> None:
        self.task = task
        self.provider = provider
        self.model = model
        self.engine_counts: Counter[str] = Counter()
        self.steps = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.error: Optional[str] = None
        self._start = 0.0

    def record_step(self, engine: str, success: bool) -> None:
        self.steps += 1
        self.engine_counts[engine] += 1
        if not success:
            self.engine_counts[f"{engine}_failed"] += 1

    def record_tokens(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion

    def __enter__(self) -> "RunLogger":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.error = f"{exc_type.__name__}: {exc}"
        self._write(round(time.monotonic() - self._start, 2))
        return False  # never swallow the exception

    def _write(self, seconds: float) -> None:
        row: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": self.task,
            "provider": self.provider,
            "model": self.model,
            "ok": self.error is None,
            "seconds": seconds,
            "steps": self.steps,
            "engine_counts": dict(self.engine_counts),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "error": self.error,
        }
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            # Logging must never break a live demo.
            pass
