"""Task 4: time slices of the original report query (PERF.md sections 1 and 2).

The full report takes too long to run, so it is measured in slices: a shorter date range,
optionally one tenant or one channel, optionally with some columns removed. Every slice is
built from starter/report_query.sql itself, so it computes exactly what the original computes.

Run from the repo root, e.g.:
    uv run python submission/perf/slices.py --from 2026-05-14 --to 2026-05-14 --tenant T040
    uv run python submission/perf/slices.py --from 2026-05-14 --to 2026-05-14 --tenant T040 --drop repeat_items_prev_day
"""
import argparse
import gzip
import json
import re
import sqlite3
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUERY = ROOT / "starter" / "report_query.sql"
DB = ROOT / "data" / "perf.sqlite"
REFERENCE = ROOT / "data" / "report_reference.json.gz"


def split_top_level(text: str) -> list[str]:
    """Splits the SELECT list on commas that are not inside brackets."""
    parts, depth, current = [], 0, ""
    for ch in text:
        depth += (ch == "(") - (ch == ")")
        if ch == "," and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += ch
    parts.append(current.strip())
    return parts


def columns() -> list[tuple[str, str]]:
    """(alias, expression) for every column of the original query, in order."""
    sql = re.sub(r"--[^\n]*", "", QUERY.read_text(encoding="utf-8"))
    # the outer FROM, not "FROM order_line ol4" inside a sub-query
    outer_from = re.search(r"FROM order_line ol\s+JOIN tenant", sql).start()
    select = sql[sql.index("SELECT") + len("SELECT"):outer_from]
    result = []
    for expr in split_top_level(select):
        alias = re.search(r"(?:AS\s+)?(\w+)\s*$", expr).group(1)
        if alias in ("tenant_id", "plan", "channel"):  # t.tenant_id, t.plan, ol.channel
            alias = expr.split(".")[-1]
        result.append((alias, expr))
    return result


def build(date_from: str, date_to: str, tenant: str | None = None, drop: tuple[str, ...] = (),
          channel: str | None = None) -> str:
    kept = [expr for alias, expr in columns() if alias not in drop]
    filters = ""
    if tenant:
        filters += f"\n  AND t.tenant_id = '{tenant}'"
    if channel:
        filters += f"\n  AND ol.channel = '{channel}'"
    return (
        "SELECT\n    " + ",\n    ".join(kept) + "\n"
        "FROM order_line ol\n"
        "JOIN tenant t ON t.tenant_id = ol.tenant_id\n"
        f"WHERE substr(ol.created_at, 1, 10) >= '{date_from}'\n"
        f"  AND substr(ol.created_at, 1, 10) <= '{date_to}'{filters}\n"
        "GROUP BY t.tenant_id, t.plan, ol.channel, substr(ol.created_at, 1, 10)\n"
        "ORDER BY t.tenant_id, ol.channel, day;"
    )


def run(sql: str, cap_s: float) -> tuple[list[dict] | None, float]:
    """Runs the query; gives up after cap_s seconds (rows = None)."""
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    start = time.perf_counter()
    con.set_progress_handler(lambda: time.perf_counter() - start > cap_s, 100_000)
    try:
        rows = [dict(r) for r in con.execute(sql).fetchall()]
    except sqlite3.OperationalError:  # interrupted at the cap
        rows = None
    elapsed = time.perf_counter() - start
    con.close()
    return rows, elapsed


def matches_reference(rows: list[dict], date_from: str, date_to: str, tenant: str | None,
                      channel: str | None) -> bool:
    """The slice must equal the same rows of the full reference result."""
    ref = json.load(gzip.open(REFERENCE, "rt"))
    want = [r for r in ref["rows"] if date_from <= r["day"] <= date_to
            and (tenant is None or r["tenant_id"] == tenant) and (channel is None or r["channel"] == channel)]
    cols = [c for c in ref["columns"] if rows and c in rows[0]]
    key = lambda r: tuple(round(r[c], 6) if isinstance(r[c], float) else r[c] for c in cols)
    return sorted(map(key, rows)) == sorted(map(key, want))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="date_from", required=True)
    ap.add_argument("--to", dest="date_to", required=True)
    ap.add_argument("--tenant")
    ap.add_argument("--channel")
    ap.add_argument("--drop", nargs="*", default=[])
    ap.add_argument("--repeat", type=int, default=1, help="run this many times, report the median")
    ap.add_argument("--cap", type=float, default=300, help="give up after this many seconds")
    args = ap.parse_args()

    sql = build(args.date_from, args.date_to, args.tenant, tuple(args.drop), args.channel)
    label = (f"{args.date_from}..{args.date_to} tenant={args.tenant or 'all'} channel={args.channel or 'all'}"
             f" drop={','.join(args.drop) or '-'}")
    times = []
    for _ in range(args.repeat):
        rows, elapsed = run(sql, args.cap)
        if rows is None:
            print(f"{label}: stopped at the {args.cap:.0f}s cap")
            return
        times.append(elapsed)
    same = matches_reference(rows, args.date_from, args.date_to, args.tenant, args.channel) if not args.drop else None
    print(f"{label}: {len(rows)} rows, median {statistics.median(times):.2f}s over {len(times)} run(s)"
          + ("" if same is None else f", matches reference: {same}"))


if __name__ == "__main__":
    main()
