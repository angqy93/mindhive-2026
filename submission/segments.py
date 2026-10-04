"""Noise groups for the evaluation harness. See EVAL.md section 1.

The data does not say what kind of mess a line has, so each group is detected from the line
itself. A line can be in several groups (e.g. a Malay word and a typo). Two groups come from a
hand-made list, because telling them apart needs judgement: lines that are not an order, and
products the company does not sell.
"""
import re

from rapidfuzz.distance import OSA

from matcher import Item, normalize
from matcher.normalize import ABBREVIATIONS, FILLER_WORDS, MALAY_WORDS, UNIT_WORDS, whole_word

GROUPS = ("clean", "barcode", "buyer_sku", "typo", "malay", "abbreviation", "formatting",
          "quantities_included", "incomplete_order", "not_an_order", "not_in_catalogue")

# Tagged by hand from the training lines.
NOT_AN_ORDER = {
    "same as last month order", "subtotal", "thanks bro", "pls confirm stock first", "po attached",
    "kindly quote best price", "deliver by friday please", "delivery charge", "----",
    "attn: purchasing dept",
}
NOT_IN_CATALOGUE = {
    "cadbury dairy milk 165g", "epson 003 ink black bottle", "copper pipe 22mm x 3m class 2",
    "wagyu striploin mb7 grain fed", "nescafe gold refill 170g", "duracell aa battery 8 pack",
    "3m 8210 n95 respirator box 20", "makita ls1040 mitre saw 240v",
}

# List numbering, a leading dash or "item:", spaced dashes, double spaces, slashes between words.
FORMATTING = re.compile(r"^\s*(\d+\)|-\s|item:)|\s-\s|\s{2,}|(?<!\d)/|/(?!\d)")
QUANTITY = re.compile(r"(?<![a-z0-9])x\s?\d+\s*$|" + "|".join(whole_word(w) for w in UNIT_WORDS))


class Segmenter:
    """Built once per tenant from its catalogue."""

    def __init__(self, catalogue: dict[str, Item]):
        self.names = {item.item_name.lower() for item in catalogue.values()}
        self.item_words = [set(normalize(item.item_name).split()) for item in catalogue.values()]
        self.vocab = set().union(*self.item_words)

    def groups(self, line: dict) -> list[str]:
        raw = line["raw_text"]
        lower = raw.lower()
        if lower.strip() in NOT_AN_ORDER:
            return ["not_an_order"]
        if lower.strip() in NOT_IN_CATALOGUE:
            return ["not_in_catalogue"]

        words = normalize(raw).split()
        unknown = [w for w in words if w not in self.vocab]
        found = []
        if " ".join(lower.split()) in self.names and raw == " ".join(raw.split()):
            found.append("clean")
        if line["raw_barcode"].strip() or re.search(r"\d{8,14}", raw):
            found.append("barcode")
        if line["buyer_sku"].strip():
            found.append("buyer_sku")
        # One letter off a catalogue word (a swap of two letters counts as one). Words with digits
        # are left out: "22mm" vs "24mm" is a different size, not a typo. Short words are left out:
        # "fed" vs "red" is a different word.
        if any(w.isalpha() and len(w) >= 4 and any(OSA.distance(w, v) == 1 for v in self.vocab)
               for w in unknown):
            found.append("typo")
        if any(re.search(whole_word(w), lower) for w in MALAY_WORDS):
            found.append("malay")
        if any(re.search(whole_word(w), lower) for w in ABBREVIATIONS):
            found.append("abbreviation")
        if FORMATTING.search(raw) or any(re.search(whole_word(w), lower) for w in FILLER_WORDS):
            found.append("formatting")
        if QUANTITY.search(lower) or line["notes"].strip():
            found.append("quantities_included")
        # Every word is a real catalogue word, but the line leaves out part of the item's name.
        if words and not unknown and any(set(words) < item for item in self.item_words):
            found.append("incomplete_order")
        # Nothing above explains why the line is not exactly an item name, so some word is wrong:
        # trade wording ("SS304" for "Stainless 304"), words stuck together, or a short-word typo.
        return found or ["typo"]
