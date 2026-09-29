# LLM Agent + Chat Interface — Phase 4

Wires an LLM to the Phase 3 `Controller`. The model never checks which
engine is active -- it sees `navigate` (always present) plus whatever
`Controller.available_actions` holds, and that list changes after every
navigate.

## Files
- `agent_gemini.py` -- Gemini provider (default). Free key, no card:
  aistudio.google.com/apikey
- `agent.py` -- Anthropic provider. Needs billing at console.anthropic.com.
- `cli.py` -- chat loop; picks provider from `LLM_PROVIDER`.

## Jarvis mode (visible browser)
In `.env`: `HEADLESS=false` and `SLOW_MO=500`. Chromium opens on screen
and pauses between actions so the panel can follow along. Playwright
drives its own bundled Chromium with a separate profile -- it never
touches your installed Chrome/Firefox/Edge.

## Run
1. `cp .env.example .env`, set `GEMINI_API_KEY`.
2. `python packages/engine_webmcp/demo_pages/server.py` in another terminal.
3. `python -m agent.cli`

## How this was checked
No network in the build environment, so nothing ran against a real API.
Both providers were verified with stub packages scripting a realistic
multi-turn tool-use conversation (navigate -> extract_text -> final
answer), run end to end through the real `run_task()` loop, plus a check
that `cli.py` imports the right class per `LLM_PROVIDER`. First genuine
test is `python -m agent.cli` with a real key.

`agent_gemini.py` caveats, written from docs without being runnable here:
only sync client usage was confirmed for the Interactions API, so calls
are wrapped in `asyncio.to_thread()`; and no dedicated system-prompt
parameter was confirmed, so it's prepended to the first instruction.

## Next
Phase 5 -- demo script + per-task/per-engine logging (success, latency,
tokens) for the Parameter 3 comparison. Needs to run over weeks, not once.
