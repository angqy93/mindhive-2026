"""The whole matcher: stages 1-3, the decision and the calibrated confidence. See DESIGN.md section 2."""
from dataclasses import dataclass

from .calibration import Calibrator, success_line
from .data import CustomerKey, Item, SkuMapping
from .decide import REVIEW_FLOOR, Decision, decide
from .embedding_stage import EmbeddingStage
from .fuzzy_stage import FuzzyStage
from .regex_stage import RegexStage


@dataclass(frozen=True)
class Prediction:
    line_id: str
    item_code: str      # blank unless the decision is "auto"
    confidence: float   # how often lines with this reason and score were right, 0-1
    decision: str       # "auto", "review" or "reject"
    reason_code: str
    candidates: str     # up to 3 "item_code:score", "|"-separated, best first


class TenantMatcher:
    """Every stage for one tenant. It only ever sees that tenant's catalogue and SKU map."""

    def __init__(self, tenant: str, catalogue: dict[str, Item],
                 sku_map: dict[CustomerKey, dict[str, list[SkuMapping]]], model=None):
        self.regex = RegexStage(tenant, catalogue, sku_map)
        self.fuzzy = FuzzyStage(catalogue)
        self.embedding = EmbeddingStage(catalogue, model) if model is not None else None

    def decide(self, line: dict) -> Decision:
        regex = self.regex.match(line)
        if regex.decision is not None:
            return decide(regex, None)
        fuzzy = self.fuzzy.match(regex.text)
        embedding = None
        # Stage 3 only runs in the failure zone: fuzzy found no overlap in words.
        if (self.embedding is not None and fuzzy.decision is None
                and fuzzy.reason != "empty_line" and fuzzy.score < REVIEW_FLOOR):
            embedding = self.embedding.match(regex.text)
        return decide(regex, fuzzy, embedding)


class Matcher:
    """All tenants. fit() learns from labelled lines, then predict() handles one order line."""

    def __init__(self, catalogues: dict[str, dict[str, Item]],
                 sku_map: dict[CustomerKey, dict[str, list[SkuMapping]]], model=None):
        self.tenants = {tenant: TenantMatcher(tenant, catalogue, sku_map, model)
                        for tenant, catalogue in catalogues.items()}
        self.calibrator = Calibrator([])

    def fit(self, labelled: list[dict]) -> None:
        """Learns the embeddings success line, then the confidence calibration.

        labelled: order lines with gt_item_code (blank means the right answer is to abstain).
        """
        # 1. Embeddings: answers that passed every check, and whether they were right.
        decisions = [(line, self.tenants[line["tenant"]].decide(line)) for line in labelled]
        examples = [(d.score, is_correct(line, d)) for line, d in decisions
                    if d.reason_code == "embedding_low_score"]
        cut = success_line(examples)
        for tenant in self.tenants.values():
            if tenant.embedding is not None:
                tenant.embedding.success_line = cut

        # 2. Confidence, learned on the final decisions.
        decisions = [(line, self.tenants[line["tenant"]].decide(line)) for line in labelled]
        self.calibrator = Calibrator([(d.reason_code, d.score, is_correct(line, d)) for line, d in decisions])

    def predict(self, line: dict) -> Prediction:
        d = self.tenants[line["tenant"]].decide(line)
        return Prediction(
            line_id=line["line_id"],
            item_code=d.item_code,
            confidence=self.calibrator.confidence(d.reason_code, d.score),
            decision=d.decision,
            reason_code=d.reason_code,
            candidates="|".join(f"{code}:{score:.1f}" for code, score in d.candidates),
        )


def is_correct(line: dict, d: Decision) -> bool:
    """The top candidate is the labelled item (a blank label is never matched)."""
    return bool(line["gt_item_code"]) and d.top_candidate == line["gt_item_code"]
