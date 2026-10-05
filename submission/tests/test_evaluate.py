"""The 5-fold cross-validation in the harness (EVAL.md section 1)."""
from evaluate import FOLDS, cross_validate, fold_sets
from matcher import Prediction


class SpyMatcher:
    """Stands in for the matcher: remembers which lines it learned from, and fails if it is
    asked to score one of them."""

    def __init__(self):
        self.learned = set()
        self.fits = []

    def fit(self, lines):
        self.learned = {line["line_id"] for line in lines}
        self.fits.append(len(lines))

    def predict(self, line):
        assert line["line_id"] not in self.learned, f"{line['line_id']} was scored by a matcher that learned from it"
        return Prediction(line["line_id"], "", 0.5, "review", "test", "")


class NoGroups:
    def groups(self, line):
        return []


def lines(n):
    return [{"line_id": f"L{i}", "tenant": "acme"} for i in range(n)]


def test_every_line_is_in_exactly_one_fold():
    folds = fold_sets(420)
    assert len(folds) == FOLDS
    assert sorted(i for fold in folds for i in fold) == list(range(420))
    assert {len(fold) for fold in folds} == {84}


def test_folds_are_the_same_every_run():
    assert fold_sets(420) == fold_sets(420)


def test_no_line_is_scored_by_a_matcher_that_learned_from_it():
    spy = SpyMatcher()
    cross_validate(spy, lines(420), {"acme": NoGroups()})
    assert spy.fits == [336] * FOLDS  # each fit learns from the other 4 folds


def test_every_line_is_scored_once_in_order():
    data = lines(420)
    scored = cross_validate(SpyMatcher(), data, {"acme": NoGroups()})
    assert [s.line["line_id"] for s in scored] == [line["line_id"] for line in data]
