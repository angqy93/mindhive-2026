"""Final step: turns a stage result into a decision. See DESIGN.md section 2."""
from dataclasses import dataclass

from .embedding_stage import EmbeddingResult
from .fuzzy_stage import FuzzyResult
from .regex_stage import RegexResult

# Lines that fuzzy scores below this are rejected: on the training lines, no line
# below 60 had a correct answer. Temporary: the final value is set from the ROC curve (Task 3).
REVIEW_FLOOR = 60


@dataclass(frozen=True)
class Decision:
    item_code: str                               # blank unless the decision is "auto"
    top_candidate: str | None                    # the best guess, even when not auto
    decision: str                                # "auto", "review" or "reject"
    reason_code: str
    score: float                                 # the stage's own score, 0-100
    candidates: tuple[tuple[str, float], ...]    # up to 3 (item_code, score), best first


def decide(regex: RegexResult, fuzzy: FuzzyResult | None, embedding: EmbeddingResult | None = None) -> Decision:
    if regex.decision is not None:
        reason, decision, best, score = regex.reason, regex.decision, regex.item_code, 100.0
        candidates = regex.candidates or ((regex.item_code, 100.0),)
    else:
        reason, decision, best, score = fuzzy.reason, fuzzy.decision, fuzzy.item_code, fuzzy.score
        candidates = fuzzy.candidates
        if decision is None:  # passed on by fuzzy: empty, or scored below 70
            if reason == "empty_line":
                reason, decision = "not_an_item", "reject"
            elif score >= REVIEW_FLOOR:
                decision = "review"
            elif embedding is not None and embedding.reason != "embedding_unavailable":
                # Stage 3 ran: its reason explains the outcome, its top 3 become the suggestions.
                reason, decision, best = embedding.reason, embedding.decision or "reject", embedding.item_code
                score, candidates = embedding.score, embedding.candidates
            else:
                reason, decision = "no_candidate_above_floor", "reject"

    return Decision(
        item_code=best if decision == "auto" else "",
        top_candidate=best,
        decision=decision,
        reason_code=reason,
        score=score,
        candidates=candidates[:3],
    )
