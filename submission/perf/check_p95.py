"""Task 4: checks the p95_latency_ms column of report_fast.sql (PERF.md section 4).

bench_report.py check does not compare new columns, so this computes the nearest-rank p95 the
plain way, in Python, from the raw events: for every tenant and day, sort all latencies of that
tenant's candidates (all channels, the same set as max_latency_ms) and take the one at position
ceil(0.95 x count). Every row of the report must have that value.

Run from the repo root:  uv run python submission/perf/check_p95.py
"""
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "perf.sqlite"
REPORT = Path(__file__).resolve().parent / "report_fast.sql"


def main() -> None:
    con = sqlite3.connect(DB)
    latencies = defaultdict(list)
    for tenant, day, latency in con.execute(
            "SELECT tenant_id, substr(created_at, 1, 10), latency_ms FROM match_event "
            "WHERE substr(created_at, 1, 10) BETWEEN '2026-05-01' AND '2026-06-30'"):
        latencies[(tenant, day)].append(latency)
    expected = {key: sorted(values)[math.ceil(0.95 * len(values)) - 1] for key, values in latencies.items()}

    con.row_factory = sqlite3.Row
    rows = con.execute(REPORT.read_text(encoding="utf-8")).fetchall()
    wrong = [r for r in rows if r["p95_latency_ms"] != expected[(r["tenant_id"], r["day"])]]
    print(f"p95_latency_ms: {len(rows)} rows checked, {len(wrong)} differ from the plain nearest-rank p95")
    for r in wrong[:5]:
        print("  ", r["tenant_id"], r["day"], r["channel"], r["p95_latency_ms"], "expected", expected[(r["tenant_id"], r["day"])])
    raise SystemExit(1 if wrong else 0)


if __name__ == "__main__":
    main()
