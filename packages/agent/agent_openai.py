"""
OpenAI-compatible provider -- used for OmniRoute, and for any other
gateway or provider that speaks the OpenAI chat-completions format.

Why this exists: Gemini's free tier caps full Flash models at roughly 20
requests per day, and one agent task burns one request per step. A
complex task in front of an examiner can exhaust that mid-demo.
OmniRoute (github.com/diegosouzapw/OmniRoute) is a local MIT-licensed
gateway on http://localhost:20128/v1 that fans out across many free
providers and falls back automatically when one hits its quota, so the
rate limit stops being a single point of failure.

Same public interface as agent.py / agent_gemini.py (run_task, close,
on_step), so cli.py and the web UI use it without changes. If OmniRoute
misbehaves, set LLM_PROVIDER=gemini in .env and you are instantly back
on the previously-proven path -- that is the whole point of keeping the
three implementations interchangeable.

Model default is "auto": OmniRoute picks and re-picks a live provider
itself. Against a plain OpenAI-compatible endpoint, set OPENAI_MODEL to
a real model name instead.
"""
from __future__ import annotations

import json
import os
from typing import Any, Awaitable, Callable, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI

from controller.controller import Controller
from controller.schema import ActionSchema, NormalizedResult

from .run_logger import RunLogger

load_dotenv()

BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:20128/v1")
# OmniRoute needs no key; a placeholder keeps the SDK happy since it
# insists on some value being present.
API_KEY = os.environ.get("OPENAI_API_KEY", "omniroute-local")
MODEL = os.environ.get("OPENAI_MODEL", "auto")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))

StepCallback = Callable[[dict[str, Any]], Awaitable[None]]

NAVIGATE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
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
        "function": {
            "name": a.name,
            "description": a.description,
            "parameters": a.input_schema or {"type": "object", "properties": {}},
        },
    }


def _result_to_text(r: NormalizedResult) -> str:
    """OpenAI tool results must be a string, so a screenshot is reported as
    a note rather than an image -- the agent can still call extract_text to
    read the page, and the examiner sees the real browser window anyway."""
    if not r.success:
        return f"Error: {r.error}"
    if isinstance(r.data, (bytes, bytearray)):
        return f"(screenshot captured, {len(r.data)} bytes)"
    return r.data if isinstance(r.data, str) else json.dumps(r.data)


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
        self.client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
        self.controller = Controller()
        self.on_step = on_step
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def _current_tools(self) -> list[dict[str, Any]]:
        return [NAVIGATE_TOOL] + [_tool_schema(a) for a in self.controller.available_actions]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[NormalizedResult, str]:
        name = _clean_tool_name(name)
        if name == "navigate":
            return await self.controller.navigate(args["url"]), "playwright"
        r = await self.controller.execute(name, args)
        return r, r.engine

    async def run_task(self, instruction: str) -> str:
        with RunLogger(instruction, "omniroute", MODEL) as log:
            self.messages.append({"role": "user", "content": instruction})

            for step in range(MAX_STEPS):
                response = await self.client.chat.completions.create(
                    model=MODEL,
                    messages=self.messages,
                    tools=self._current_tools(),
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    log.record_tokens(getattr(usage, "prompt_tokens", 0) or 0,
                                      getattr(usage, "completion_tokens", 0) or 0)

                message = response.choices[0].message
                tool_calls = message.tool_calls or []

                # Echo the assistant turn back verbatim so the model keeps its
                # own tool-call ids in context.
                self.messages.append({
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.function.name, "arguments": c.function.arguments}}
                        for c in tool_calls
                    ] or None,
                })

                if not tool_calls:
                    return message.content or "(no answer returned)"

                for call in tool_calls:
                    name = call.function.name
                    try:
                        args = json.loads(call.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result, engine = await self._dispatch(name, args)
                    log.record_step(engine, result.success)
                    print(f"  [step {step + 1}] engine={engine:<10} "
                          f"tool={name}({args}) -> success={result.success}")
                    if self.on_step:
                        await self.on_step({"step": step + 1, "engine": engine, "tool": name,
                                            "args": args, "success": result.success,
                                            "error": result.error})
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _result_to_text(result),
                    })

            return "(stopped: hit the max step limit -- see AGENT_MAX_STEPS)"

    async def close(self) -> None:
        await self.controller.close()
