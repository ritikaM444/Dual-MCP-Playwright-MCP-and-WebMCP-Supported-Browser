"""
Phase 4, Gemini provider -- same plan/act loop as agent.py, adapted to
Google's Gemini Interactions API. Free key, no card required:
aistudio.google.com/apikey

Kept deliberately parallel to agent.py: same always-available navigate,
same per-step engine print, same Controller underneath. What differs is
the wire format -- Gemini groups a turn's tool calls as `steps` on an
`interaction`, and continues a conversation via previous_interaction_id
rather than a growing messages list.

Two things written from Google's docs without being able to run them:
  1. Only synchronous client usage was confirmed for this endpoint, so
     every call is wrapped in asyncio.to_thread() to stay off the event
     loop Playwright needs, rather than guessing at an async interface.
  2. No dedicated system-prompt parameter was confirmed, so the system
     prompt is prepended to the first instruction. Functionally the same.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any

from google import genai
from dotenv import load_dotenv

from controller.controller import Controller
from controller.schema import ActionSchema, NormalizedResult

load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.7-flash")
MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "15"))

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


class Agent:
    """Same public interface as agent.Agent -- cli.py needn't know which is active."""

    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set -- get a free key at aistudio.google.com/apikey, "
                "copy .env.example to .env, and fill it in"
            )
        self.client = genai.Client(api_key=api_key)
        self.controller = Controller()
        self._last_interaction_id: str | None = None
        self._first_turn = True

    def _current_tools(self) -> list[dict[str, Any]]:
        return [NAVIGATE_TOOL] + [_tool_schema(a) for a in self.controller.available_actions]

    async def _dispatch(self, name: str, args: dict[str, Any]) -> tuple[NormalizedResult, str]:
        if name == "navigate":
            return await self.controller.navigate(args["url"]), "playwright"
        r = await self.controller.execute(name, args)
        return r, r.engine

    async def _create(self, **kwargs: Any) -> Any:
        return await asyncio.to_thread(self.client.interactions.create, **kwargs)

    async def run_task(self, instruction: str) -> str:
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

            calls = [s for s in interaction.steps if s.type == "function_call"]
            if not calls:
                return interaction.output_text

            results = []
            for call in calls:
                result, engine = await self._dispatch(call.name, call.arguments)
                print(f"  [step {step_num + 1}] engine={engine:<10} tool={call.name}({call.arguments}) -> success={result.success}")
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
