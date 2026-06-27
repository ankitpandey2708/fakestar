from fakestar.baselines import WEIGHTS, band_for


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_band_boundaries():
    assert band_for(0) == "LIKELY ORGANIC"
    assert band_for(18) == "LIKELY ORGANIC"
    assert band_for(19) == "SUSPICIOUS"
    assert band_for(44) == "SUSPICIOUS"
    assert band_for(45) == "LIKELY MANIPULATED"
    assert band_for(100) == "LIKELY MANIPULATED"
