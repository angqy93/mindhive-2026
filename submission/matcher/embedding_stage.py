"""Stage 3: embeddings, for lines whose words don't overlap the catalogue. See DESIGN.md sections 2 and 3."""
import re
from dataclasses import dataclass

import numpy as np

from .data import Item
from .normalize import normalize, whole_word

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# Pinned to one exact version of the model, so the same line always gets the same vector.
MODEL_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"

# The second-best candidate within this many points of the best counts as a tie (as in fuzzy).
TIE_GAP = 1

NUMBER = re.compile(r"\d+(?:\.\d+)?")


def load_model(name: str = MODEL_NAME, revision: str = MODEL_REVISION):
    """Loads the pinned model from this machine only, never the network. None if it isn't there."""
    try:
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(name, revision=revision, local_files_only=True)
    except Exception:
        return None


@dataclass(frozen=True)
class EmbeddingResult:
    item_code: str | None   # best candidate, None when the stage could not run
    reason: str             # "embedding_match", "embedding_several_fit", "embedding_near_tie", "embedding_detail_mismatch",
                            # "embedding_variants", "embedding_low_score" or "embedding_unavailable"
    decision: str | None    # "auto", or None: the line keeps fuzzy's decision, with these candidates
    passed_checks: bool     # True when the word, gap, hard-detail and variants checks all passed
    score: float            # cosine similarity x 100
    candidates: tuple[tuple[str, float], ...] = ()


class EmbeddingStage:
    """Built once per tenant. Only runs on lines that fuzzy scored in the failure zone.

    success_line is the lowest similarity at which auto answers reach 92.7% precision, measured
    on the labelled lines (calibration.success_line). None means it never auto-answers.
    """

    def __init__(self, catalogue: dict[str, Item], model, success_line: float | None = None):
        self.model = model
        self.success_line = success_line
        self.codes = list(catalogue)
        self.names = [normalize(catalogue[code].item_name) for code in self.codes]
        self.brands = [normalize(catalogue[code].brand) for code in self.codes]
        self.all_brands = {brand for brand in self.brands if brand}
        self.words = [set(name.split()) for name in self.names]
        self.vectors = model.encode(self.names, normalize_embeddings=True)

    def match(self, text: str) -> EmbeddingResult:
        # No time limit here: it would make the answer depend on how fast the machine is.
        # Time per line is measured and reported instead (run.py).
        try:
            vector = self.model.encode([text], normalize_embeddings=True)[0]
        except Exception:
            return EmbeddingResult(None, "embedding_unavailable", None, False, 0.0)

        similarity = self.vectors @ vector * 100
        top = np.argsort(-similarity)[:3]
        candidates = tuple((self.codes[i], round(float(similarity[i]), 1)) for i in top)
        best = top[0]
        best_code, best_score = candidates[0]

        # Word check (as in fuzzy): more than one item contains every word of the line,
        # e.g. "40mm class" fits 23 pipes.
        line_words = set(text.split())
        if sum(line_words <= words for words in self.words) >= 2:
            reason = "embedding_several_fit"
        # Gap check: the model can't tell the top two apart.
        elif len(candidates) > 1 and best_score - candidates[1][1] <= TIE_GAP:
            reason = "embedding_near_tie"
        # Hard-detail check: a brand or number in the line must be in the candidate, and the
        # candidate must not add a number the line doesn't have (e.g. "Pantry Milk" -> a 1L item).
        elif not self.details_match(text, best):
            reason = "embedding_detail_mismatch"
        # Unique item names: other items extend the candidate's name, e.g. "(Bulk)".
        elif any(name.startswith(self.names[best] + " ") for name in self.names):
            reason = "embedding_variants"
        elif self.success_line is None or best_score < self.success_line:
            return EmbeddingResult(best_code, "embedding_low_score", None, True, best_score, candidates)
        else:
            return EmbeddingResult(best_code, "embedding_match", "auto", True, best_score, candidates)
        return EmbeddingResult(best_code, reason, None, False, best_score, candidates)

    def details_match(self, text: str, index: int) -> bool:
        named = [brand for brand in self.all_brands if re.search(whole_word(brand), text)]
        if named and self.brands[index] not in named:
            return False
        return set(NUMBER.findall(text)) == set(NUMBER.findall(self.names[index]))
