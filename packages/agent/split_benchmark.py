"""
Split a benchmark results file in two, at a point in time.

Why: results from different setups (e.g. the plain demo pages vs the Agent
Street pages) must not be averaged together, because the page change alone
alters what Engine 2 reads. If two runs landed in one file, this separates
them. The original file is never changed.

USAGE (run from the project root)
    python -m agent.split_benchmark
        -> lists the runs in the file: when each started and ended, rows, model

    python -m agent.split_benchmark --at "2026-11-04 17:10" \\
            --before benchmark_v3_plain_pages.jsonl --after benchmark_street.jsonl
        -> rows before 17:10 (your local time) go to the first file,
           rows from 17:10 onwards go to the second

    python -m agent.split_benchmark --run 2 --out benchmark_street_final.jsonl
        -> copies just run 2 (as numbered in the listing) to a new file

A new run starts after a gap of 30+ minutes, or when a cell that the
current run already did comes round again (the benchmark was restarted).

Bare file names are written next to the results file (packages/agent/logs/).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

LOGS = Path(__file__).parent / "logs"
GAP = timedelta(minutes=30)   # a pause this long between rows = a new run


def _in_logs(name: str) -> Path:
    p = Path(name)
    return LOGS / p if p.parent == Path(".") else p


def _load(path: Path) -> list[tuple[datetime, str, dict]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows.append((datetime.fromisoformat(r["timestamp"]).astimezone(), line, r))
    return rows


def _key(r: dict) -> tuple:
    return (r.get("task"), r.get("forced_engine"), r.get("rep"))


def runs(rows) -> list[list]:
    """Group rows into runs: a 30+ min gap, or a cell repeating, starts a new one.
    Rows saved by --resume continue their run (they fill cells it lacked)."""
    if not rows:
        return []
    groups, cur = [], [rows[0]]
    seen = set() if rows[0][2].get("infra") else {_key(rows[0][2])}
    for prev, row in zip(rows, rows[1:]):
        k = _key(row[2])
        if row[0] - prev[0] > GAP or k in seen:
            groups.append(cur)
            cur, seen = [], set()
        cur.append(row)
        if not row[2].get("infra"):   # a provider-error cell is redone by --resume
            seen.add(k)
    groups.append(cur)
    return groups


def list_runs(rows) -> None:
    if not rows:
        print("File is empty.")
        return
    groups = runs(rows)
    print(f"{len(rows)} rows, {len(groups)} run(s):\n")
    for i, g in enumerate(groups, 1):
        models = sorted({str(r.get('model')) for _, _, r in g})
        print(f"  run {i}: {g[0][0]:%Y-%m-%d %H:%M} -> {g[-1][0]:%H:%M}   "
              f"{len(g):>3} rows   model: {', '.join(models)}")
    for i, g in enumerate(groups, 1):
        bad = sum(1 for _, _, r in g if not r.get("obs_chars") and not r.get("ok"))
        if bad == len(g):
            print(f"\n  run {i}: every row read nothing from the page (obs 0) - "
                  "likely the demo server was off")
    if len(groups) > 1:
        print(f"\nTo keep one run: --run <number> --out <new file name>")


def main() -> None:
    ap = argparse.ArgumentParser(description="Split a benchmark results file by time")
    ap.add_argument("--file", default="benchmark.jsonl", help="file to read (default benchmark.jsonl)")
    ap.add_argument("--at", help='split time, your local clock, e.g. "2026-11-04 17:10"')
    ap.add_argument("--before", help="file for rows before --at")
    ap.add_argument("--after", help="file for rows at or after --at")
    ap.add_argument("--run", type=int, help="copy just this run (number from the listing)")
    ap.add_argument("--out", help="file name for --run")
    a = ap.parse_args()

    src = _in_logs(a.file)
    if not src.exists():
        print(f"No such file: {src}")
        return
    rows = _load(src)
    if a.run:
        groups = runs(rows)
        if not a.out or not 1 <= a.run <= len(groups):
            print(f"--run needs --out, and a run number from 1 to {len(groups)}.")
            return
        out = _in_logs(a.out)
        if out.exists():
            print(f"Not overwriting {out} - it already exists. Pick another name or move it first.")
            return
        out.write_text("".join(line + "\n" for _, line, _ in groups[a.run - 1]), encoding="utf-8")
        print(f"{len(groups[a.run - 1]):>3} rows (run {a.run}) -> {out}\n{src.name} itself was not changed.")
        return
    if not a.at:
        list_runs(rows)
        return
    if not (a.before and a.after):
        print("--at needs both --before and --after file names.")
        return

    cut = datetime.fromisoformat(a.at).astimezone()
    before = [line for t, line, _ in rows if t < cut]
    after = [line for t, line, _ in rows if t >= cut]
    for name, lines in ((a.before, before), (a.after, after)):
        out = _in_logs(name)
        if out.exists():
            print(f"Not overwriting {out} - it already exists. Pick another name or move it first.")
            return
    for name, lines in ((a.before, before), (a.after, after)):
        out = _in_logs(name)
        out.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
        print(f"{len(lines):>3} rows -> {out}")
    print(f"\n{src.name} itself was not changed.")


if __name__ == "__main__":
    main()
