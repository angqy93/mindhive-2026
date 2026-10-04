"""Order-line matcher: resolves a free-text order line to an item_code, or abstains. See DESIGN.md."""
from .data import CustomerKey, Item, SkuMapping, load_catalogue, load_sku_map
from .normalize import normalize
from .regex_stage import RegexResult, RegexStage
from .fuzzy_stage import FuzzyResult, FuzzyStage
from .embedding_stage import EmbeddingResult, EmbeddingStage, load_model
from .decide import Decision, decide
from .calibration import Calibrator, success_line
from .pipeline import Matcher, Prediction, TenantMatcher

__all__ = [
    "CustomerKey", "Item", "SkuMapping", "load_catalogue", "load_sku_map",
    "normalize", "RegexResult", "RegexStage", "FuzzyResult", "FuzzyStage",
    "EmbeddingResult", "EmbeddingStage", "load_model", "Decision", "decide", "Calibrator", "success_line",
    "Matcher", "Prediction", "TenantMatcher",
]
