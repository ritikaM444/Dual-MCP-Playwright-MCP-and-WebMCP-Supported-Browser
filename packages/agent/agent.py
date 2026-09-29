"""
Phase 4: the LLM agent (Anthropic provider).

Wires an Anthropic Claude client to the Phase 3 Controller. The model
never sees which engine is behind a tool call -- it just sees a flat
tool list that changes after every navigate(). `navigate` is always
present; everything else comes from Controller.available_actions.

Uses AsyncAnthropic -- the rest of the stack (Playwright) is async, so a
blocking sync client would stall the event loop mid-task.
"""
from __future__ import annotations

import base64
import os
from typing import Any

from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from controller.controller import Controller
from controller.schema import ActionSchema, NormalizedResult

load_dotenv()

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))

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
    return {
        "name": a.name,
        "description": a.description,
        "input_schema": a.input_schema or {"type": "object", "properties": {}},
    }


def _result_to_content(r: NormalizedResult) -> list[dict[str, Any]]:
    if not r.success:
        return [{"type": "text", "text": f"Error: {r.error}"}]
    if isinstance(r.data, (bytes, bytearray)):
        return [{
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.b64encode(r.data).decode("ascii"),
            },
        }]
    return [{"type": "text", "text": str(r.data)}]


class Agent:
    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set -- copy .env.example to .env and fill it in "
                "(or set LLM_PROVIDER=gemini to use the free Gemini path instead)"
            )
        self.client = AsyncAnthropic(api_key=api_key)
        self.controller = Controller()
        self.messages: list[dict[str, Any]] = []

    def _current_tools(self) -> list[dict[str, Any]]:
        return [NAVIGATE_TOOL] + [_tool_schema(a) for a in self.controller.available_actions]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[NormalizedResult, str]:
        if name == "navigate":
            return await self.controller.navigate(args["url"]), "playwright"
        r = await self.controller.execute(name, args)
        return r, r.engine

    async def run_task(self, instruction: str) -> str:
        self.messages.append({"role": "user", "content": instruction})

        for step in range(MAX_STEPS):
            response = await self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=self._current_tools(),
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                return "\n".join(b.text for b in response.content if b.type == "text")

            results = []
            for b in tool_uses:
                result, engine = await self._dispatch(b.name, b.input)
                # Per-step engine indicator -- a stated live-demo requirement.
                print(f"  [step {step + 1}] engine={engine:<10} tool={b.name}({b.input}) -> success={result.success}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": _result_to_content(result),
                    "is_error": not result.success,
                })
            self.messages.append({"role": "user", "content": results})

        return "(stopped: hit the max step limit -- see AGENT_MAX_STEPS)"

    async def close(self) -> None:
        await self.controller.close()
