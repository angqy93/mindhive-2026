"""The whole matcher, without the embedding model so it runs fast."""
import csv

import pytest

from matcher import Matcher, load_catalogue, load_sku_map
from run import HOLDOUT, LABELLED

PREFIX = {"acme": "ACM-", "nordic": "NRD-"}


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def matcher():
    m = Matcher({tenant: load_catalogue(tenant) for tenant in PREFIX}, load_sku_map())
    m.fit(read(LABELLED))
    return m


@pytest.fixture(scope="module")
def holdout():
    return read(HOLDOUT)


def test_never_crosses_tenants(matcher, holdout):
    for line in read(LABELLED) + holdout:
        p = matcher.predict(line)
        codes = [p.item_code] * bool(p.item_code) + [c.split(":")[0] for c in p.candidates.split("|") if c]
        assert all(code.startswith(PREFIX[line["tenant"]]) for code in codes), line["line_id"]


def test_same_input_same_output(matcher, holdout):
    assert [matcher.predict(line) for line in holdout] == [matcher.predict(line) for line in holdout]


def test_output_follows_the_schema(matcher, holdout):
    for line in holdout:
        p = matcher.predict(line)
        assert p.decision in ("auto", "review", "reject")
        assert bool(p.item_code) == (p.decision == "auto")
        assert 0 <= p.confidence <= 1
        assert p.reason_code and " " not in p.reason_code
        assert len(p.candidates.split("|")) <= 3


def test_auto_precision_clears_break_even_on_labelled_lines(matcher):
    predictions = [(line, matcher.predict(line)) for line in read(LABELLED)]
    auto = [(line, p) for line, p in predictions if p.decision == "auto"]
    right = sum(p.item_code == line["gt_item_code"] for line, p in auto)
    assert right / len(auto) >= 0.927
