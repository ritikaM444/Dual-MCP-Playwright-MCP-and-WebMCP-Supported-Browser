"""
Web UI for the hybrid browser agent -- the "watch it work" interface.

Serves one page at http://localhost:8000 with a chat box. You type a
task; each step streams back live as the agent executes it, labelled
with the engine that handled it (webmcp = Engine 1 native tools,
playwright = Engine 2 DOM fallback). That per-step engine indicator is a
stated live-demo requirement, not decoration.

Pair with HEADLESS=false and SLOW_MO=500 in .env so the examiner sees
this panel AND the real Chromium window driving itself.

Run:  python -m webapp.server        (then open http://localhost:8000)
Also start the demo pages in another terminal:
      python packages/engine_webmcp/demo_pages/server.py
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .provider import PROVIDER, get_agent_class

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="MCP Hybrid Browser Agent")


class Task(BaseModel):
    instruction: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def config() -> dict[str, Any]:
    return {
        "provider": PROVIDER,
        "visible_browser": os.environ.get("HEADLESS", "true").lower() == "false",
        "demo_base": os.environ.get("DEMO_BASE_URL", "http://localhost:4173"),
    }


@app.post("/api/run")
async def run(task: Task) -> StreamingResponse:
    """Runs one task, streaming step events to the page as they happen.

    Server-Sent Events. A queue bridges the agent's on_step callback
    (which fires deep inside the plan/act loop) to this response stream.
    A fresh Agent per request keeps each demo task independent -- no
    leftover page state from the previous run confusing the examiner.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def on_step(event: dict[str, Any]) -> None:
        await queue.put({"type": "step", **event})

    Agent = get_agent_class()
    agent = Agent(on_step=on_step)

    async def drive() -> None:
        try:
            reply = await agent.run_task(task.instruction)
            await queue.put({"type": "done", "reply": reply})
        except Exception as exc:  # surfaced in the UI rather than a blank page
            await queue.put({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            await agent.close()
            await queue.put(None)

    async def stream():
        worker = asyncio.create_task(drive())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            await worker

    return StreamingResponse(stream(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("WEBAPP_PORT", "8000"))
    print(f"Web UI on http://localhost:{port}  (provider: {PROVIDER})")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
