# Web UI — the demo interface

`python -m webapp.server` → open http://localhost:8000

Chat box; each step streams back live, colour-coded by engine
(green = webmcp / Engine 1 native tools, blue = playwright / Engine 2
DOM fallback). Pair with `HEADLESS=false` + `SLOW_MO=500` in `.env` so
the examiner sees this panel AND the real Chromium window driving itself.

Needs the demo pages running too:
`python packages/engine_webmcp/demo_pages/server.py`

Verified before delivery by actually starting the server and hitting
`/`, `/api/config` and the `/api/run` SSE stream with a stubbed LLM —
page served, both step events streamed with correct engine labels, final
reply delivered. Not yet run against the real Gemini API or a real
browser; that's your first run.
