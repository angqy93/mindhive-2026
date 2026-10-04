"""Writes predictions.csv for the holdout lines.

Run from the repo root:  uv run python submission/run.py
"""
import csv
import statistics
import time
from collections import Counter
from pathlib import Path

from matcher import Matcher, load_catalogue, load_model, load_sku_map
from matcher.data import DATA_DIR

HERE = Path(__file__).resolve().parent
LABELLED = HERE / "data" / "order_lines_train_corrected.csv"
HOLDOUT = DATA_DIR / "order_lines_holdout.csv"
OUTPUT = HERE / "predictions.csv"
COLUMNS = ["line_id", "item_code", "confidence", "decision", "reason_code", "candidates"]


def read_lines(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    model = load_model()
    print("embedding model:", "loaded" if model is not None else "not found, running without stage 3")

    tenants = sorted(path.stem.removeprefix("catalogue_") for path in DATA_DIR.glob("catalogue_*.csv"))
    matcher = Matcher({tenant: load_catalogue(tenant) for tenant in tenants}, load_sku_map(), model)
    matcher.fit(read_lines(LABELLED))

    predictions, times = [], []
    for line in read_lines(HOLDOUT):
        start = time.perf_counter()
        predictions.append(matcher.predict(line))
        times.append((time.perf_counter() - start) * 1000)

    with open(OUTPUT, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for p in predictions:
            writer.writerow([p.line_id, p.item_code, f"{p.confidence:.3f}", p.decision, p.reason_code, p.candidates])

    print(f"wrote {len(predictions)} lines to {OUTPUT}")
    print("decisions:", dict(Counter(p.decision for p in predictions)))
    print(f"time per line: median {statistics.median(times):.1f} ms, "
          f"p95 {statistics.quantiles(times, n=20)[18]:.1f} ms, max {max(times):.1f} ms")


if __name__ == "__main__":
    main()
