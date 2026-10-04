"""Stage 1: exact lookups by barcode, buyer SKU and item name. See DESIGN.md section 2."""
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .data import CustomerKey, Item, SkuMapping
from .normalize import normalize

TRUSTED_SOURCES = ("confirmed_order", "manual_import")

# A barcode typed inside the text: a run of 8 to 14 digits (EAN-8 up to GTIN-14).
EMBEDDED_BARCODE = re.compile(r"(?<!\d)\d{8,14}(?!\d)")


@dataclass(frozen=True)
class RegexResult:
    item_code: str | None   # None when no exact match was found
    reason: str | None      # "barcode_hit", "sku_map_hit", "name_exact" or "ambiguous_twins"
    decision: str | None    # "auto" or "review", None when nothing was found
    text: str               # cleaned line text, handed to fuzzy matching if nothing was found
    candidates: tuple[tuple[str, float], ...] = ()  # (item_code, score) a reviewer chooses between, for "review"


def is_trusted(mapping: SkuMapping) -> bool:
    """confirmed_order and manual_import always; inferred_match only at confidence 1.0."""
    return mapping.source in TRUSTED_SOURCES or mapping.confidence == 1.0


class RegexStage:
    """Built once per tenant, then used for every order line of that tenant."""

    def __init__(self, tenant: str, catalogue: dict[str, Item],
                 sku_map: dict[CustomerKey, dict[str, list[SkuMapping]]]):
        self.tenant = tenant
        self.catalogue = catalogue
        self.sku_map = sku_map
        self.barcodes = {item.barcode: code for code, item in catalogue.items() if item.barcode}
        self.cleaned = {code: normalize(item.item_name) for code, item in catalogue.items()}
        self.names = {name: code for code, name in self.cleaned.items()}

    def match(self, line: dict) -> RegexResult:
        text = line["raw_text"]

        # 1. Barcode: the barcode field first, then any barcode typed inside the text.
        for barcode in (line["raw_barcode"].strip(), *EMBEDDED_BARCODE.findall(text)):
            item_code = self.barcodes.get(barcode)
            if item_code:
                return RegexResult(item_code, "barcode_hit", "auto", normalize(text))

        # 2. Buyer SKU, looked up in this customer's own map only.
        customer_skus = self.sku_map.get((self.tenant, line["customer_id"]), {})
        for mapping in customer_skus.get(line["buyer_sku"].strip(), []):
            if not is_trusted(mapping):
                # inferred_match below 1.0: the customer's number becomes its description
                text = f"{text} {mapping.description}"
            elif mapping.item_code in self.catalogue:
                return RegexResult(mapping.item_code, "sku_map_hit", "auto", normalize(text))

        # 3. Exact item name.
        cleaned = normalize(text)
        item_code = self.names.get(cleaned)
        if item_code:
            variants = [code for name, code in self.names.items() if name.startswith(cleaned + " ")]
            if variants:
                # Other items extend this name (e.g. "(Bulk)"), and the line doesn't say which one.
                scored = tuple((code, fuzz.ratio(cleaned, self.cleaned[code])) for code in (item_code, *variants))
                return RegexResult(item_code, "ambiguous_twins", "review", cleaned, scored)
            return RegexResult(item_code, "name_exact", "auto", cleaned)

        return RegexResult(None, None, None, cleaned)
