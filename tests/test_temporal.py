from fakestar.detectors.temporal import analyze_temporal, detect_burst


def _ts(day):
    return f"2024-07-{day:02d}T12:00:00Z"


def test_detect_burst_spike():
    # 90 stars on one day, 10 spread across 10 days (median daily count = 1,
    # k*median = 20, only day 1 exceeds it -> 90/100 burst fraction)
    spike = [_ts(1)] * 90 + [_ts(d) for d in range(2, 12)]
    frac, _ = detect_burst(spike)
    assert frac == 0.9


def test_detect_burst_even_distribution_no_burst():
    # 1 per day for 20 days: median = 1, no day exceeds 20*median -> no burst
    even = [_ts(d) for d in range(1, 21)]
    frac, _ = detect_burst(even)
    assert frac == 0.0


def test_detect_burst_single_day_is_max():
    # everything on one day -> degenerate guard returns full burst
    frac, _ = detect_burst([_ts(1)] * 50)
    assert frac == 1.0


def test_detect_burst_empty():
    frac, _ = detect_burst([])
    assert frac == 0.0


class FakeClient:
    def __init__(self, timestamps):
        self._ts = timestamps

    def iter_stargazers(self, owner, repo, with_timestamps=False, max_pages=None):
        for t in self._ts:
            yield {"starred_at": t, "user": {"login": "x"}}


def test_analyze_temporal_trips_on_spike():
    spike = ["2024-07-01T00:00:00Z"] * 60 + ["2024-07-%02dT00:00:00Z" % d
                                             for d in range(2, 42)]
    sig = analyze_temporal(FakeClient(spike), "o", "r")[0]
    assert sig.name == "temporal_burst"
    assert sig.tripped is True


def test_analyze_temporal_clean():
    even = ["2024-07-%02dT00:00:00Z" % d for d in range(1, 29)]
    sig = analyze_temporal(FakeClient(even), "o", "r")[0]
    assert sig.tripped is False


def test_analyze_temporal_empty_safe():
    sig = analyze_temporal(FakeClient([]), "o", "r")[0]
    assert sig.tripped is False
    assert sig.value == 0.0
