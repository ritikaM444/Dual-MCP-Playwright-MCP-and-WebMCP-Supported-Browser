"""
Real-website tests for the full agent (planner + controller + both engines).

The benchmark measures Engine 1 vs Engine 2 on our own demo pages. This
script answers a different question from the Review 3 testing plan: does
the whole agent work on real public websites nobody prepared for it, and
does the controller switch engines correctly mid-task?

Unlike the benchmark, nothing is forced here: the controller picks the
engine on every page exactly as it does in normal use. Each row records
which engines were used, so the switching task shows Engine 1 then
Engine 2 in the data.

USAGE (demo server running in another terminal)
    python -m agent.real_sites                  # run the tasks once, save, print the table
    python -m agent.real_sites --reps 2         # run each task twice
    python -m agent.real_sites --summary        # reprint the table from the saved file

Results go to packages/agent/logs/real_sites.jsonl, one row per run,
with the full answer. The success check is the benchmark's rule.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark import (
    ANSWER_KEEP, CELL_TIMEOUT_S, DEMO_BASE, _is_infra, _is_quota,
    _last_run_tokens, _load_agent_class, _passes, _runs_log_lines,
)

OUT = Path(__file__).parent / "logs" / "real_sites.jsonl"

TASKS = [
    {"id": "books-price", "site": "books.toscrape.com (e-commerce catalogue)",
     "instruction": 'go to https://books.toscrape.com and tell me the price of "A Light in the Attic"',
     "check": ["51.77"]},
    {"id": "quotes-author", "site": "quotes.toscrape.com (listing with authors)",
     "instruction": "go to https://quotes.toscrape.com and tell me who said the first quote on the page",
     "check": ["einstein"]},
    {"id": "table-email", "site": "the-internet.herokuapp.com (data table)",
     "instruction": "go to https://the-internet.herokuapp.com/tables and tell me "
                    "Jason Doe's email address from the first table",
     "check": ["jdoe@hotmail.com"]},
    {"id": "switch-mid-task", "site": "Agent Street dashboard, then example.com",
     "instruction": "go to {base}/dashboard/ and get this month's revenue, then go to "
                    "https://example.com and tell me the page heading",
     "check": ["82000", "example domain"],
     "expect_engines": ["webmcp", "playwright"]},
]


async def run_one(task: dict, rep: int, provider: str) -> dict[str, Any]:
    Agent, model = _load_agent_class(provider)
    instruction = task["instruction"].format(base=DEMO_BASE)
    steps: list[list[str]] = []   # [tool, engine] per step

    async def on_step(ev: dict[str, Any]) -> None:
        steps.append([str(ev.get("tool", "")), ev["engine"]])

    agent = Agent(on_step=on_step)
    runs_before = _runs_log_lines()
    start = time.monotonic()
    answer, error = "", None
    try:
        answer = await asyncio.wait_for(agent.run_task(instruction), CELL_TIMEOUT_S)
    except asyncio.TimeoutError:
        error = f"CellTimeout: no answer within {CELL_TIMEOUT_S:.0f} s"
    except Exception as exc:  # a failed run is a result, not a crash
        error = f"{type(exc).__name__}: {exc}"
    seconds = round(time.monotonic() - start, 2)
    try:
        await agent.close()
    except Exception:
        pass

    answer_ok = error is None and _passes(task["check"], answer)
    # Opening a page is always done by Playwright, even on a page with an AI
    # door, so page loads say nothing about which engine did the work. Only
    # the actions after them count.
    engines = [e for tool, e in steps if tool.split(":")[-1] != "navigate"]
    # The switching task must ALSO show Engine 1 doing work and then Engine 2
    # doing work after it: a right answer from one engine alone is no switch.
    switched = None
    if task.get("expect_engines"):
        first, second = task["expect_engines"]
        switched = first in engines and second in engines[engines.index(first):]

    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": task["id"],
        "site": task["site"],
        "rep": rep,
        "ok": answer_ok and switched is not False,
        "answer_ok": answer_ok,
        "switched": switched,
        "engines": engines,          # engine per action, page loads left out
        "steps": steps,              # every step as [tool, engine], page loads included
        "tokens": _last_run_tokens(runs_before),
        "seconds": seconds,
        "provider": provider,
        "model": model,
        "instruction": instruction,
        "answer": (answer or "")[:ANSWER_KEEP],
        "error": error,
    }
    if error and _is_infra(error):
        row["infra"] = True
    return row


def summarise(path: Path = OUT) -> None:
    if not path.exists():
        print("No real-site results yet. Run: python -m agent.real_sites")
        return
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows_ok = [r for r in rows if not r.get("infra")]
    print("\n" + "=" * 100)
    print("FULL AGENT ON REAL WEBSITES - engine chosen by the controller, not forced")
    print(f"model(s): {', '.join(sorted({r['model'] for r in rows}))}")
    print("=" * 100)
    print(f"{'task':<17}{'rep':>4}  {'result':<8}{'engines doing the work, in order':<36}{'tokens':>7}{'secs':>7}")
    print("-" * 100)
    for r in rows_ok:
        order = " > ".join(e for i, e in enumerate(r["engines"]) if i == 0 or e != r["engines"][i - 1]) or "-"
        result = "OK" if r["ok"] else "FAIL"
        tok = r["tokens"] if r["tokens"] is not None else "-"
        print(f"{r['task']:<17}{r['rep']:>4}  {result:<8}{order[:35]:<36}{tok:>7}{r['seconds']:>7.1f}")
    print("-" * 100)
    n_ok = sum(r["ok"] for r in rows_ok)
    print(f"{n_ok} of {len(rows_ok)} runs correct")
    sw = [r for r in rows_ok if r["switched"] is not None]
    if sw:
        print(f"engine switch seen in {sum(bool(r['switched']) for r in sw)} of {len(sw)} switching runs")
    infra = len(rows) - len(rows_ok)
    if infra:
        print(f"note: {infra} run(s) hit a provider error and are left out")
    print("\nAnswers:")
    for r in rows_ok:
        mark = "OK  " if r["ok"] else "FAIL"
        why = r["error"] or ("" if r["switched"] is not False else " (right answer, but no engine switch)")
        print(f"  {mark} {r['task']:<17}{why.strip() + ' ' if why else ''}{' '.join(r['answer'].split())[:110]!r}")
    print()


async def main_async(reps: int, provider: str) -> None:
    import urllib.request
    try:
        urllib.request.urlopen(DEMO_BASE + "/", timeout=5).read(1)
    except Exception as exc:
        print(f"The demo server is not answering at {DEMO_BASE} ({type(exc).__name__}).\n"
              "Start it in its own terminal first:\n"
              "    python packages/engine_webmcp/demo_pages/server.py")
        return
    total = len(TASKS) * reps
    print(f"Running {total} real-website task(s) on provider={provider}; saving to {OUT}\n")
    n = 0
    for rep in range(1, reps + 1):
        for task in TASKS:
            n += 1
            print(f"[{n}/{total}] {task['id']}: {task['instruction'].format(base=DEMO_BASE)}", flush=True)
            row = await run_one(task, rep, provider)
            if _is_quota(row["error"]):
                print(f"\nSTOPPED: the provider refused the request (limit reached?).\n  {row['error'][:200]}\n"
                      "Nothing from this task was saved. Run again later.")
                break
            OUT.parent.mkdir(parents=True, exist_ok=True)
            with OUT.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(f"        {'OK' if row['ok'] else 'FAIL'}  engines={row['engines']}  "
                  f"tokens={row['tokens']}  {row['seconds']}s")
            await asyncio.sleep(5)   # stay under the per-minute limit
        else:
            continue
        break
    summarise()


def main() -> None:
    ap = argparse.ArgumentParser(description="Full agent on real public websites")
    ap.add_argument("--reps", type=int, default=1, help="runs per task (default 1)")
    ap.add_argument("--provider", default="gemini",
                    choices=["gemini", "omniroute", "openai", "anthropic"])
    ap.add_argument("--summary", action="store_true", help="reprint the table from the saved file")
    a = ap.parse_args()
    if a.summary:
        summarise()
        return
    asyncio.run(main_async(a.reps, a.provider))


if __name__ == "__main__":
    main()
