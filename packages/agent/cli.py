"""
Terminal chat interface. The web UI (python -m webapp.server) is the one
to demo; this stays for quick testing without a browser tab.

LLM_PROVIDER in .env picks the backend:
  omniroute  -- local gateway, auto-falls-back across free providers (no
                rate-limit cliff); needs `omniroute` running separately
  gemini     -- direct Google Gemini (free key, but ~20 req/day on full
                Flash models, ~500 on Flash-Lite)
  anthropic  -- direct Claude (needs billing)

All three share the same interface, so switching is one word in .env.

Set HEADLESS=false and SLOW_MO=500 to watch Chromium work.
Run: python -m agent.cli
"""
from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()

if PROVIDER == "anthropic":
    from .agent import Agent
elif PROVIDER in {"omniroute", "openai"}:
    from .agent_openai import Agent
else:
    from .agent_gemini import Agent


async def main() -> None:
    agent = Agent()
    visible = os.environ.get("HEADLESS", "true").lower() == "false"
    print(f"MCP Browser Agent ({PROVIDER}, {'visible browser' if visible else 'headless'}) "
          "-- type an instruction, or 'quit' to exit.\n")
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
            print(f"\n{await agent.run_task(instruction)}\n")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
