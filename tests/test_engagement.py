from datetime import datetime, timedelta, timezone

from fakestar.detectors.engagement import analyze_engagement

NOW = datetime(2026, 6, 26, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, contributors):
        self._contributors = contributors

    def count_contributors(self, owner, repo):
        return self._contributors


def _repo(stars, open_issues, pushed_days_ago):
    pushed = (NOW - timedelta(days=pushed_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"stargazers_count": stars, "open_issues_count": open_issues,
            "pushed_at": pushed}


def test_high_stars_few_contributors_trips():
    sigs = {s.name: s for s in analyze_engagement(
        FakeClient(2), "o", "r", _repo(50000, 800, 10), now=NOW)}
    assert sigs["low_contributors"].tripped is True
    assert 0.0 < sigs["low_contributors"].severity <= 1.0


def test_small_repo_few_contributors_does_not_trip():
    # below MIN_STARS_FOR_RATIO -> gate prevents flagging a small solo project
    sigs = {s.name: s for s in analyze_engagement(
        FakeClient(1), "o", "r", _repo(500, 0, 10), now=NOW)}
    assert sigs["low_contributors"].tripped is False


def test_stale_repo_trips():
    sigs = {s.name: s for s in analyze_engagement(
        FakeClient(100), "o", "r", _repo(50000, 800, 800), now=NOW)}
    assert sigs["commit_staleness"].tripped is True


def test_recent_push_does_not_trip_staleness():
    sigs = {s.name: s for s in analyze_engagement(
        FakeClient(100), "o", "r", _repo(50000, 800, 5), now=NOW)}
    assert sigs["commit_staleness"].tripped is False


def test_missing_pushed_at_is_safe():
    repo = {"stargazers_count": 50000, "open_issues_count": 800}  # no pushed_at
    sigs = {s.name: s for s in analyze_engagement(FakeClient(100), "o", "r", repo, now=NOW)}
    assert sigs["commit_staleness"].tripped is False
    assert sigs["commit_staleness"].value == 0.0


def test_high_stars_near_zero_issues_trips():
    sigs = {s.name: s for s in analyze_engagement(
        FakeClient(100), "o", "r", _repo(50000, 0, 5), now=NOW)}
    assert sigs["low_issues"].tripped is True


def test_healthy_repo_trips_nothing():
    # many contributors, recent push, healthy issue ratio
    sigs = analyze_engagement(FakeClient(120), "o", "r", _repo(50000, 1500, 5), now=NOW)
    assert all(s.tripped is False for s in sigs)
