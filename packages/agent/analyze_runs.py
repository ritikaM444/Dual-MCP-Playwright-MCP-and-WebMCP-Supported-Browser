"""
Reads logs/runs.jsonl and prints the Engine 1 vs Engine 2 summary --
the table that goes in your Review 3 testing report and the paper.

Pure standard library on purpose: no pandas needed, runs anywhere.

Run: python -m agent.analyze_runs
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from statistics import mean

from .run_logger import LOG_PATH


def main() -> None:
    if not LOG_PATH.exists():
        print(f"No runs logged yet -- expected {LOG_PATH}")
        print("Run some tasks through the CLI or web UI first.")
        return

    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a partially-written line rather than crash

    if not rows:
        print("Log file exists but has no complete rows yet.")
        return

    ok = [r for r in rows if r["ok"]]
    print(f"Runs logged:    {len(rows)}")
    print(f"Succeeded:      {len(ok)} ({100 * len(ok) / len(rows):.0f}%)")
    print(f"Mean seconds:   {mean(r['seconds'] for r in rows):.1f}")
    print(f"Mean tokens:    {mean(r['total_tokens'] for r in rows):.0f}")
    print(f"Mean steps:     {mean(r['steps'] for r in rows):.1f}")

    engine_steps: Counter[str] = Counter()
    for r in rows:
        for engine, n in r["engine_counts"].items():
            engine_steps[engine] += n
    print("\nSteps by engine (the Parameter 3 comparison):")
    for engine, n in engine_steps.most_common():
        print(f"  {engine:<22} {n}")

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    print("\nBy model:")
    for model, rs in by_model.items():
        succ = 100 * sum(1 for r in rs if r["ok"]) / len(rs)
        print(f"  {model:<28} runs={len(rs):<4} success={succ:.0f}%  "
              f"mean_tokens={mean(r['total_tokens'] for r in rs):.0f}  "
              f"mean_secs={mean(r['seconds'] for r in rs):.1f}")

    failures = [r for r in rows if not r["ok"]]
    if failures:
        print(f"\nFailures ({len(failures)}) -- failure-mode catalogue for the report:")
        for r in failures[-5:]:
            print(f"  {r['timestamp'][:19]}  {r['error']}")


if __name__ == "__main__":
    main()
