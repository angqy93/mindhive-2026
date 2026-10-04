"""Evaluation harness (Task 3): scores the matcher on the labelled training lines.

Run from the repo root:  uv run python submission/evaluate.py

Every line is scored by a matcher that learned (calibration, embeddings success line) from the
other 4 of 5 folds, never from the line itself. Scored twice: against the original labels and
against the corrected labels. See EVAL.md.
"""
import csv
import random
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from matcher import Matcher, Prediction, load_catalogue, load_model, load_sku_map
from matcher.data import DATA_DIR
from segments import GROUPS, Segmenter

HERE = Path(__file__).resolve().parent
LABEL_SETS = {
    "original labels": DATA_DIR / "order_lines_train.csv",
    "corrected labels": HERE / "data" / "order_lines_train_corrected.csv",
}
FOLDS = 5
SEED = 0  # fixed, so the folds (and every number) are the same run to run

# Cost model from README section 1, in seconds.
RIGHT, ABSTAIN, WRONG = 20, -40, -800


@dataclass(frozen=True)
class Scored:
    line: dict
    prediction: Prediction
    groups: list[str]

    @property
    def label(self) -> str:
        return self.line["gt_item_code"]

    @property
    def top(self) -> str:
        return self.prediction.candidates.split("|")[0].split(":")[0] if self.prediction.candidates else ""

    @property
    def top3(self) -> list[str]:
        return [c.split(":")[0] for c in self.prediction.candidates.split("|") if c]


def read_lines(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cross_validate(matcher: Matcher, lines: list[dict], segmenters: dict) -> list[Scored]:
    """Each fold is predicted by a matcher fitted on the other folds."""
    order = list(range(len(lines)))
    random.Random(SEED).shuffle(order)
    folds = [set(order[k::FOLDS]) for k in range(FOLDS)]
    scored = [None] * len(lines)
    for fold in folds:
        matcher.fit([line for i, line in enumerate(lines) if i not in fold])
        for i in fold:
            line = lines[i]
            scored[i] = Scored(line, matcher.predict(line), segmenters[line["tenant"]].groups(line))
    return scored


def metrics(rows: list[Scored]) -> dict:
    auto = [r for r in rows if r.prediction.decision == "auto"]
    right = sum(r.prediction.item_code == r.label for r in auto)
    wrong = len(auto) - right
    abstained = [r for r in rows if r.prediction.decision != "auto"]
    no_answer = [r for r in rows if not r.label]
    missed = [r for r in abstained if r.label]  # abstained although a right answer exists
    return {
        "lines": len(rows),
        "auto": len(auto),
        "coverage": len(auto) / len(rows) if rows else 0.0,
        "precision": right / len(auto) if auto else None,
        "wrong_auto": wrong,
        "net_value": RIGHT * right + ABSTAIN * len(abstained) + WRONG * wrong,
        "all_human": ABSTAIN * len(rows),
        "refused_no_answer": sum(r.prediction.decision != "auto" for r in no_answer) / len(no_answer) if no_answer else None,
        "recall3_abstained": sum(r.label in r.top3 for r in missed) / len(missed) if missed else None,
        "accuracy": sum((r.prediction.item_code or "") == r.label for r in rows) / len(rows) if rows else 0.0,
    }


def pct(x) -> str:
    return "   -  " if x is None else f"{100 * x:5.1f}%"


def print_table(title: str, segments: dict[str, list[Scored]]) -> None:
    print(f"\n{title}")
    print(f"  {'':18s} {'lines':>5s} {'auto':>5s} {'coverage':>8s} {'precision':>9s} {'wrong':>5s}"
          f" {'net value':>9s} {'refused':>8s} {'recall@3':>8s}")
    for name, rows in segments.items():
        if not rows:
            continue
        m = metrics(rows)
        print(f"  {name:18s} {m['lines']:5d} {m['auto']:5d} {pct(m['coverage']):>8s} {pct(m['precision']):>9s}"
              f" {m['wrong_auto']:5d} {m['net_value']:9d} {pct(m['refused_no_answer']):>8s}"
              f" {pct(m['recall3_abstained']):>8s}")


def curve(rows: list[Scored]) -> list[tuple[float, float, float | None, int]]:
    """Precision vs coverage if every line whose confidence is at least t were auto-answered
    with its top candidate."""
    points = []
    for t in sorted({r.prediction.confidence for r in rows}, reverse=True):
        answered = [r for r in rows if r.prediction.confidence >= t and r.top]
        right = sum(r.top == r.label for r in answered)
        net = RIGHT * right + WRONG * (len(answered) - right) + ABSTAIN * (len(rows) - len(answered))
        points.append((t, len(answered) / len(rows), right / len(answered) if answered else None, net))
    return points


def timing(matcher: Matcher, lines: list[dict]) -> tuple[float, float, float]:
    matcher.predict(lines[0])  # warm-up: cold caches are excluded (README section 5.1)
    times = []
    for line in lines:
        start = time.perf_counter()
        matcher.predict(line)
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), statistics.quantiles(times, n=20)[18], max(times)


def main() -> None:
    model = load_model()
    print("embedding model:", "loaded" if model is not None else "not found, running without stage 3")
    catalogues = {t: load_catalogue(t) for t in ("acme", "nordic")}
    matcher = Matcher(catalogues, load_sku_map(), model)
    segmenters = {t: Segmenter(c) for t, c in catalogues.items()}

    for label_set, path in LABEL_SETS.items():
        lines = read_lines(path)
        scored = cross_validate(matcher, lines, segmenters)
        print(f"\n{'=' * 100}\n{label_set.upper()}  ({path.name}, {FOLDS}-fold)\n{'=' * 100}")
        m = metrics(scored)
        print(f"  precision on auto {pct(m['precision'])}  coverage {pct(m['coverage'])}  wrong autos {m['wrong_auto']}"
              f"  net value {m['net_value']} s (all-human {m['all_human']} s)  accuracy {pct(m['accuracy'])}")
        cross = [r.line["line_id"] for r in scored
                 if any(not code.startswith(r.line["line_id"][:3]) for code in r.top3)]
        print(f"  cross-tenant violations: {len(cross)}")
        print_table("per tenant", {t: [r for r in scored if r.line["tenant"] == t] for t in catalogues})
        print_table("per noise group (a line can be in several)",
                    {g: [r for r in scored if g in r.groups] for g in GROUPS})
        print("\n  precision vs coverage (auto-answer every line with confidence >= t; a row per ~5% coverage)")
        print(f"  {'t':>6s} {'coverage':>8s} {'precision':>9s} {'net value':>9s}")
        points = curve(scored)
        best = max(points, key=lambda p: p[3])
        last = -1.0
        for point in points:
            t, cov, prec, net = point
            if cov - last >= 0.05 or point == best:
                print(f"  {t:6.3f} {pct(cov):>8s} {pct(prec):>9s} {net:9d}" + ("   <- best net value" if point == best else ""))
                last = cov

    median, p95, worst = timing(matcher, read_lines(LABEL_SETS["corrected labels"]))
    print(f"\ntime per line: median {median:.1f} ms, p95 {p95:.1f} ms, max {worst:.1f} ms (budget: p95 <= 250 ms)")


if __name__ == "__main__":
    main()
