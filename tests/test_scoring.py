from fakestar.models import Signal
from fakestar.scoring import score_signals


def _sig(name, weight, severity, tripped=True):
    return Signal(name, 0.0, 0.0, 0.0, weight, tripped, severity, "d")


def test_no_signals_scores_zero_and_organic():
    v = score_signals([], repo="o/r", sample_size=0)
    assert v.score == 0
    assert v.band == "LIKELY ORGANIC"


def test_full_severity_all_signals_caps_at_100():
    sigs = [_sig("a", 30, 1.0), _sig("b", 25, 1.0), _sig("c", 20, 1.0),
            _sig("d", 15, 1.0), _sig("e", 10, 1.0)]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.score == 100
    assert v.band == "LIKELY MANIPULATED"


def test_partial_severity_sums_proportionally():
    # 30*0.5 + 25*0.4 = 15 + 10 = 25 -> ORGANIC boundary
    sigs = [_sig("a", 30, 0.5), _sig("b", 25, 0.4)]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.score == 25
    assert v.band == "LIKELY ORGANIC"


def test_notes_passed_through():
    v = score_signals([], repo="o/r", sample_size=0, notes=["x"])
    assert v.notes == ["x"]
