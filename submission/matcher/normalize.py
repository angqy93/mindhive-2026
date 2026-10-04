"""Stage 0: cleans an order line before any matching. See DESIGN.md section 2."""
import re

# Trade abbreviations -> the catalogue's own wording.
ABBREVIATIONS = {
    "s/s": "stainless",
    "zp": "zinc plated",
    "fc": "full cream",
}

# Malay words found in the order lines -> the catalogue's English wording.
# Two-word phrases come first so they are replaced before their single words.
MALAY_WORDS = {
    "topi keledar": "helmet",
    "sarung tangan": "glove",
    "skru": "screw",
    "susu": "milk",
    "ayam": "chicken",
    "paip": "pipe",
    "pita": "tape",
    "mentega": "butter",
    "udang": "prawn",
    "daging": "beef",
    "putih": "white",
}

# Words that are never part of a product.
FILLER_WORDS = ("pls", "please", "need", "send", "item", "kindly", "thanks", "bro", "urgent")

# Quantity and packing words. Never part of a catalogue name ("kg" is, so it is not here).
UNIT_WORDS = ("ctn", "carton", "case", "box", "pack", "pkt")


def whole_word(word: str) -> str:
    """Regex for `word` with no letter directly before or after it."""
    return rf"(?<![a-z]){re.escape(word)}(?![a-z])"


def normalize(text: str) -> str:
    text = text.lower()

    # 1. Abbreviations and Malay words first, because S/S contains a slash.
    for short, full in ABBREVIATIONS.items():
        text = re.sub(whole_word(short), full, text)
    for malay, english in MALAY_WORDS.items():
        text = re.sub(whole_word(malay), english, text)
    text = re.sub(r"\s*" + whole_word("inch"), '"', text)
    text = text.replace("''", '"')

    # 2. Separators become spaces. A slash between two digits (3/4, 21/25) and a dash
    #    inside a word or number (19-25mm, 1-1/2) are kept.
    text = re.sub(r"(?<!\d)/|/(?!\d)", " ", text)
    text = re.sub(r"(?<!\w)-|-(?!\w)", " ", text)
    text = text.replace(":", " ")              # "item: ..."
    text = re.sub(r"^\s*\d+\)", " ", text)     # list numbering such as "1) ..."

    # 3. Remove filler words, then quantity wording, then an "x + number" left at the end.
    for word in FILLER_WORDS:
        text = re.sub(whole_word(word), " ", text)
    for unit in UNIT_WORDS:
        text = re.sub(whole_word(unit), " ", text)
    text = re.sub(r"(?<![a-z0-9])x\s?\d+\s*$", "", text.strip())

    return " ".join(text.split())
