# MCP-Based Autonomous Browser Agent

A hybrid **dual-engine** browser agent. You type a task in plain English; the
agent drives a real browser to complete it, choosing at runtime between two
different ways of controlling each page.



---

## The idea

Today's browser agents read a page's pixels or raw HTML and *guess* which
element to click. That works everywhere, but it's slow, expensive in tokens,
and breaks when a site changes its layout.

**WebMCP** — a W3C Web Machine Learning Community Group draft from Google and
Microsoft — proposes the opposite: a page *declares* its own capabilities as
callable tools, so an agent invokes a function instead of inferring a click.
Precise and cheap, but almost no live site implements it yet.

This project resolves that tension at runtime:

| | Engine 1 — WebMCP | Engine 2 — Playwright |
|---|---|---|
| How it acts | Calls the page's own declared tools | DOM automation (click / type / extract) |
| Speed & cost | Fast, few tokens, structured JSON | Slower, token-heavy |
| Works on | Pages that expose a tool registry | Any website |

An **Agent Controller Layer** probes every page as it loads, picks the right
engine, and normalises both engines' very different outputs into one shape —
so the planning model never knows or cares which one ran.

## Architecture

```
You  →  Web UI / CLI
            ↓
        LLM planner  (Gemini · OmniRoute · Claude — interchangeable)
            ↓
        Agent Controller Layer   ← capability probe on every navigation
            ↓                        router · normaliser · task state
     ┌──────┴──────┐
 Engine 1        Engine 2
 WebMCP          Playwright MCP
     └──────┬──────┘
        One shared Chromium session
```

Both engines act on the **same live browser session**, which is what makes a
mid-task engine switch coherent — and what makes the Engine 1 vs Engine 2
comparison fair.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[agent]"
playwright install chromium

cp .env.example .env               # then add your API key
```

Get a free Gemini key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

Run it — three terminals, each with the venv activated:

```bash
python packages/engine_webmcp/demo_pages/server.py   # 1: WebMCP demo apps
python -m webapp.server                              # 2: UI on localhost:8000
python -m agent.cli                                  # 3: (optional) terminal chat
```

Set `HEADLESS=false` and `SLOW_MO=500` in `.env` to watch Chromium work.

### Try it

```
go to http://localhost:4173/shopping-cart/ and add 2 running shoes, then check out
```
```
go to news.ycombinator.com and tell me the top story
```

The first runs on Engine 1, the second on Engine 2 — the UI labels every step.

## Choosing an LLM provider

One line in `.env` (`LLM_PROVIDER=`):

- **`gemini`** — free key, no card. Note the free tier gives ~500 requests/day
  on Flash-Lite but only ~20 on full Flash models.
- **`omniroute`** — routes through a local [OmniRoute](https://github.com/diegosouzapw/OmniRoute)
  gateway that fans out across many free providers and falls back automatically
  when one hits its quota. Best for long demos.
- **`anthropic`** — direct Claude; needs billing.

All three implement the same interface, so switching is one word.

## Project layout

```
packages/
  engine_playwright/   Engine 2 — Playwright actions + MCP server
  engine_webmcp/       Engine 1 — capability probe, native bridge,
                       WebMCP polyfill, 8 demo apps
  controller/          Router, output normaliser, task state
  agent/               Plan/act loop (3 providers), CLI, run logging
  webapp/              Web UI with live per-step engine indicators
```

## Testing

```bash
python -m engine_playwright.test_client   # Engine 2 against real websites
python -m engine_webmcp.test_client       # Engine 1 against all 8 demo apps
python -m controller.test_controller      # engine switching, no LLM involved
python -m agent.analyze_runs              # Engine 1 vs Engine 2 metrics
```

Every task run appends success, latency, token cost and per-engine step
counts to `packages/agent/logs/runs.jsonl`.

## Notes on the WebMCP polyfill

`webmachinelearning/webmcp` is a specification repository — it contains no
runnable JavaScript. `document.modelContext.registerTool()` is fully
specified and the demo apps use it exactly as documented, but **external tool
discovery is explicitly left open** in the spec:

> TODO: Spec and describe the `modelContext.getTools()` and
> `modelContext.executeTool()` APIs.

So `packages/engine_webmcp/polyfill/webmcp-polyfill.js` implements the real,
documented registration API faithfully and adds minimal `getTools()` /
`callTool()` entry points to fill that gap. This is a deliberate, documented
design decision, not an undisclosed shortcut.

That polyfill and the demo apps' inline scripts are the only JavaScript in the
project — unavoidably so, since `document.modelContext` is a browser API. There
is no Node or npm toolchain here; Chromium executes that JS exactly as it would
any website's own scripts. Everything else is Python.

## Known limitations

- Real-world WebMCP adoption is effectively zero, so Engine 1 is exercised
  against self-hosted demo apps. No claim is made about production WebMCP sites.
- Engine 2's reliability depends on target site structure; dynamic or
  bot-protected sites can fail, and those failures are logged rather than hidden.
- Comparative results are currently conditioned on a single planner model.

## Tech stack

Python 3.10+ · Playwright (async) · MCP Python SDK (FastMCP) · FastAPI · OmniRoute
Google Gemini / OpenAI-compatible / Anthropic
