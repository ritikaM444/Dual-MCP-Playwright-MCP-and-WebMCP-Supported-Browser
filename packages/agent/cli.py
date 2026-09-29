"""
Phase 4: minimal chat interface. Shows, per step, which engine handled
that step (both Agent classes print an "engine=..." line per tool call).

Picks the provider from LLM_PROVIDER in .env: "gemini" (default, free)
or "anthropic". Both Agents share run_task()/close(), so nothing here
needs to know which is active.

For the visible "watch it work" demo, set HEADLESS=false and SLOW_MO=500
in .env before running.

Run with: python -m agent.cli
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

if PROVIDER == "anthropic":
    from .agent import Agent
else:
    from .agent_gemini import Agent


async def main() -> None:
    agent = Agent()
    visible = os.environ.get("HEADLESS", "true").lower() == "false"
    mode = "visible browser" if visible else "headless"
    print(f"MCP Browser Agent ({PROVIDER}, {mode}) -- type an instruction, or 'quit' to exit.\n")
    try:
        while True:
            try:
                instruction = input("> ").strip()
            except EOFError:
                break
            if not instruction:
                continue
            if instruction.lower() in {"quit", "exit"}:
                break
            reply = await agent.run_task(instruction)
            print(f"\n{reply}\n")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
