"""Turns each stage's own score into a calibrated confidence. See DESIGN.md section 2."""
from bisect import bisect_right
from collections import defaultdict

from sklearn.isotonic import IsotonicRegression


class Calibrator:
    """Learns, separately for each reason code, how often answers with a given score were right.

    Isotonic regression splits each reason's scores into groups where a higher score never
    has a lower hit rate. Each group then reports (right + 1) / (lines + 2): counted as if it
    had seen one extra right and one extra wrong answer, so a small group never claims
    exactly 100% or 0%. Lanes without a varying score (exact matches) form one group.
    A second isotonic pass keeps the groups in order after that adjustment.
    """

    def __init__(self, examples: list[tuple[str, float, bool]]):
        """examples: (reason_code, score, top candidate was correct) for each labelled line."""
        grouped = defaultdict(list)
        for reason, score, correct in examples:
            grouped[reason].append((score, 1.0 if correct else 0.0))

        self.steps = {}  # reason -> (lowest score of each group, confidence of each group)
        for reason, pairs in grouped.items():
            scores, outcomes = zip(*sorted(pairs))
            levels = IsotonicRegression().fit(scores, outcomes).predict(scores)
            groups = []  # [lowest score, lines, right]
            for score, outcome, level in zip(scores, outcomes, levels):
                if not groups or level != groups[-1][3]:
                    groups.append([score, 0, 0, level])
                groups[-1][1] += 1
                groups[-1][2] += outcome
            starts = [g[0] for g in groups]
            smoothed = [(right + 1) / (lines + 2) for _, lines, right, _ in groups]
            # The +1/+2 pulls small groups towards 50% more than big ones, which can put a small
            # low-score group above a bigger high-score group. A second isotonic pass, weighted by
            # group size, merges any such pair so a higher score never gets a lower confidence.
            weights = [lines + 2 for _, lines, _, _ in groups]
            fitted = IsotonicRegression().fit(starts, smoothed, sample_weight=weights).predict(starts)
            self.steps[reason] = (starts, [float(v) for v in fitted])

    def confidence(self, reason: str, score: float) -> float:
        if reason not in self.steps:  # a reason never seen in the labelled lines
            return 0.5
        starts, values = self.steps[reason]
        return round(values[max(bisect_right(starts, score) - 1, 0)], 3)


# The break-even precision from DESIGN.md section 1: below it, a human is cheaper.
PRECISION_TARGET = 0.927


def wilson_lower(right: int, total: int, z: float = 1.645) -> float:
    """One-sided 95% lower bound on a hit rate: accounts for how few answers it is based on."""
    if total == 0:
        return 0.0
    rate = right / total
    centre = rate + z * z / (2 * total)
    spread = z * ((rate * (1 - rate) + z * z / (4 * total)) / total) ** 0.5
    return (centre - spread) / (1 + z * z / total)


def success_line(examples: list[tuple[float, bool]]) -> float | None:
    """The lowest score at which answers scoring at or above it reach PRECISION_TARGET.

    examples: (score, top candidate was correct). None when no score is good enough.
    """
    for cut in sorted({score for score, _ in examples}):
        above = [correct for score, correct in examples if score >= cut]
        if wilson_lower(sum(above), len(above)) >= PRECISION_TARGET:
            return cut
    return None
