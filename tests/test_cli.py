import json
from datetime import datetime, timezone

import pytest

from fakestar.cli import parse_args, run
from fakestar.github import RepoNotFound


def test_parse_args_defaults():
    a = parse_args(["octocat/hello"])
    assert a.repo == "octocat/hello"
    assert a.sample == 150
    assert a.timeline_pages == 40
    assert a.ratios_only is False
    assert a.json is False


class FakeClient:
    def __init__(self, repo, users, timestamps, fail=None):
        self._repo, self._users, self._ts, self._fail = repo, users, timestamps, fail

    def get_repo(self, o, r):
        if self._fail == "404":
            raise RepoNotFound("x")
        return self._repo

    def iter_stargazers(self, o, r, with_timestamps=False, max_pages=None):
        if with_timestamps:
            for t in self._ts:
                yield {"starred_at": t, "user": {"login": "x"}}
        else:
            for u in self._users:
                yield {"login": u["login"]}

    def get_user(self, login):
        return next(u for u in self._users if u["login"] == login)


def _ghosty_users(n):
    return [{"login": f"g{i}", "created_at": "2023-01-01T00:00:00Z",
             "public_repos": 0, "followers": 0, "bio": ""} for i in range(n)]


def test_run_manipulated_repo(monkeypatch):
    repo = {"stargazers_count": 157000, "forks_count": 2676, "subscribers_count": 168}
    ts = ["2024-07-01T00:00:00Z"] * 60 + ["2024-07-%02dT00:00:00Z" % d
                                          for d in range(2, 42)]
    client = FakeClient(repo, _ghosty_users(150), ts)
    # freeze "now" so 2023-01-01 accounts appear < 365 days old (making them suspicious)
    fixed_now = datetime(2023, 6, 1, tzinfo=timezone.utc)
    monkeypatch.setattr("fakestar.detectors.profiles.datetime",
                        type("dt", (), {"now": staticmethod(lambda tz=None: fixed_now),
                                        "strptime": staticmethod(datetime.strptime)})())
    args = parse_args(["o/r"])
    v = run(args, client)
    assert v.band == "LIKELY MANIPULATED"
    assert v.score >= 61


def test_run_repo_not_found_short_circuits():
    client = FakeClient({}, [], [], fail="404")
    v = run(parse_args(["o/r"]), client)
    assert "deleted" in " ".join(v.notes).lower() or "not found" in " ".join(v.notes).lower()
    assert v.band == "LIKELY MANIPULATED"


def test_run_ratios_only_skips_sampling():
    repo = {"stargazers_count": 70000, "forks_count": 16450, "subscribers_count": 2030}
    client = FakeClient(repo, [], [])
    v = run(parse_args(["o/r", "--ratios-only"]), client)
    names = {s.name for s in v.signals}
    assert names == {"fork_to_star", "watcher_to_star"}


def test_run_ratios_only_reports_zero_sample():
    repo = {"stargazers_count": 70000, "forks_count": 16450, "subscribers_count": 2030}
    client = FakeClient(repo, [], [])
    v = run(parse_args(["o/r", "--ratios-only"]), client)
    assert v.sample_size == 0


def test_run_detector_failure_is_tolerated():
    repo = {"stargazers_count": 70000, "forks_count": 16450, "subscribers_count": 2030}

    class Boom(FakeClient):
        def get_user(self, login):
            raise RuntimeError("boom")

    client = Boom(repo, _ghosty_users(5), [])
    v = run(parse_args(["o/r"]), client)
    # profiles failed but ratios still present and a note recorded
    assert any(s.name == "fork_to_star" for s in v.signals)
    assert any("profile" in n.lower() for n in v.notes)
