"""
Phase 4, Anthropic provider -- same plan/act loop and same public
interface as agent_gemini.py (run_task / close / on_step callback), so
cli.py and the web UI work with either without changes.
Needs billing at console.anthropic.com; Gemini is the free default.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Awaitable, Callable, Optional

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from controller.controller import Controller
from controller.schema import ActionSchema, NormalizedResult

from .run_logger import RunLogger

load_dotenv()

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))

StepCallback = Callable[[dict[str, Any]], Awaitable[None]]

NAVIGATE_TOOL: dict[str, Any] = {
    "name": "navigate",
    "description": (
        "Navigate the browser to an absolute URL. Always available. The other "
        "tools change after every navigate call to reflect what the new page supports."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Absolute URL"}},
        "required": ["url"],
    },
}

SYSTEM_PROMPT = """You are a browser automation agent working on one task at a time.

You always have a `navigate` tool. After navigating, the other tools you can
call change depending on the page: some pages expose their own native
actions (fast, structured, page-specific); pages without native support
fall back to generic browser actions (click, type, extract_text,
screenshot). You are never told which kind you're using -- just call
whatever tools are offered to you after each navigate.

Work step by step: navigate, observe, then act. Stop and report back in
plain text once the task is complete or you're stuck."""


def _tool_schema(a: ActionSchema) -> dict[str, Any]:
    return {"name": a.name, "description": a.description,
            "input_schema": a.input_schema or {"type": "object", "properties": {}}}


def _result_to_content(r: NormalizedResult) -> list[dict[str, Any]]:
    if not r.success:
        return [{"type": "text", "text": f"Error: {r.error}"}]
    if isinstance(r.data, (bytes, bytearray)):
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                 "data": base64.b64encode(r.data).decode("ascii")}}]
    return [{"type": "text", "text": str(r.data)}]


def _clean_tool_name(name: str) -> str:
    """Strip a namespace prefix from a tool name.

    Some providers (Gemini notably) return tool calls namespaced, e.g.
    "default_api:navigate" instead of "navigate". Without stripping that,
    `navigate` is not recognised as the always-available browser action,
    the call falls through to the page's own tool registry, and the task
    gets stuck on whatever page it is on -- unable to ever leave it.
    WebMCP tool names never contain ':' or '.', so taking the last
    segment is safe.
    """
    for sep in (":", "."):
        if sep in name:
            name = name.rsplit(sep, 1)[-1]
    return name.strip()


class Agent:
    def __init__(self, on_step: Optional[StepCallback] = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set -- set LLM_PROVIDER=gemini to use the free path instead"
            )
        self.client = AsyncAnthropic(api_key=api_key)
        self.controller = Controller()
        self.on_step = on_step
        self.messages: list[dict[str, Any]] = []

    def _current_tools(self) -> list[dict[str, Any]]:
        return [NAVIGATE_TOOL] + [_tool_schema(a) for a in self.controller.available_actions]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[NormalizedResult, str]:
        name = _clean_tool_name(name)
        if name == "navigate":
            return await self.controller.navigate(args["url"]), "playwright"
        r = await self.controller.execute(name, args)
        return r, r.engine

    async def run_task(self, instruction: str) -> str:
        with RunLogger(instruction, "anthropic", MODEL) as log:
            self.messages.append({"role": "user", "content": instruction})

            for step in range(MAX_STEPS):
                response = await self.client.messages.create(
                    model=MODEL, max_tokens=1024, system=SYSTEM_PROMPT,
                    tools=self._current_tools(), messages=self.messages,
                )
                self.messages.append({"role": "assistant", "content": response.content})
                usage = getattr(response, "usage", None)
                if usage is not None:
                    log.record_tokens(getattr(usage, "input_tokens", 0) or 0,
                                      getattr(usage, "output_tokens", 0) or 0)

                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if not tool_uses:
                    return "\n".join(b.text for b in response.content if b.type == "text")

                results = []
                for b in tool_uses:
                    result, engine = await self._dispatch(b.name, b.input)
                    log.record_step(engine, result.success)
                    print(f"  [step {step + 1}] engine={engine:<10} "
                          f"tool={b.name}({b.input}) -> success={result.success}")
                    if self.on_step:
                        await self.on_step({"step": step + 1, "engine": engine, "tool": b.name,
                                            "args": b.input, "success": result.success,
                                            "error": result.error})
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": _result_to_content(result),
                                    "is_error": not result.success})
                self.messages.append({"role": "user", "content": results})

            return "(stopped: hit the max step limit -- see AGENT_MAX_STEPS)"

    async def close(self) -> None:
        await self.controller.close()
