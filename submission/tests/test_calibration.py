from matcher import Calibrator, success_line
from matcher.calibration import wilson_lower


def test_lower_bound_matches_design():
    # DESIGN.md section 2: 66 of 67 fuzzy answers right gives a lower bound of 93.6%.
    assert round(wilson_lower(66, 67), 3) == 0.936


def test_no_success_line_from_one_example():
    assert success_line([(80.0, True)]) is None


def test_success_line_needs_35_right_answers():
    assert success_line([(80.0, True)] * 34) is None
    assert success_line([(80.0, True)] * 35) == 80.0


def test_confidence_never_claims_certainty():
    calibrator = Calibrator([("lane", 100.0, True)] * 10 + [("junk", 10.0, False)] * 10)
    assert 0 < calibrator.confidence("junk", 10.0) < calibrator.confidence("lane", 100.0) < 1


def test_higher_score_never_gets_lower_confidence():
    calibrator = Calibrator([("fuzzy", s, s >= 50) for s in range(0, 100, 5)])
    confidences = [calibrator.confidence("fuzzy", s) for s in range(0, 100, 5)]
    assert confidences == sorted(confidences)


def test_small_group_at_the_bottom_does_not_end_up_higher():
    # The real fuzzy_low_score lines: a 1-line group (wrong) below a 5-line group (1 right).
    # +1/+2 alone gives 1/3 = 0.333 then 2/7 = 0.286, so the higher score would get less.
    scores = [61.5, 64.4, 64.7, 67.9, 67.9, 68.2]
    calibrator = Calibrator([("fuzzy_low_score", s, s == 64.4) for s in scores])
    confidences = [calibrator.confidence("fuzzy_low_score", s) for s in scores]
    assert confidences == sorted(confidences)
