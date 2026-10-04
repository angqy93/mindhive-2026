from matcher import normalize


def test_abbreviations_are_expanded():
    assert normalize("S/S Hex Bolt ZP") == "stainless hex bolt zinc plated"


def test_malay_words_are_translated_and_filler_removed():
    assert normalize("susu full cream 1L pls") == "milk full cream 1l"


def test_spaced_dashes_and_unit_words_are_removed():
    assert normalize("Skru - 10 - ctn") == "screw 10"


def test_trailing_quantity_is_removed():
    assert normalize("tolsen wall plug 6mm x 10") == "tolsen wall plug 6mm"


def test_two_single_quotes_become_an_inch_mark():
    assert normalize("1'' tape") == '1" tape'


def test_a_line_of_only_filler_is_empty():
    assert normalize("thanks bro") == ""
