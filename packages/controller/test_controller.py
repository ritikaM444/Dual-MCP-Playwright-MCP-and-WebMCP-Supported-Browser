"""
Phase 3 standalone test -- NO LLM (BUILD_STEPS.md checkpoint): drives the
Controller directly, starting on a WebMCP demo page (Engine 1), then
navigating to a real site with no WebMCP (Engine 2), and confirms the
engine switch happens correctly with one consistent NormalizedResult
shape throughout.

Requires the demo server running first, in another terminal:
    python packages/engine_webmcp/demo_pages/server.py

Run with: python -m controller.test_controller
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from .controller import Controller
from .schema import NormalizedResult

DEMO_BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:4173")


def summarize(result: NormalizedResult) -> dict[str, Any]:
    data = result.data
    if isinstance(data, (bytes, bytearray)):
        data = f"<{len(data)} bytes>"
    return {"engine": result.engine, "success": result.success, "data": data, "error": result.error}


async def main() -> None:
    controller = Controller()

    print(f"--- navigate to WebMCP demo page ({DEMO_BASE}/todo-app/) ---")
    nav1 = await controller.navigate(f"{DEMO_BASE}/todo-app/")
    print(summarize(nav1))
    print("engine selected:", controller.state.current_engine)
    print("actions available:", [a.name for a in controller.available_actions])
    assert controller.state.current_engine == "webmcp", "expected Engine 1 on the WebMCP demo page"

    add = await controller.execute("add-todo", {"text": "Buy milk"})
    print("add-todo:", summarize(add))
    assert add.success, "add-todo should have succeeded via Engine 1"

    print("\n--- navigate to a real site with no WebMCP (Hacker News) ---")
    nav2 = await controller.navigate("https://news.ycombinator.com/")
    print(summarize(nav2))
    print("engine selected:", controller.state.current_engine)
    print("actions available:", [a.name for a in controller.available_actions])
    assert controller.state.current_engine == "playwright", "expected Engine 2 fallback on a legacy site"

    extract = await controller.execute("extract_text", {"selector": ".titleline"})
    print("extract_text:", summarize(extract))
    assert extract.success, "extract_text should have succeeded via Engine 2"

    print(f"\n--- task state history: {len(controller.state.history)} recorded actions ---")
    for i, r in enumerate(controller.state.history):
        print(f"  [{i}] engine={r.engine} success={r.success}")

    await controller.close()
    print("\nOK: controller switched engines correctly with one consistent output shape throughout")


if __name__ == "__main__":
    asyncio.run(main())
