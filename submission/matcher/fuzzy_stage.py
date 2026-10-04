"""Stage 2: fuzzy matching against item names. See DESIGN.md section 2."""
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from .data import Item
from .normalize import normalize

# The lowest ratio score at which a 95% lower bound on precision, measured on the
# training lines, still clears the 92.7% break-even from DESIGN.md section 1.
SUCCESS_SCORE = 70

# The second-best candidate within this many points of the best counts as a tie.
TIE_GAP = 1


@dataclass(frozen=True)
class FuzzyResult:
    item_code: str | None   # best candidate, None when the line is empty
    reason: str             # "fuzzy_match", "ambiguous_several_fit", "ambiguous_near_tie",
                            # "fuzzy_low_score" or "empty_line"
    decision: str | None    # "auto" or "review"; None means it is passed on to the next step
    score: float            # best ratio score, 0-100
    candidates: tuple[tuple[str, float], ...] = ()  # up to 3 (item_code, score), best first


class FuzzyStage:
    """Built once per tenant, then used for every line that stage 1 could not resolve."""

    def __init__(self, catalogue: dict[str, Item]):
        self.names = {code: normalize(item.item_name) for code, item in catalogue.items()}
        self.words = {code: set(name.split()) for code, name in self.names.items()}

    def match(self, text: str) -> FuzzyResult:
        if not text:
            return FuzzyResult(None, "empty_line", None, 0.0)

        top = process.extract(text, self.names, scorer=fuzz.ratio, processor=None, limit=3)
        candidates = tuple((code, score) for _, score, code in top)
        best_code, best_score = candidates[0]

        if best_score < SUCCESS_SCORE:
            return FuzzyResult(best_code, "fuzzy_low_score", None, best_score, candidates)

        # Word check: more than one item contains every word of the line.
        line_words = set(text.split())
        fitting = [code for code, words in self.words.items() if line_words <= words]
        if len(fitting) >= 2:
            scored = sorted(((code, fuzz.ratio(text, self.names[code])) for code in fitting),
                            key=lambda pair: pair[1], reverse=True)
            return FuzzyResult(best_code, "ambiguous_several_fit", "review", best_score, tuple(scored[:3]))

        # Gap check: the second-best scores almost the same as the best.
        if len(candidates) > 1 and best_score - candidates[1][1] <= TIE_GAP:
            return FuzzyResult(best_code, "ambiguous_near_tie", "review", best_score, candidates)

        return FuzzyResult(best_code, "fuzzy_match", "auto", best_score, candidates)
