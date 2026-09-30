"""
Phase 4, Gemini provider -- plan/act loop over the Phase 3 Controller.
Free key, no card: aistudio.google.com/apikey

The model never sees which engine is behind a tool call. It sees
`navigate` (always available) plus whatever Controller.available_actions
holds for the current page, and that list changes after every navigate.

Now also carries Phase 5 instrumentation (run_logger) and an optional
on_step callback so the web UI can show each step live.

Two things written from Google's docs without being runnable here:
  1. Only sync client usage was confirmed for this endpoint, so calls
     are wrapped in asyncio.to_thread() to stay off the event loop.
  2. No dedicated system-prompt parameter was confirmed, so the system
     prompt is prepended to the first instruction.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any, Awaitable, Callable, Optional

from google import genai
from dotenv import load_dotenv

from controller.controller import Controller
from controller.schema import ActionSchema, NormalizedResult

from .run_logger import RunLogger

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))

StepCallback = Callable[[dict[str, Any]], Awaitable[None]]

NAVIGATE_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "navigate",
    "description": (
        "Navigate the browser to an absolute URL. Always available. The other "
        "tools change after every navigate call to reflect what the new page supports."
    ),
    "parameters": {
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
    return {
        "type": "function",
        "name": a.name,
        "description": a.description,
        "parameters": a.input_schema or {"type": "object", "properties": {}},
    }


def _result_to_content(r: NormalizedResult) -> list[dict[str, Any]]:
    if not r.success:
        return [{"type": "text", "text": f"Error: {r.error}"}]
    if isinstance(r.data, (bytes, bytearray)):
        return [
            {"type": "text", "text": "(screenshot attached)"},
            {"type": "image", "mime_type": "image/png",
             "data": base64.b64encode(r.data).decode("ascii")},
        ]
    text = r.data if isinstance(r.data, str) else json.dumps(r.data)
    return [{"type": "text", "text": text}]


def _usage(interaction: Any) -> tuple[int, int]:
    """Best-effort token extraction -- field names vary by SDK version, and
    missing usage must never break a run, so this degrades to (0, 0)."""
    u = getattr(interaction, "usage", None) or getattr(interaction, "usage_metadata", None)
    if u is None:
        return 0, 0
    prompt = getattr(u, "prompt_tokens", None) or getattr(u, "prompt_token_count", 0) or 0
    completion = getattr(u, "completion_tokens", None) or getattr(u, "candidates_token_count", 0) or 0
    return int(prompt), int(completion)


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
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set -- get a free key at aistudio.google.com/apikey, "
                "copy .env.example to .env, and fill it in"
            )
        self.client = genai.Client(api_key=api_key)
        self.controller = Controller()
        self.on_step = on_step
        self._last_interaction_id: str | None = None
        self._first_turn = True

    def _current_tools(self) -> list[dict[str, Any]]:
        return [NAVIGATE_TOOL] + [_tool_schema(a) for a in self.controller.available_actions]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[NormalizedResult, str]:
        name = _clean_tool_name(name)
        if name == "navigate":
            return await self.controller.navigate(args["url"]), "playwright"
        r = await self.controller.execute(name, args)
        return r, r.engine

    async def _create(self, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.client.interactions.create, **kwargs)

    async def run_task(self, instruction: str) -> str:
        with RunLogger(instruction, "gemini", MODEL) as log:
            if self._first_turn:
                current_input: Any = f"{SYSTEM_PROMPT}\n\nTask: {instruction}"
                self._first_turn = False
            else:
                current_input = [{"type": "user_input",
                                  "content": [{"type": "text", "text": instruction}]}]

            for step_num in range(MAX_STEPS):
                interaction = await self._create(
                    model=MODEL,
                    input=current_input,
                    tools=self._current_tools(),
                    previous_interaction_id=self._last_interaction_id,
                )
                self._last_interaction_id = interaction.id
                log.record_tokens(*_usage(interaction))

                calls = [s for s in interaction.steps if s.type == "function_call"]
                if not calls:
                    return interaction.output_text

                results = []
                for call in calls:
                    # Display/dispatch on the clean name, but echo the original
                    # back in the function_result -- the provider matches on
                    # the name it sent us.
                    shown = _clean_tool_name(call.name)
                    result, engine = await self._dispatch(call.name, call.arguments)
                    log.record_step(engine, result.success)
                    line = (f"  [step {step_num + 1}] engine={engine:<10} "
                            f"tool={shown}({call.arguments}) -> success={result.success}")
                    print(line)
                    if self.on_step:
                        await self.on_step({
                            "step": step_num + 1,
                            "engine": engine,
                            "tool": shown,
                            "args": call.arguments,
                            "success": result.success,
                            "error": result.error,
                        })
                    results.append({
                        "type": "function_result",
                        "name": call.name,
                        "call_id": call.id,
                        "result": _result_to_content(result),
                    })
                current_input = results

            return "(stopped: hit the max step limit -- see AGENT_MAX_STEPS)"

    async def close(self) -> None:
        await self.controller.close()
