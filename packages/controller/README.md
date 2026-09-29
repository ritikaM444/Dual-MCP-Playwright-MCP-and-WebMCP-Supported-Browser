# Agent Controller Layer — Phase 3 (done)

Your project's actual contribution (BUILD_STEPS.md calls this out explicitly:
"the piece your project actually contributes... it only makes sense once
Engine 1 and Engine 2 exist independently and you've seen them work
standalone"). No reference implementation exists for this part — budget real
time to read and understand it, since it's what you defend individually at
viva.

## Files

- `schema.py` — `NormalizedResult`, `ActionSchema`, `TaskState`. (Named
  `schema.py`, not `types.py` — a module literally named `types.py` shadows
  Python's own stdlib `types` module the moment its directory lands on
  `sys.path`, which breaks unrelated imports elsewhere with a confusing
  circular-import error. Caught this the hard way while testing.)
- `router.py` — `select_engine(page)`: runs the Phase 2 capability check and
  returns which engine governs the current page plus its action menu.
- `normalizer.py` — `normalize_webmcp()` / `normalize_playwright()`: map each
  engine's native return shape into one `NormalizedResult`.
- `controller.py` — the `Controller` class: owns one shared browser session,
  exposes `navigate(url)` and `execute(name, args)` as the only two entry
  points Phase 4's agent will ever call.
- `test_controller.py` — Phase 3 standalone checkpoint test (no LLM):
  scripts a real multi-engine sequence (WebMCP demo page → real legacy site)
  and asserts the engine switch and output shape are both correct.

## Why Engine 2 got a small refactor

`engine_playwright/actions.py` is new — the actual click/type/extract/
screenshot logic, pulled out of `server.py` into plain functions. The
controller needs to call these directly against its *own* shared Playwright
page; spawning a second MCP-over-stdio subprocess just to click a button on
the same browser tab it already has open would mean a second, disconnected
browser session — exactly the "controller loses context on an engine switch"
failure mode BUILD_STEPS.md warns about. `server.py` now just wraps
`actions.py` as MCP tools for the Phase 1 standalone test; behavior is
unchanged, so your already-passing Phase 1/2 test runs remain valid.

## How this was checked before delivery

The build sandbox still has no network, so nothing here could run against a
real browser. Went one step further than Phase 1/2 though: wrote minimal
stub `mcp`/`playwright` packages and actually *imported and ran* every
module — including driving a full `Controller.navigate()` → `execute()`
sequence through both the WebMCP branch and the Playwright branch with a
mocked page, asserting on the real return values. This catches wiring bugs
(wrong import paths, decorator misuse, a real `types.py` stdlib collision)
that syntax-checking alone would miss — but it's still a mock, not Playwright
actually driving Chromium. Run `python -m controller.test_controller` for
the first real execution (needs the Phase 2 demo server running in another
terminal).

## What's next

Phase 4 — LLM agent + chat interface: wire an MCP client (Anthropic Python
SDK) to `Controller.available_actions` / `Controller.execute()`, implement
the plan/act loop, and a minimal interface showing which engine handled each
step.
