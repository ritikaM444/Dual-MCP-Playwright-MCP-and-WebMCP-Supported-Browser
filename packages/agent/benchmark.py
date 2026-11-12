"""
Parameter 3: the matched-pair Engine 1 vs Engine 2 benchmark.

Runs the SAME task, against the SAME page, with the SAME planner model
and prompt -- varying only which engine executes it. That isolation is
the whole point: any difference in tokens, latency or success is
attributable to the interaction mode, not to a change of model or task.

HOW ENGINE FORCING WORKS
The controller normally picks the engine from its capability probe. For
the benchmark we need to override that, so ForcedController subclasses
Controller and pins the engine after every navigation. Nothing in the
existing controller package is modified -- this is a pure addition.

WHY THE CORPUS LOOKS LIKE THIS (two deliberate exclusions)

1. No write tasks. The original demo apps declared tools but rendered no
   form controls, so forcing Engine 2 onto a write task would have failed
   for lack of a DOM affordance -- measuring markup, not the engine. The
   Agent Street redesign gives every shop real controls, so matched write
   tasks are now possible; they are left as future work so this corpus
   stays comparable with the earlier runs.

2. No task whose answer only one engine can reach. "What does the running
   shoe cost?" is answerable by Engine 2 (the price is rendered) but NOT
   by Engine 1 on that page, because shopping-cart declares view-cart and
   never exposes the catalogue. Including it would penalise Engine 1 for
   the page author's choice of tools.

Both exclusions are findings in their own right and belong in the testing
report: a native-tool agent is bounded by what the page chose to declare,
while a DOM agent is bounded by what the page chose to render. Every task
retained below is answerable by BOTH engines, so the comparison measures
the interaction mode and nothing else.

USAGE
    python -m agent.benchmark                        # all tasks, 3 reps, gemini
    python -m agent.benchmark --reps 5
    python -m agent.benchmark --tasks big-garden,big-toys --reps 3
    python -m agent.benchmark --summary              # reprint the table
    python -m agent.benchmark --summary --file benchmark_v1.jsonl
    python -m agent.benchmark --ping                 # one tiny call: is the provider answering?
    python -m agent.benchmark --file benchmark_street.jsonl            # write to a separate file
    python -m agent.benchmark --file benchmark_street.jsonl --resume   # carry on after a stop
    (a bare file name means packages/agent/logs/<name>)

STOPPING AND RESUMING
    Every finished cell is saved the moment it finishes, so stopping a run
    (Ctrl+C, a closed terminal, a used-up quota) loses at most the cell in
    progress. --resume skips cells already in the file for the same model.
    Provider problems -- a used-up quota, a timeout, a server error -- are
    not the engine's fault: they are never counted as engine failures. A
    used-up quota stops the run with a message; other provider errors are
    saved with "infra": true and left out of the table.

WHAT IS MEASURED, AND WHY
    action ms  -- time inside the engine's actions (WebMCP tool call, or DOM
                  read). This is the engine latency metric. The browser is
                  launched before timing starts, so startup is excluded.
    nav ms     -- page loads. Same machinery on both arms (Playwright
                  navigate + capability probe), reported for completeness.
    obs chars  -- size of what the engine returns for the model to read. A
                  model-independent proxy for token cost.
    tokens     -- provider-reported total tokens for the task (input +
                  output + thinking), where the provider reports usage.
    success    -- final answer contains the expected value (formatting such
                  as "82,000" vs "82000" is normalised away).
    wall s     -- whole task. Dominated by LLM API latency; NOT used to
                  compare engines.

PLANNER MUST BE FIXED
    Every cell must use one fixed model. The benchmark's provider is set by
    --provider (default gemini) and deliberately ignores LLM_PROVIDER in
    .env, so the app can use OmniRoute day to day without affecting the
    experiment. OmniRoute is refused when OPENAI_MODEL is "auto": auto-
    routing may switch models between cells and confound the comparison.

QUOTA NOTE
    Each cell costs roughly 2-4 model requests (a lost Engine 2 run on the
    big catalogue can cost 10+). Check your provider's daily
    limit against (tasks x 2 x reps x ~3) before a large run.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from controller.controller import Controller
from controller.router import PLAYWRIGHT_ACTIONS
from controller.schema import ActionSchema

load_dotenv()

BENCH_LOG = Path(__file__).parent / "logs" / "benchmark.jsonl"
RUNS_LOG = Path(__file__).parent / "logs" / "runs.jsonl"
DEMO_BASE = os.environ.get("DEMO_BASE_URL", "http://localhost:4173")

# Characters of the final answer saved per row (rows saved before Nov 2026
# kept 300). Used to re-score saved rows when the success rule changes.
ANSWER_KEEP = 1000

# A whole cell may not take longer than this. The longest real cell so far
# (a lost Engine 2 run on the big catalogue, 13 steps) took ~112 s.
CELL_TIMEOUT_S = float(os.environ.get("BENCH_CELL_TIMEOUT", "420"))

_QUOTA_MARKERS = ("429", "resource_exhausted", "quota", "rate limit", "ratelimit", "too many requests")
_INFRA_MARKERS = _QUOTA_MARKERS + (
    "timeout", "timed out", "503", "500 ", "502", "504", "unavailable", "overloaded",
    "connecterror", "connection", "apiconnectionerror", "internalservererror", "servererror",
)


class QuotaExhausted(RuntimeError):
    """The provider says no more requests for now. Stops the run."""


def _is_quota(err: Optional[str]) -> bool:
    return bool(err) and any(m in err.lower() for m in _QUOTA_MARKERS)


def _is_infra(err: Optional[str]) -> bool:
    """A provider/network problem, not something the engine did."""
    return bool(err) and any(m in err.lower() for m in _INFRA_MARKERS)


# --------------------------------------------------------------------------
# Task corpus -- read-only, so both engines can genuinely attempt each one.
# `check` is a lowercase substring the final answer must contain for the run
# to count as a success. Keep these tolerant: the model phrases answers
# differently each time, and we are measuring the engine, not the prose.
# --------------------------------------------------------------------------
TASKS: list[dict[str, str]] = [
    {
        "id": "dashboard-revenue",
        "page": "dashboard",
        "instruction": "go to {base}/dashboard/ and tell me the current value of the revenue metric",
        "check": "82000",
    },
    {
        "id": "dashboard-signups",
        "page": "dashboard",
        "instruction": "go to {base}/dashboard/ and tell me how many signups there are",
        "check": "342",
    },
    {
        "id": "products-electronics",
        "page": "product-search",
        "instruction": "go to {base}/product-search/ and tell me the name of the most expensive electronics product",
        "check": "keyboard",
    },
    {
        "id": "directory-cafes",
        "page": "directory-search",
        "instruction": "go to {base}/directory-search/ and tell me how many cafes are listed",
        "check": "2|two",
    },
    {
        "id": "products-cheapest",
        "page": "product-search",
        "instruction": "go to {base}/product-search/ and tell me which product is the cheapest",
        "check": "water bottle",
    },
    {
        "id": "booking-slots",
        "page": "booking",
        "instruction": "go to {base}/booking/ and tell me how many time slots are shown on the page",
        "check": "5|five",
    },
    # ---- Scaling tasks: big-catalog (300 products, ~9,000 rendered chars) ----
    # The small pages above are ~300 chars, so reading the whole DOM costs
    # about as much as a tool call and the engines cannot be told apart on
    # cost. These two tasks test what happens when the page is large.
    {
        # Within Engine 2's 8,000-char read budget: all 50 garden items are
        # visible. A pure cost test -- Engine 2 must read ~8k chars and
        # compare 50 prices itself; Engine 1 can have the page sort for it.
        "id": "big-garden-cheapest",
        "page": "big-catalog",
        "instruction": "go to {base}/big-catalog/ and tell me the name of the cheapest product in the garden category",
        "check": ["rake", "1125"],   # name + number; "Vintage Rake (ID 1125)" names the right product
    },
    {
        # TRUNCATION PROBE -- chosen deliberately, and labelled as such. The
        # answer sits at char ~8,878, past extract_text's 8,000-char cap, so
        # an unscoped DOM read sees only 16 of the 50 toys and is not told
        # it was cut off. Engine 2 can still succeed if the model scopes its
        # read with a CSS selector (e.g. #cat-toys). Report this task
        # separately from the matched corpus; it measures a failure mode,
        # not average performance.
        "id": "big-toys-priciest",
        "page": "big-catalog",
        "instruction": "go to {base}/big-catalog/ and tell me the name of the most expensive product in the toys category",
        "check": ["kite", "1297"],
    },
]


class ForcedController(Controller):
    """Controller with the engine pinned, for the matched-pair arms.

    force="webmcp"     -> keep whatever the probe found (demo pages expose
                          WebMCP, so this is the native-tool arm)
    force="playwright" -> ignore the page's tool registry entirely and
                          expose only the generic browser actions
    """

    def __init__(self, force: Optional[str] = None) -> None:
        super().__init__()
        self.force = force
        # Engine-side instrumentation. Wall-clock time for a whole task is
        # dominated by LLM API latency (and rate-limit backoff), which has
        # nothing to do with the engine. These isolate the engine's own cost.
        #   nav_seconds    -- page loads. Identical machinery on both arms
        #                     (Playwright navigate + capability probe), so it
        #                     is reported but is NOT the engine comparison.
        #   action_seconds -- the tool calls / DOM reads that actually differ
        #                     between engines. This is the latency metric.
        self.nav_seconds = 0.0
        self.action_seconds = 0.0
        self.obs_chars = 0          # size of what the engine hands back to the model

    async def warm(self) -> None:
        """Launch the browser before timing starts.

        Without this, the first navigate of every cell includes a full
        Chromium launch (~1.5 s, ~20 s on a cold first launch), which swamps
        every real engine difference.
        """
        await self._session.get_page()

    @property
    def available_actions(self) -> list[ActionSchema]:
        if self.force == "playwright":
            return PLAYWRIGHT_ACTIONS
        return super().available_actions

    async def navigate(self, url: str):
        t0 = time.monotonic()
        result = await super().navigate(url)
        if self.force == "playwright":
            # Pin the routing decision too -- execute() dispatches on this.
            self.state.current_engine = "playwright"
        self.nav_seconds += time.monotonic() - t0
        return result

    async def execute(self, name: str, args: Optional[dict[str, Any]] = None):
        t0 = time.monotonic()
        result = await super().execute(name, args)
        self.action_seconds += time.monotonic() - t0
        # Observation size is a model-independent proxy for token cost: it is
        # exactly what this engine forces the model to read. Screenshots are
        # excluded (bytes, and not used by any benchmark task).
        if result.success and not isinstance(result.data, (bytes, bytearray)):
            data = result.data
            self.obs_chars += len(data if isinstance(data, str) else json.dumps(data))
        return result


def _normalise(s: str) -> str:
    """Make the success check tolerant of formatting the engine didn't cause.

    The model may write 82000 as "82,000", "₹82,000" or "Rs. 82000". Those
    are all correct answers; failing them would measure prose, not engines.
    """
    s = (s or "").lower()
    return re.sub(r"[,\u20b9]", "", s)


def _runs_log_lines() -> int:
    try:
        return len(RUNS_LOG.read_text(encoding="utf-8").strip().splitlines())
    except OSError:
        return 0


def _token_found(token: str, text: str) -> bool:
    """One check token. 'a|b' = either. A number must stand alone, so a
    check for 2 is not passed by '2026' or 'localhost:4173/...2'."""
    for alt in token.split("|"):
        alt = _normalise(alt)
        if alt.isdigit():
            if re.search(rf"(?<![\d.]){alt}(?![\d])", text):
                return True
        elif alt in text:
            return True
    return False


def _passes(check: Any, answer: str) -> bool:
    """Success rule, identical for both engines. `check` is a token or a list
    of tokens that must ALL appear in the final answer."""
    text = _normalise(answer)
    tokens = check if isinstance(check, list) else [check]
    return bool(text) and all(_token_found(t, text) for t in tokens)


def _last_run_tokens(lines_before: Optional[int] = None) -> Optional[int]:
    """Total tokens for the run that just finished.

    The agent's RunLogger appends one row to runs.jsonl as run_task() exits,
    so after a sequential run the last line is this run. Returns None if the
    provider reported no usage (some SDK versions don't expose it).
    """
    if not RUNS_LOG.exists():
        return None
    if lines_before is not None and _runs_log_lines() <= lines_before:
        return None   # this cell logged nothing; don't borrow the previous cell's count
    try:
        last = RUNS_LOG.read_text(encoding="utf-8").strip().splitlines()[-1]
        n = json.loads(last).get("total_tokens")
        return n if n else None
    except (IndexError, json.JSONDecodeError, OSError):
        return None


def _load_agent_class(provider: str):
    """Agent class for the benchmark's provider.

    Deliberately NOT read from LLM_PROVIDER: your .env can point the app at
    OmniRoute for everyday use while the benchmark stays on one fixed model.
    """
    if provider == "anthropic":
        from .agent import Agent, MODEL
    elif provider in {"omniroute", "openai"}:
        from .agent_openai import Agent, MODEL
    else:
        from .agent_gemini import Agent, MODEL
    return Agent, MODEL


async def run_one(task: dict[str, str], engine: str, rep: int, provider: str,
                  out: Path = BENCH_LOG) -> dict[str, Any]:
    """One cell of the matched-pair design: one task, one engine, one repetition."""
    Agent, model = _load_agent_class(provider)
    instruction = task["instruction"].format(base=DEMO_BASE)

    engine_steps: list[str] = []

    async def on_step(ev: dict[str, Any]) -> None:
        engine_steps.append(ev["engine"])

    agent = Agent(on_step=on_step)
    # Swap in the forced controller before the agent touches the browser.
    await agent.controller.close()
    agent.controller = ForcedController(force=engine)
    await agent.controller.warm()

    runs_before = _runs_log_lines()
    start = time.monotonic()
    answer, error = "", None
    try:
        answer = await asyncio.wait_for(agent.run_task(instruction), CELL_TIMEOUT_S)
    except asyncio.TimeoutError:
        error = f"CellTimeout: no answer within {CELL_TIMEOUT_S:.0f} s"
    except Exception as exc:  # a failed cell is data, not a crash
        error = f"{type(exc).__name__}: {exc}"
    seconds = round(time.monotonic() - start, 2)

    ctl = agent.controller
    nav_seconds = round(ctl.nav_seconds, 3)
    action_seconds = round(ctl.action_seconds, 3)
    obs_chars = ctl.obs_chars
    tokens = _last_run_tokens(runs_before)

    try:
        await agent.close()
    except Exception:
        pass

    if _is_quota(error):
        # Not data about the engine. Don't save it; stop the run.
        raise QuotaExhausted(error)

    ok = error is None and _passes(task["check"], answer)

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task["id"],
        "page": task["page"],
        "forced_engine": engine,
        "rep": rep,
        "ok": ok,
        "seconds": seconds,                # wall clock, includes LLM latency
        "nav_seconds": nav_seconds,        # page loads (same on both arms)
        "action_seconds": action_seconds,  # engine actions only -- THE latency metric
        "obs_chars": obs_chars,            # what the engine fed the model
        "tokens": tokens,                  # provider-reported, may be None
        "steps": len(engine_steps),
        "engine_steps": dict(
            (e, engine_steps.count(e)) for e in set(engine_steps)
        ),
        "provider": provider,
        "model": model,
        "answer": (answer or "")[:ANSWER_KEEP],
        "error": error,
    }

    # Validity check promised in the Review 1 design: a forced-Engine-2 run
    # that silently used webmcp would contaminate the cell, so record it.
    if engine == "playwright" and "webmcp" in row["engine_steps"]:
        row["contaminated"] = True
    # Provider trouble (timeout, 5xx) is kept for the record but left out
    # of the engine comparison. A cell-level timeout is NOT infra: the
    # model was answering, the task just never finished.
    if error and not error.startswith("CellTimeout") and _is_infra(error):
        row["infra"] = True

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def _mean(xs: list) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def _fmt(x: Optional[float], spec: str) -> str:
    """Format a number, or a right-aligned '-' of the same width if missing."""
    if x is not None:
        return format(x, spec)
    width = int(re.match(r"[<>^]?(\d*)", spec).group(1) or 0)
    return "-".rjust(width)


def _ms(rs: list[dict], key: str) -> Optional[float]:
    v = _mean([r.get(key) for r in rs])
    return v * 1000 if v is not None else None


def summarise(path: Path = BENCH_LOG) -> None:
    if not path.exists():
        print("No benchmark data yet.")
        return
    all_rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    rows = [r for r in all_rows if not r.get("infra")]
    # Score every saved row with the CURRENT success rule, so all files are
    # judged the same way (the rule was tightened in Nov 2026: whole numbers
    # only, and name + number for the big-catalogue items). Report changes.
    checks = {t["id"]: t["check"] for t in TASKS}
    rescored = 0
    for r in rows:
        if r["task"] in checks and not r.get("error"):
            ans = r.get("answer", "")
            new_ok = _passes(checks[r["task"]], ans)
            # A saved answer may be cut short (300 chars in older rows). If the
            # check fails on the cut-short text we cannot tell what the full
            # answer said, so the result from when it was saved stands.
            if not new_ok and len(ans) >= 300:
                continue
            if new_ok != r["ok"]:
                rescored += 1
                r["ok_as_saved"] = r["ok"]
                r["ok"] = new_ok
    infra = len(all_rows) - len(rows)
    if not rows:
        print("No benchmark data yet." + (f" ({infra} provider-error rows skipped)" if infra else ""))
        return

    by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by[(r["task"], r["forced_engine"])].append(r)

    W = 102
    print("\n" + "=" * W)
    print("ENGINE 1 (WebMCP) vs ENGINE 2 (Playwright) - matched-pair results")
    models = sorted({str(r.get("model", "?")) for r in rows})
    print(f"planner model(s): {', '.join(models)}")
    print("=" * W)
    print(f"{'task':<22}{'engine':<16}{'runs':>5}{'success':>9}"
          f"{'action ms':>11}{'nav ms':>9}{'obs chars':>11}{'tokens':>9}{'steps':>7}{'wall s':>8}")
    print("-" * W)
    # Engine 1 before Engine 2 within each task, rather than alphabetically.
    for (task, engine) in sorted(by, key=lambda k: (k[0], k[1] != "webmcp")):
        rs = by[(task, engine)]
        succ = 100 * sum(1 for r in rs if r["ok"]) / len(rs)
        label = "1 (webmcp)" if engine == "webmcp" else "2 (playwright)"
        print(f"{task:<22}{label:<16}{len(rs):>5}{succ:>8.0f}%"
              f"{_fmt(_ms(rs, 'action_seconds'), '>11.0f')}"
              f"{_fmt(_ms(rs, 'nav_seconds'), '>9.0f')}"
              f"{_fmt(_mean([r.get('obs_chars') for r in rs]), '>11.0f')}"
              f"{_fmt(_mean([r.get('tokens') for r in rs]), '>9.0f')}"
              f"{statistics.mean(r['steps'] for r in rs):>7.1f}"
              f"{statistics.mean(r['seconds'] for r in rs):>8.1f}")

    print("-" * W)
    for engine in ("webmcp", "playwright"):
        rs = [r for r in rows if r["forced_engine"] == engine]
        if not rs:
            continue
        succ = 100 * sum(1 for r in rs if r["ok"]) / len(rs)
        label = "Engine 1 (WebMCP)" if engine == "webmcp" else "Engine 2 (Playwright)"
        print(f"{label:<24} runs={len(rs):<4} success={succ:.0f}%  "
              f"action={_fmt(_ms(rs, 'action_seconds'), '.0f')}ms  "
              f"obs={_fmt(_mean([r.get('obs_chars') for r in rs]), '.0f')} chars  "
              f"tokens={_fmt(_mean([r.get('tokens') for r in rs]), '.0f')}  "
              f"steps={statistics.mean(r['steps'] for r in rs):.1f}")

    print("\naction ms  = time inside the engine's actions (tool call / DOM read) - the engine latency metric")
    print("nav ms     = page loads; identical machinery on both arms, shown for completeness")
    print("obs chars  = size of what the engine returned for the model to read")
    print("tokens     = provider-reported total tokens for the whole task")
    print("wall s     = whole task, dominated by LLM latency; NOT an engine metric")

    if len(models) > 1:
        print(f"\n!! more than one planner model in this file ({', '.join(models)}) - "
              "the comparison is only valid within one model")
    if rescored:
        print(f"\nnote: {rescored} row(s) scored differently from when they were saved, "
              "under the current success rule:")
        for r in rows:
            if "ok_as_saved" in r:
                print(f"  {r['task']:<22}{r['forced_engine']:<12}"
                      f"{'wrong -> right' if r['ok'] else 'right -> wrong'}: {r.get('answer', '')[:70]!r}")
    if infra:
        print(f"\nnote: {infra} cell(s) hit a provider error (timeout / server error) and are "
              "left out - not engine failures")
    if any(r.get("tokens") is None for r in rows):
        print("\nnote: some rows have no token count (provider did not report usage)")
    bad = [r for r in rows if r.get("contaminated")]
    if bad:
        print(f"\n!! {len(bad)} forced-Engine-2 run(s) used webmcp steps - exclude from claims")
    fails = [r for r in rows if not r["ok"]]
    if fails:
        print(f"\nFailures ({len(fails)}) - for the failure-mode catalogue:")
        for r in fails[-8:]:
            reason = r["error"] or f"wrong answer: {r.get('answer', '')[:70]!r}"
            print(f"  {r['task']:<22}{r['forced_engine']:<12}{reason}")
    print()


def _done_cells(out: Path, model: str) -> set[tuple[str, str, int]]:
    """Cells already saved in `out` for this model (provider-error rows don't count)."""
    if not out.exists():
        return set()
    done = set()
    for line in out.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("model") == model and not r.get("infra"):
            done.add((r["task"], r["forced_engine"], r["rep"]))
    return done


async def main_async(reps: int, only: Optional[list[str]], pause: float, provider: str,
                     out: Path = BENCH_LOG, resume: bool = False) -> None:
    tasks = [t for t in TASKS if only is None or t["id"] in only]
    if not tasks:
        print(f"No task matching {only!r}. Available: {[t['id'] for t in TASKS]}")
        return

    # Fail fast if the demo pages aren't being served: otherwise every cell
    # "fails" at navigate and the run measures nothing (seen Nov 2026).
    import urllib.request
    try:
        urllib.request.urlopen(DEMO_BASE + "/", timeout=5).read(1)
    except Exception as exc:
        print(f"The demo server is not answering at {DEMO_BASE} ({type(exc).__name__}).\n"
              "Start it in its own terminal, then run this command again:\n"
              "    python packages/engine_webmcp/demo_pages/server.py\n"
              f"Check by opening {DEMO_BASE}/ in your browser.")
        return

    total = len(tasks) * 2 * reps
    _, model = _load_agent_class(provider)
    done = _done_cells(out, model) if resume else set()
    print(f"Running {total} cells ({len(tasks)} tasks x 2 engines x {reps} reps) "
          f"on provider={provider}, model={model}")
    print(f"Saving to {out}")
    if done:
        print(f"--resume: {len(done)} cell(s) already saved for this model will be skipped")
    elif not resume and out.exists() and out.stat().st_size:
        print(f"note: {out.name} already has rows; new rows are added to them. "
              "Use --file for a fresh file.")
    print("Demo server must be running: python packages/engine_webmcp/demo_pages/server.py\n")

    n = 0
    # Interleave engines per repetition so API or network drift cannot
    # alias onto the engine variable (Review 1 experimental design).
    for rep in range(1, reps + 1):
        for task in tasks:
            for engine in ("webmcp", "playwright"):
                n += 1
                if (task["id"], engine, rep) in done:
                    continue
                print(f"[{n}/{total}] {task['id']} on {engine} (rep {rep})", flush=True)
                try:
                    row = await run_one(task, engine, rep, provider, out)
                except QuotaExhausted as exc:
                    print(f"\nSTOPPED: the provider refused the request -- usually the daily or "
                          f"per-minute limit.\n  {str(exc)[:200]}\n"
                          f"Nothing from this cell was saved. Everything before it is safe in {out}.\n"
                          "When the limit resets, run the SAME command again with --resume.\n")
                    summarise(out)
                    return
                status = "ok" if row["ok"] else f"FAIL ({row['error'] or 'wrong answer'})"
                tok = row["tokens"] if row["tokens"] is not None else "-"
                if row.get("infra"):
                    status = f"PROVIDER ERROR, not counted ({row['error'][:80]})"
                print(f"        {status}  action={row['action_seconds']*1000:.0f}ms  "
                      f"obs={row['obs_chars']}  tokens={tok}  wall={row['seconds']}s")
                if pause and n < total:
                    # Stay under the provider's per-minute limit, so a cell's
                    # wall time isn't inflated by rate-limit backoff.
                    await asyncio.sleep(pause)
    summarise(out)


async def ping(provider: str) -> None:
    """One tiny request, with a short timeout, to see whether the provider answers."""
    _, model = _load_agent_class(provider)
    print(f"Pinging provider={provider} model={model} (30 s limit)...", flush=True)
    t0 = time.monotonic()
    try:
        if provider in {"omniroute", "openai"}:
            from openai import AsyncOpenAI
            from .agent_openai import BASE_URL, API_KEY
            client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=30, max_retries=0)
            r = await client.chat.completions.create(
                model=model, max_tokens=5,
                messages=[{"role": "user", "content": "Reply with the word OK."}])
            text = r.choices[0].message.content
        elif provider == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(timeout=30, max_retries=0)
            r = await client.messages.create(
                model=model, max_tokens=5,
                messages=[{"role": "user", "content": "Reply with the word OK."}])
            text = r.content[0].text
        else:
            import threading
            from google import genai
            from google.genai import types
            # No silent retries: a refusal (e.g. 429, quota used up) must be
            # shown as-is, not hidden behind ~30 s of quiet backoff.
            client = genai.Client(
                api_key=os.environ.get("GEMINI_API_KEY"),
                http_options=types.HttpOptions(
                    timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
            box: dict[str, Any] = {}

            def call() -> None:
                try:
                    box["r"] = client.interactions.create(model=model, input="Reply with the word OK.")
                except Exception as e:      # handed back to the main thread
                    box["e"] = e
            # Daemon thread: if Google never answers, the program can still exit.
            th = threading.Thread(target=call, daemon=True)
            th.start()
            await asyncio.to_thread(th.join, 35)
            if "e" in box:
                raise box["e"]
            if "r" not in box:
                raise TimeoutError("no answer from Google within 35 s")
            text = box["r"].output_text
        print(f"OK in {time.monotonic() - t0:.1f} s. Reply: {str(text).strip()[:60]!r}")
        print("The provider is answering. If the benchmark still stalls, the problem is elsewhere.")
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        print(f"FAILED after {time.monotonic() - t0:.1f} s\n  {err[:400]}")
        if _is_quota(err):
            print("=> Limit reached. Wait for it to reset, or use another provider/model.")
        elif _is_infra(err) or isinstance(exc, asyncio.TimeoutError):
            print("=> The provider did not answer in time / had a server error. Try again in a few minutes.")
        else:
            print("=> Not a limit problem. Check the API key and model name in .env.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Engine 1 vs Engine 2 matched-pair benchmark")
    ap.add_argument("--reps", type=int, default=3, help="repetitions per task per engine")
    ap.add_argument("--tasks", type=str, default=None,
                    help="comma-separated task ids to run (default: all)")
    ap.add_argument("--pause", type=float, default=10.0,
                    help="seconds to wait between cells, to stay under rate limits (default 10)")
    ap.add_argument("--provider", type=str, default="gemini",
                    choices=["gemini", "omniroute", "openai", "anthropic"],
                    help="planner provider for the benchmark (default gemini; "
                         "independent of LLM_PROVIDER in .env)")
    ap.add_argument("--summary", action="store_true", help="print the table from existing data and exit")
    ap.add_argument("--file", type=str, default=None,
                    help="results file to write to (and read with --summary). A bare "
                         "name goes in packages/agent/logs/. Default benchmark.jsonl")
    ap.add_argument("--resume", action="store_true",
                    help="skip cells already saved in the results file for the same model")
    ap.add_argument("--ping", action="store_true",
                    help="send one tiny request to the provider and report what happens")
    args = ap.parse_args()

    out = BENCH_LOG
    if args.file:
        out = Path(args.file)
        if out.parent == Path("."):        # bare name -> the logs folder
            out = BENCH_LOG.parent / out
    if args.summary:
        summarise(out)
        return
    if args.ping:
        asyncio.run(ping(args.provider))
        return

    if args.provider in {"omniroute", "openai"}:
        model = os.environ.get("OPENAI_MODEL", "auto")
        if model == "auto" or model.startswith("auto/"):
            print("Refusing to benchmark through OmniRoute with OPENAI_MODEL="
                  f"{model!r}.\nAuto-routing may switch models between cells, which would "
                  "confound the engine comparison.\nEither use --provider gemini (default), "
                  "or set OPENAI_MODEL to one specific model id.")
            return

    only = [s.strip() for s in args.tasks.split(",")] if args.tasks else None
    try:
        asyncio.run(main_async(args.reps, only, args.pause, args.provider, out, args.resume))
    except KeyboardInterrupt:
        print(f"\nStopped. Finished cells are saved in {out}; "
              "run the same command with --resume to carry on.")


if __name__ == "__main__":
    main()
