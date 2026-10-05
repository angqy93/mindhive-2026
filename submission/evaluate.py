"""Evaluation harness (Task 3): scores the matcher on the labelled training lines.

Run from the repo root:  uv run python submission/evaluate.py
Without the embedding stage:  uv run python submission/evaluate.py --no-embeddings

Every line is scored by a matcher that learned (calibration, embeddings success line) from the
other 4 of 5 folds, never from the line itself. Scored twice: against the original labels and
against the corrected labels. Ends with the regression gates (EVAL.md section 5): the exit code
is 1 if any gate fails, so CI blocks the change. See EVAL.md.
"""
import csv
import json
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from matcher import (FuzzyStage, Matcher, Prediction, RegexStage, load_catalogue, load_model,
                     load_sku_map)
from matcher.calibration import PRECISION_TARGET, success_line, wilson_lower
from matcher.data import DATA_DIR
from matcher.decide import REVIEW_FLOOR
from segments import GROUPS, Segmenter

HERE = Path(__file__).resolve().parent
LABEL_SETS = {
    "original labels": DATA_DIR / "order_lines_train.csv",
    "corrected labels": HERE / "data" / "order_lines_train_corrected.csv",
}
GATE_LABELS = "corrected labels"  # the benchmark the gates are checked on (EVAL.md section 5)
BASELINE = HERE / "eval_baseline.json"  # the last accepted run
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


def fold_sets(n: int) -> list[set[int]]:
    """The same 5 folds every run (fixed seed)."""
    order = list(range(n))
    random.Random(SEED).shuffle(order)
    return [set(order[k::FOLDS]) for k in range(FOLDS)]


def cross_validate(matcher: Matcher, lines: list[dict], segmenters: dict) -> list[Scored]:
    """Each fold is predicted by a matcher fitted on the other folds."""
    scored = [None] * len(lines)
    for fold in fold_sets(len(lines)):
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


def fuzzy_line_checks(label_sets: dict[str, list[dict]], catalogues: dict, sku_map: dict) -> None:
    """EVAL.md section 1: is the fuzzy success line of 70 overfitted?

    Uses every fuzzy answer that passes the gap and word checks, whatever its score, so the line
    can be moved or re-chosen with the same 92.7% rule the matcher uses.
    """
    stages = {t: (RegexStage(t, c, sku_map), FuzzyStage(c, success_score=0)) for t, c in catalogues.items()}
    answers = {}  # label set -> [(line index, tenant, fuzzy score, right?)]
    for name, lines in label_sets.items():
        answers[name] = []
        for i, line in enumerate(lines):
            regex, fuzzy = stages[line["tenant"]]
            r = regex.match(line)
            f = fuzzy.match(r.text) if r.decision is None else None
            if f is not None and f.reason == "fuzzy_match":
                answers[name].append((i, line["tenant"], f.score, f.item_code == line["gt_item_code"]))

    print(f"\n{'=' * 100}\nIS THE FUZZY SUCCESS LINE OVERFITTED?  ({len(answers[GATE_LABELS])} fuzzy answers pass both checks)\n{'=' * 100}")
    print("  1) moving the line")
    print(f"  {'line':>6s} {'answers':>8s}" + "".join(f" {'right (' + n.split()[0] + ')':>18s} {'lower bound':>11s}" for n in answers))
    for cut in (60, 65, 70, 75, 80):
        row = f"  {cut:6d} {sum(s >= cut for _, _, s, _ in answers[GATE_LABELS]):8d}"
        for ex in answers.values():
            above = [ok for _, _, s, ok in ex if s >= cut]
            row += f" {sum(above):18d} {pct(wilson_lower(sum(above), len(above))):>11s}"
        print(row)

    print("\n  2) re-choosing the line with the 92.7% rule from 4 folds, testing on the 5th")
    for name, ex in answers.items():
        picks, tested = [], []
        for fold in fold_sets(len(label_sets[name])):
            cut = success_line([(s, ok) for i, _, s, ok in ex if i not in fold])
            picks.append("none" if cut is None else f"{cut:.0f}")
            tested += [ok for i, _, s, ok in ex if i in fold and cut is not None and s >= cut]
        print(f"  {name:17s} lines chosen: {', '.join(picks):24s} unseen answers right: {sum(tested)}/{len(tested)}")

    print("\n  3) choosing the line on one tenant, testing on the other")
    for name, ex in answers.items():
        for train, test in (("acme", "nordic"), ("nordic", "acme")):
            cut = success_line([(s, ok) for _, t, s, ok in ex if t == train])
            tested = [ok for _, t, s, ok in ex if t == test and cut is not None and s >= cut]
            print(f"  {name:17s} chosen on {train:6s}: line {'none' if cut is None else f'{cut:.0f}':4s}"
                  f"  answers right on {test}: {sum(tested)}/{len(tested)}")


