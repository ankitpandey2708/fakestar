from fakestar.baselines import WEIGHTS, band_for


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_band_boundaries():
    assert band_for(0) == "LIKELY ORGANIC"
    assert band_for(25) == "LIKELY ORGANIC"
    assert band_for(26) == "SUSPICIOUS"
    assert band_for(60) == "SUSPICIOUS"
    assert band_for(61) == "LIKELY MANIPULATED"
    assert band_for(100) == "LIKELY MANIPULATED"
