from fakestar.detectors import ratios
from fakestar.detectors.ratios import analyze_ratios


def _repo(stars, forks, watchers):
    return {"stargazers_count": stars, "forks_count": forks,
            "subscribers_count": watchers}


def test_zero_threshold_does_not_crash(monkeypatch):
    # A threshold of 0 would make the severity denominator zero. The guard must
    # keep severity valid and never raise ZeroDivisionError.
    monkeypatch.setitem(ratios.THRESHOLDS, "fork_to_star", 0.0)
    sigs = {s.name: s for s in analyze_ratios(_repo(50000, 0, 1))}
    assert 0.0 <= sigs["fork_to_star"].severity <= 1.0


def test_organic_repo_does_not_trip():
    sigs = {s.name: s for s in analyze_ratios(_repo(70000, 16450, 2030))}
    assert sigs["fork_to_star"].tripped is False
    assert sigs["watcher_to_star"].tripped is False


def test_manipulated_repo_trips_both():
    sigs = {s.name: s for s in analyze_ratios(_repo(157000, 2676, 168))}
    assert sigs["fork_to_star"].tripped is True
    assert sigs["watcher_to_star"].tripped is True
    assert 0.0 < sigs["fork_to_star"].severity <= 1.0


def test_fork_ratio_ignored_below_min_stars():
    # very low fork ratio but only 500 stars -> not enough to trip
    sigs = {s.name: s for s in analyze_ratios(_repo(500, 1, 1))}
    assert sigs["fork_to_star"].tripped is False


def test_zero_stars_is_safe():
    sigs = {s.name: s for s in analyze_ratios(_repo(0, 0, 0))}
    assert sigs["fork_to_star"].tripped is False
    assert sigs["fork_to_star"].value == 0.0


def test_caveat_present():
    sigs = analyze_ratios(_repo(70000, 16450, 2030))
    assert all(s.caveat for s in sigs)

