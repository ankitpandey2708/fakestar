import json
from datetime import datetime, timezone

import pytest

from fakestar.cli import main, parse_args, resolve_token, run
from fakestar.github import RepoNotFound


def test_parse_args_defaults():
    a = parse_args(["octocat/hello"])
    assert a.repo == "octocat/hello"
    assert a.sample == "auto"          # sized from star count unless overridden
    assert a.margin == 0.08
    assert a.max_sample == 150
    assert a.timeline_pages == 40
    assert a.json is False


def test_parse_args_explicit_sample():
    a = parse_args(["octocat/hello", "--sample", "300"])
    assert a.sample == 300


def test_parse_args_rejects_bad_margin():
    with pytest.raises(SystemExit):  # argparse exits on invalid value
        parse_args(["octocat/hello", "--margin", "0"])


def test_parse_args_json_and_verbose_are_mutually_exclusive():
    with pytest.raises(SystemExit):  # both pick an output format
        parse_args(["octocat/hello", "--json", "--verbose"])


class FakeClient:
    def __init__(self, repo, users, timestamps, fail=None, contributors=50):
        self._repo, self._users, self._ts, self._fail = repo, users, timestamps, fail
        self._contributors = contributors

    def get_repo(self, o, r):
        if self._fail == "404":
            raise RepoNotFound("x")
        return self._repo

    def count_contributors(self, o, r):
        return self._contributors

    def iter_stargazers(self, o, r, with_timestamps=False, max_pages=None):
        # temporal detector path (timestamps only)
        for t in self._ts:
            yield {"starred_at": t, "user": {"login": "x"}}

    def get_stargazer_page(self, o, r, page, per_page=100):
        start = (page - 1) * per_page
        return [{"login": u["login"]} for u in self._users[start:start + per_page]]

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


def test_resolve_token_precedence(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    # explicit flag wins over everything
    assert resolve_token("flag", gh_token=lambda: "gh") == "flag"
    # env beats gh
    monkeypatch.setenv("GITHUB_TOKEN", "envtok")
    assert resolve_token(None, gh_token=lambda: "gh") == "envtok"
    monkeypatch.delenv("GITHUB_TOKEN")
    # GH_TOKEN also honored
    monkeypatch.setenv("GH_TOKEN", "ghenv")
    assert resolve_token(None, gh_token=lambda: "gh") == "ghenv"
    monkeypatch.delenv("GH_TOKEN")
    # falls back to gh CLI, then to None
    assert resolve_token(None, gh_token=lambda: "ghcli") == "ghcli"
    assert resolve_token(None, gh_token=lambda: None) is None


def test_main_requires_a_token(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("fakestar.cli._gh_token", lambda: None)  # no gh fallback
    rc = main(["o/r"])  # no token -> error out before any network call
    assert rc == 3
    assert "token" in capsys.readouterr().err.lower()


def test_run_reports_actual_sample_size_not_requested():
    # repo has only 7 stargazers; a full run (default --sample 150) must report
    # the 7 actually analyzed, not the requested cap.
    repo = {"stargazers_count": 7, "forks_count": 1, "subscribers_count": 1}
    client = FakeClient(repo, _ghosty_users(7), [])
    v = run(parse_args(["o/r"]), client)
    assert v.sample_size == 7


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
