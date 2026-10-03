"""Loads the catalogues and the buyer SKU map, and removes rows that are not real products.

Follows DESIGN.md section 2 ("Before searching", stage 1) and section 4, failure mode 5.
"""
import csv
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

CustomerKey = tuple[str, str]  # (tenant, customer_id)


@dataclass(frozen=True)
class Item:
    tenant: str
    item_code: str
    item_name: str
    brand: str
    barcode: str
    list_price: float


@dataclass(frozen=True)
class SkuMapping:
    item_code: str     # already switched from -OLD to the replacement
    source: str        # confirmed_order, manual_import or inferred_match
    confidence: float
    description: str   # the customer's own description, e.g. "Squid Raw 2Kg"


def load_catalogue(tenant: str) -> dict[str, Item]:
    """Returns the tenant's real, active items, keyed by item_code.

    Skips old items (disabled = 1) and junk rows such as DELIVERY FEE (list_price = 0).
    """
    items = {}
    with open(DATA_DIR / f"catalogue_{tenant}.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            list_price = float(row["list_price"] or 0)
            if row["disabled"] == "1" or list_price == 0:
                continue
            items[row["item_code"]] = Item(
                tenant=tenant,
                item_code=row["item_code"],
                item_name=row["item_name"],
                brand=row["brand"],
                barcode=row["barcode"],
                list_price=list_price,
            )
    return items


def load_sku_map() -> dict[CustomerKey, dict[str, list[SkuMapping]]]:
    """Grouped by customer first, then by that customer's own SKU.

    Lookups always start from (tenant, customer_id), so they can never reach
    another tenant's or another customer's mappings. Mappings that point to an
    old item are switched to its replacement (the same code without -OLD).
    """
    sku_map = {}
    with open(DATA_DIR / "customer_sku_map.csv", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            # Every end date in this data (2026-03-31) is before every order
            # (2026-04-01 onward), so a mapping with an end date has expired.
            if row["valid_to"]:
                continue
            customer = (row["tenant"], row["customer_id"])
            mapping = SkuMapping(
                item_code=row["item_code"].removesuffix("-OLD"),
                source=row["source"],
                confidence=float(row["confidence"]),
                description=row["customer_description"],
            )
            sku_map.setdefault(customer, {}).setdefault(row["customer_sku"], []).append(mapping)
    return sku_map
