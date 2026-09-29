# MCP-Based Autonomous Browser Agent

Hybrid dual-engine browser agent — WebMCP (Engine 1) + Playwright MCP (Engine 2) —
Vishwakarma University, Dept. of Computer Engineering, Major Project (BTECCE23706).

**Status: Phase 0–4 complete, pure Python.** Phases 0-3 have been run for
real on real hardware and passed (see the controller/engine_webmcp READMEs).
Phase 4 (the LLM agent) is built and checked as far as a sandbox with no
network can check it — see `packages/agent/README.md` for exactly what
that means. Phase 5 (demo script + comparative logging) is next.

This was originally scaffolded in Node/TypeScript, then rewritten to Python
end to end at the user's request — which also resolves a real inconsistency:
the proposal's own Technology Selection table already said "Python" for agent
orchestration.

## The one thing that's still JavaScript, and why it has to be

`packages/engine_webmcp/polyfill/webmcp-polyfill.js` and the two demo pages'
inline `<script>` tags are JavaScript, not Python — and can't become Python.
`document.modelContext` is a *browser* API; it only exists inside a page's own
JS execution context, the same way any website's client-side script does.
This has nothing to do with Node or npm — you will not run `npm`, `node`, or
any JS toolchain anywhere in this project. The browser (Chromium, driven by
Playwright) is what executes that JS, exactly as it would execute a real
site's own scripts. Everything that orchestrates, tests, or drives the
browser — servers, capability checks, the bridge, the demo page's static file
server — is plain Python.

## ⚠️ Built with no network access — read this before you run anything

This repo was written in a sandboxed environment with no access to PyPI,
GitHub, or live websites (`pip install` can't reach the index here). Every
file was hand-written and syntax-checked (`python -m py_compile`, `node
--check` for the one JS file) but **nothing in here has actually been
executed yet.** On your machine (which has real network access):

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[agent]"          # or: pip install -r requirements.txt
playwright install chromium

python -m engine_playwright.test_client      # Phase 1 standalone test, no LLM

# in a second terminal:
python packages/engine_webmcp/demo_pages/server.py
# back in the first terminal:
python -m engine_webmcp.test_client           # Phase 2 standalone test, no LLM
```

Some of the real websites used for testing (see below) may have changed
layout, started blocking headless Chromium, or gone offline since this was
written — that's expected of "test against real sites," not a bug in the
code. If one breaks, swap the selector or the site; the pattern is what
matters.

## Why the MCP Python SDK is pinned to v1 (`mcp>=1.2,<2`)

Same due-diligence problem as WebMCP, on the SDK side this time: the official
`mcp` Python SDK is mid-migration to a v2 that's still beta/RC as of this
writing, tied to a not-yet-finalized 2026-07-28 spec revision — sources
disagree on whether a bare `pip install mcp` currently resolves to v1.x or
2.x. Rather than build Phase 3/4 against a moving target that could still
change API shape before your Nov Review 3, this pins to the well-documented,
stable v1.x line (`FastMCP`, `@mcp.tool()` decorators, `ClientSession` +
`stdio_client`) used throughout `server.py` / `test_client.py`. Re-check this
before Review 2 in case v1 has since gone end-of-life.

## Two things verified before writing Phase 2, worth knowing for the literature survey

1. **`webmachinelearning/webmcp` has no JS polyfill.** It's a spec-text repo
   (98.7% Bikeshed, no runnable JS). `document.modelContext.registerTool()` is
   fully specified and our demo pages use it exactly as documented. But
   **external discovery/invocation is explicitly unspecified** — the explainer
   says outright: *"TODO: Spec and describe the `modelContext.getTools()` and
   `modelContext.executeTool()` APIs."* So `polyfill/webmcp-polyfill.js`
   implements the real, documented `registerTool()` faithfully, and adds
   `getTools()`/`callTool()` ourselves to fill that documented gap — a
   legitimate, citable design decision for Parameter 1 (research gap), not a
   shortcut to gloss over.
2. **MCP SDK versioning is in flux on both sides of the stack** (Python here,
   TypeScript when this was still Node) — see above.

## Structure

```
packages/
  engine_playwright/    Engine 2 -- Playwright actions (actions.py) + MCP server wrapper (server.py)
  engine_webmcp/          Engine 1 -- WebMCP capability check + native bridge + polyfill (JS) + demo pages (HTML/JS)
  controller/              Phase 3 -- router + normalizer + task state + Controller (done)
  agent/                   Phase 4 -- plan/act loop (agent.py) + CLI chat interface (cli.py) (done)
```

Installed as editable Python packages via `pip install -e .` (see
`pyproject.toml`, `[tool.setuptools.packages.find] where = ["packages"]`), so
`engine_playwright`, `engine_webmcp`, `controller`, and `agent` import
directly by name from anywhere in the project — no relative-path hacks needed
once the controller (Phase 3) needs to import both engines.

## Demo site choices for Engine 2 (Phase 1 test + later ESE demo)

Picked specifically to avoid anti-bot/CAPTCHA surprises on demo day:

- `the-internet.herokuapp.com` — a QA-automation *practice* site (built to be
  automated against, so it won't add bot defenses or change structure).
  Login page covers click+type; `/tables` covers structured extraction.
- `news.ycombinator.com` — plain server-rendered HTML, stable markup, good for
  a search+summarize-style task.

Run `python -m engine_playwright.test_client` once and see which of these
still behave; swap out any that don't before you build the demo script around
them (Phase 5).

## Open decision that needs your guide's sign-off before Review 1

The proposal itself flags this: how many self-hosted WebMCP demo pages / task
types count as sufficient for the Engine 1 vs Engine 2 comparison (Parameter 3
research contribution). Two demo pages exist here (`todo-app`, `product-search`)
as a starting point, not a final answer — confirm scope with your guide.

## Reality check on scope

This is a proof-of-concept proving the architecture works — it is not the
Review 2/3 deliverable on its own. The Engine 1 vs Engine 2 comparative
logging (success/failure, latency, token cost — Phase 5) needs to keep
running for weeks across a broad site set, not just during a demo. Start
that logging now that Phase 4 exists, rather than reconstructing the data
later.

## What's next

Phase 5 — demo script + comparative logging: 2-3 task types run back to
back (search+summarize, form fill, multi-page extraction), at least one
that starts on a WebMCP demo page and falls back to Engine 2 mid-task, with
success/failure, latency, and token usage logged per task per engine —
this is the actual Parameter 3 research data, and it needs to keep running
for weeks, not just get generated for a demo. Also a good point to add a
more full-featured WebMCP demo app or two, since Engine 1's data currently
comes from only two fairly trivial pages.
