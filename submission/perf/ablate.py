"""Task 4: ablation of the original report query (PERF.md section 2).

Runs one slice of the full query, then the same slice with each column removed on its own, then
with all of them removed. The versions are run round-robin (every round runs each version once),
so a slow moment of the machine affects all versions alike, and the median of the rounds is used.

Run from the repo root:
    uv run python submission/perf/ablate.py --from 2026-05-14 --to 2026-05-14 --tenant T040 --rounds 7
"""
import argparse
import statistics

from slices import build, columns, run

CHEAP = ("tenant_id", "plan", "channel", "day", "lines_total")  # read from the group itself, no sub-query


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--tenant")
    ap.add_argument("--rounds", type=int, default=7)
    args = ap.parse_args()

    metrics = [alias for alias, _ in columns() if alias not in CHEAP]
    versions = {"(full query)": ()} | {f"without {m}": (m,) for m in metrics} | {"without all eight": tuple(metrics)}
    times = {name: [] for name in versions}
    for r in range(args.rounds):
        for name, drop in versions.items():
            rows, elapsed = run(build(args.date_from, args.date_to, args.tenant, drop), cap_s=3600)
            times[name].append(elapsed)
        print(f"round {r + 1}/{args.rounds} done", flush=True)

    groups = len(rows)
    full = statistics.median(times["(full query)"])
    print(f"\nslice {args.date_from}..{args.date_to} tenant={args.tenant or 'all'}: {groups} groups, "
          f"{args.rounds} rounds, medians")
    print(f"{'version':42s} {'median':>8s} {'saved':>8s} {'share':>6s} {'per group':>9s}  runs")
    for name in versions:
        med = statistics.median(times[name])
        saved = full - med
        runs = ", ".join(f"{t:.1f}" for t in times[name])
        print(f"{name:42s} {med:7.2f}s {saved:7.2f}s {100 * saved / full:5.1f}% {saved / groups:8.2f}s  [{runs}]")


if __name__ == "__main__":
    main()
