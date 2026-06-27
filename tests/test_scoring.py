from fakestar.baselines import WEIGHTS, band_for
from fakestar.scoring import ANCHORS
from fakestar.models import Signal
from fakestar.scoring import score_signals


def _sig(name, value, severity=0.0, tripped=False):
    return Signal(name, value, 0.0, 0.0, WEIGHTS.get(name, 100), tripped, severity, "d")


def _fake(name):
    return _sig(name, ANCHORS[name][1])      # value at the fake anchor -> severity 1


def _organic(name):
    return _sig(name, ANCHORS[name][0])      # value at the organic anchor -> severity 0


def test_no_signals_scores_zero_and_organic():
    v = score_signals([], repo="o/r", sample_size=150)
    assert v.score == 0
    assert v.band == "LIKELY ORGANIC"


def test_repo_deleted_is_hard_manipulated():
    sig = Signal("repo_deleted", 1.0, 0.0, 0.0, 100, True, 1.0, "404")
    v = score_signals([sig], repo="o/r", sample_size=0)
    assert v.band == "LIKELY MANIPULATED" and v.score == 100


def test_fake_stargazer_population_is_manipulated():
    sigs = [_fake("zero_followers_pct"), _fake("ghost_pct"), _fake("zero_repos_pct")]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.band == "LIKELY MANIPULATED"
    # shrinkage pulls a fake-anchor value slightly back, so ~88 not exactly 100
    assert v.stargazer_score >= 80 and v.usage_score is None


def test_organic_stargazers_are_organic():
    sigs = [_organic("zero_followers_pct"), _organic("ghost_pct")]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.band == "LIKELY ORGANIC"
    assert v.stargazer_score == 0


def test_low_sample_clean_is_uncertain():
    v = score_signals([_organic("zero_followers_pct")], repo="o/r", sample_size=3)
    assert v.band == "UNCERTAIN"
    assert v.stargazer_score is None      # abstained


def test_low_sample_does_not_mask_usage_flag():
    # usage axis is exact (not sampled) -> a fork-starved repo still flags at low n
    v = score_signals([_fake("fork_to_star")], repo="o/r", sample_size=2)
    assert v.band == "LIKELY MANIPULATED"


def test_uncalibrated_signal_is_not_scored():
    sig = _sig("low_contributors", 1.0, severity=1.0, tripped=True)
    v = score_signals([sig], repo="o/r", sample_size=150)
    assert v.score == 0 and v.usage_score is None


def test_band_cutpoints():
    assert band_for(18) == "LIKELY ORGANIC"
    assert band_for(19) == "SUSPICIOUS"
    assert band_for(44) == "SUSPICIOUS"
    assert band_for(45) == "LIKELY MANIPULATED"


def test_notes_passed_through():
    v = score_signals([], repo="o/r", sample_size=150, notes=["x"])
    assert v.notes == ["x"]
