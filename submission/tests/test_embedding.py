import numpy as np
import pytest

from matcher import EmbeddingStage, load_catalogue, load_model, normalize
from matcher.data import Item


class WordModel:
    """Stand-in for the real model: one dimension per word, so tests run fast and offline."""

    def __init__(self):
        self.vocab = {}

    def encode(self, texts, normalize_embeddings=True):
        vectors = np.zeros((len(texts), 64))
        for i, text in enumerate(texts):
            for word in text.split():
                vectors[i, self.vocab.setdefault(word, len(self.vocab))] += 1
        return vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)


def item(code, name, brand):
    return Item("acme", code, name, brand, "", 1.0)


@pytest.fixture
def stage():
    catalogue = {i.item_code: i for i in [
        item("ACM-A", "Tolsen Cable Tie 300mm White", "Tolsen"),
        item("ACM-B", "Hitex Cable Tie 300mm White", "Hitex"),
        item("ACM-C", "Kanto PVC Pipe 40mm Class E", "Kanto"),
        item("ACM-D", "Kanto PVC Pipe 40mm Class D", "Kanto"),
    ]}
    return EmbeddingStage(catalogue, WordModel())


def test_word_check(stage):
    assert stage.match("40mm class").reason == "embedding_several_fit"


def test_hard_detail_check(stage):
    assert not stage.details_match("tolsen tie 300mm", stage.codes.index("ACM-B"))   # wrong brand
    assert not stage.details_match("cable tie white", stage.codes.index("ACM-A"))    # adds a size
    assert stage.details_match("tolsen tie 300mm white", stage.codes.index("ACM-A"))


def test_never_auto_without_a_measured_success_line(stage):
    result = stage.match("tolsen 300mm white")
    assert (result.reason, result.decision, result.passed_checks) == ("embedding_low_score", None, True)


def test_auto_once_the_success_line_is_cleared(stage):
    stage.success_line = 50.0
    result = stage.match("tolsen 300mm white")
    assert (result.item_code, result.reason, result.decision) == ("ACM-A", "embedding_match", "auto")


def test_real_model_sends_a_vague_line_to_a_human():
    model = load_model()
    if model is None:
        pytest.skip("pinned embedding model is not on this machine")
    result = EmbeddingStage(load_catalogue("acme"), model).match(normalize("40mm Class"))
    assert result.reason == "embedding_several_fit" and result.decision is None
