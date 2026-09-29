"""
Phase 3 step 2: the output normalizer.

Engine 1 (WebMCP, via engine_webmcp.native_bridge.call_webmcp_tool)
returns {"ok": bool, "result": ..., "error": ...}. Engine 2 (Playwright,
via engine_playwright.actions) returns plain strings or raw PNG bytes.
This maps both shapes into one NormalizedResult so the rest of the
controller -- and later, the Phase 4 agent -- only ever deals with one
shape regardless of which engine produced it.
"""
from __future__ import annotations

from typing import Any, Optional

from .schema import NormalizedResult


def normalize_webmcp(raw: dict[str, Any]) -> NormalizedResult:
    ok = bool(raw.get("ok"))
    return NormalizedResult(
        engine="webmcp",
        success=ok,
        data=raw.get("result") if ok else None,
        raw=raw,
        error=None if ok else raw.get("error", "unknown WebMCP tool error"),
    )


def normalize_playwright(data: Any, *, error: Optional[str] = None) -> NormalizedResult:
    return NormalizedResult(
        engine="playwright",
        success=error is None,
        data=data if error is None else None,
        raw=data,
        error=error,
    )