def review_floor_roc(lines: list[dict], catalogues: dict, sku_map: dict) -> None:
    """EVAL.md section 2: ROC table for the review floor. Lines that fuzzy scores below the
    success line go to review at or above the floor, and are rejected below it."""
    stages = {t: (RegexStage(t, c, sku_map), FuzzyStage(c)) for t, c in catalogues.items()}
    rows = []  # (fuzzy score, has a right answer?)
    for line in lines:
        regex, fuzzy = stages[line["tenant"]]
        r = regex.match(line)
        f = fuzzy.match(r.text) if r.decision is None else None
        if f is not None and f.reason == "fuzzy_low_score":
            rows.append((f.score, bool(line["gt_item_code"])))
    answered = sum(has for _, has in rows)
    print(f"\n{'=' * 100}\nREVIEW FLOOR (ROC, {GATE_LABELS})  ({len(rows)} lines below the fuzzy success line,"
          f" {answered} with a right answer)\n{'=' * 100}")
    print(f"  {'floor':>6s} {'to review':>9s} {'answered lines kept for review':>31s} {'no-answer lines sent to review':>31s}")
    for floor in (0, 30, 40, 50, 55, 60, 62, 65, 68, 70):
        review = [has for score, has in rows if score >= floor]
        kept = f"{sum(review)}/{answered}"
        junk = f"{len(review) - sum(review)}/{len(rows) - answered}"
        print(f"  {floor:6d} {len(review):9d} {kept:>31s} {junk:>31s}" + ("   <- current" if floor == REVIEW_FLOOR else ""))


def check_gates(m: dict, cross_tenant: int) -> list[str]:
    """The gates from EVAL.md section 5. Returns what failed; empty means the change may ship."""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    failures = []
    if cross_tenant:
        failures.append(f"{cross_tenant} cross-tenant answers (must be 0)")
    if m["precision"] is not None and m["precision"] < PRECISION_TARGET:
        failures.append(f"precision on auto {pct(m['precision'])} is below {100 * PRECISION_TARGET:.1f}%")
    if m["wrong_auto"] > baseline["wrong_autos"]:
        failures.append(f"{m['wrong_auto']} wrong autos, more than the {baseline['wrong_autos']} last accepted")
    return failures


def main() -> None:
    # --no-embeddings runs the non-semantic baseline (regex and fuzzy only), to measure what the
    # embedding stage adds (EVAL.md section 1).
    model = None if "--no-embeddings" in sys.argv else load_model()
    print("embedding model:", "loaded" if model is not None else "not found, running without stage 3")
    catalogues = {t: load_catalogue(t) for t in ("acme", "nordic")}
    sku_map = load_sku_map()
    matcher = Matcher(catalogues, sku_map, model)
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
        if label_set == GATE_LABELS:
            gate_inputs = (m, len(cross))
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

    fuzzy_line_checks({name: read_lines(path) for name, path in LABEL_SETS.items()}, catalogues, sku_map)
    review_floor_roc(read_lines(LABEL_SETS[GATE_LABELS]), catalogues, sku_map)

    median, p95, worst = timing(matcher, read_lines(LABEL_SETS["corrected labels"]))
    print(f"\ntime per line: median {median:.1f} ms, p95 {p95:.1f} ms, max {worst:.1f} ms (budget: p95 <= 250 ms)")

    failures = check_gates(*gate_inputs)
    print(f"\nGATES ({GATE_LABELS}):", "PASS" if not failures else "FAIL")
    for failure in failures:
        print("  -", failure)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
