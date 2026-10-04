"""Order-line matcher: resolves a free-text order line to an item_code, or abstains. See DESIGN.md."""
from .data import CustomerKey, Item, SkuMapping, load_catalogue, load_sku_map
from .normalize import normalize
from .regex_stage import RegexResult, RegexStage
from .fuzzy_stage import FuzzyResult, FuzzyStage

__all__ = [
    "CustomerKey", "Item", "SkuMapping", "load_catalogue", "load_sku_map",
    "normalize", "RegexResult", "RegexStage", "FuzzyResult", "FuzzyStage",
]
