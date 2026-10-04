import pytest

from matcher import FuzzyStage, RegexStage, decide, load_catalogue, load_sku_map, normalize


@pytest.fixture(scope="module")
def acme():
    catalogue = load_catalogue("acme")
    return RegexStage("acme", catalogue, load_sku_map()), FuzzyStage(catalogue)


def line(raw_text="", customer_id="CUST-001", buyer_sku="", raw_barcode=""):
    return {"raw_text": raw_text, "customer_id": customer_id, "buyer_sku": buyer_sku, "raw_barcode": raw_barcode}


def test_barcode_field(acme):
    result = acme[0].match(line("anything", raw_barcode="903801726452"))
    assert (result.item_code, result.reason, result.decision) == ("ACM-HEXB0936", "barcode_hit", "auto")


def test_barcode_typed_inside_the_text(acme):
    result = acme[0].match(line("pls send 903801726452 x 5"))
    assert (result.item_code, result.reason) == ("ACM-HEXB0936", "barcode_hit")


def test_trusted_buyer_sku(acme):
    result = acme[0].match(line("whatever", buyer_sku="001444143"))
    assert (result.item_code, result.reason, result.decision) == ("ACM-SELF0590", "sku_map_hit", "auto")


def test_untrusted_buyer_sku_becomes_its_description(acme):
    # inferred_match at confidence 0.72: not trusted, so no SKU answer, but the description is added.
    result = acme[0].match(line("", buyer_sku="001633956"))
    assert result.reason != "sku_map_hit"
    assert "hex bolt m8x50" in result.text


def test_twins_go_to_review_with_every_variant(acme):
    result = acme[0].match(line("Vermont PVC Pipe 50mm Class D x12 case"))
    assert (result.reason, result.decision) == ("ambiguous_twins", "review")
    assert {code for code, _ in result.candidates} == {"ACM-PVCP1055", "ACM-PVCP1055B"}


def test_gap_check_catches_a_typo_in_the_size(acme):
    # "3700mm" scores the same against the 300mm and 370mm cable ties.
    assert acme[1].match(normalize("tolsen cable tie 3700mm white")).reason == "ambiguous_near_tie"


def test_word_check_catches_a_line_that_fits_several_items(acme):
    assert acme[1].match(normalize("tolsen hex bolt m8x50")).reason == "ambiguous_several_fit"


def test_empty_line_is_not_an_item(acme):
    regex = acme[0].match(line("thanks bro"))
    d = decide(regex, acme[1].match(regex.text))
    assert (d.decision, d.reason_code, d.item_code) == ("reject", "not_an_item", "")
