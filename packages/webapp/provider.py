"""Single place that maps LLM_PROVIDER to an Agent class, so cli.py and
the web UI can never drift apart on which providers are supported."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()


def get_agent_class():
    if PROVIDER == "anthropic":
        from agent.agent import Agent
    elif PROVIDER in {"omniroute", "openai"}:
        from agent.agent_openai import Agent
    else:
        from agent.agent_gemini import Agent
    return Agent
