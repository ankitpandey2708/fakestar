import pytest

from fakestar.github import GitHubClient, GitHubServerError, RepoNotFound, RateLimited


class FakeResp:
    def __init__(self, status, body=None, headers=None, links=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.links = links or {}

    def json(self):
        return self._body


class FakeSession:
    """Returns queued responses in order; records requested URLs."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return self._responses.pop(0)


class UserSession:
    """Stateless, thread-safe: responds per user login parsed from the URL."""
    def __init__(self, missing=()):
        self._missing = set(missing)

    def get(self, url, headers=None, timeout=None):
        login = url.rstrip("/").split("/")[-1]
        if login in self._missing:
            return FakeResp(404, {})
        return FakeResp(200, {"login": login, "followers": 1})


def test_get_repo_returns_json():
    sess = FakeSession([FakeResp(200, {"stargazers_count": 100})])
    c = GitHubClient(token="t", session=sess)
    assert c.get_repo("o", "r")["stargazers_count"] == 100


def test_get_stargazer_page_builds_url_with_page():
    sess = FakeSession([FakeResp(200, [{"login": "a"}])])
    c = GitHubClient(token="t", session=sess)
    page = c.get_stargazer_page("o", "r", 3)
    assert page == [{"login": "a"}]
    assert "page=3" in sess.urls[0]
    assert "per_page=100" in sess.urls[0]


def test_get_users_fetches_all_concurrently():
    c = GitHubClient(token="t", session=UserSession())
    out = c.get_users(["a", "b", "c"], workers=3)
    assert set(out) == {"a", "b", "c"}
    assert out["b"]["login"] == "b"


def test_get_users_skips_404_accounts():
    c = GitHubClient(token="t", session=UserSession(missing={"ghost"}))
    out = c.get_users(["a", "ghost", "b"], workers=2)
    assert set(out) == {"a", "b"}  # deleted account dropped, others kept


def test_count_contributors_reads_last_page_number():
    sess = FakeSession([FakeResp(200, [{"login": "a"}],
                                  links={"last": {"url": "https://api/x?per_page=1&page=237"}})])
    c = GitHubClient(token="t", session=sess)
    assert c.count_contributors("o", "r") == 237


def test_count_contributors_single_page():
    sess = FakeSession([FakeResp(200, [{"login": "a"}])])  # no Link -> 1 contributor
    c = GitHubClient(token="t", session=sess)
    assert c.count_contributors("o", "r") == 1


def test_get_repo_404_raises():
    sess = FakeSession([FakeResp(404, {"message": "Not Found"})])
    c = GitHubClient(token="t", session=sess)
    with pytest.raises(RepoNotFound):
        c.get_repo("o", "r")


def test_rate_limit_raises_with_reset():
    sess = FakeSession([FakeResp(403, {}, headers={
        "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})])
    c = GitHubClient(token="t", session=sess)
    with pytest.raises(RateLimited) as ei:
        c.get_repo("o", "r")
    assert ei.value.reset_ts == 1700000000


def test_rate_limit_waits_and_retries_when_enabled():
    calls = []
    sess = FakeSession([
        FakeResp(403, {}, headers={
            "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"}),
        FakeResp(200, {"ok": True}),
    ])
    c = GitHubClient(token="t", session=sess,
                     sleeper=lambda s: calls.append(s), wait=True)
    assert c.get_repo("o", "r") == {"ok": True}
    assert len(calls) == 1  # slept once through the rate-limit window, then retried


def test_rate_limit_wait_gives_up_after_max():
    # window never reopens: still raises rather than looping forever
    responses = [FakeResp(403, {}, headers={
        "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})
        for _ in range(10)]
    sess = FakeSession(responses)
    c = GitHubClient(token="t", session=sess, sleeper=lambda _s: None, wait=True)
    with pytest.raises(RateLimited):
        c.get_repo("o", "r")


def test_iter_stargazers_follows_pagination():
    page1 = FakeResp(200, [{"login": "a"}, {"login": "b"}],
                     links={"next": {"url": "https://api/page2"}})
    page2 = FakeResp(200, [{"login": "c"}])
    sess = FakeSession([page1, page2])
    c = GitHubClient(token="t", session=sess)
    logins = [u["login"] for u in c.iter_stargazers("o", "r")]
    assert logins == ["a", "b", "c"]


def test_iter_stargazers_respects_max_pages():
    page1 = FakeResp(200, [{"login": "a"}],
                     links={"next": {"url": "https://api/page2"}})
    page2 = FakeResp(200, [{"login": "b"}])
    sess = FakeSession([page1, page2])
    c = GitHubClient(token="t", session=sess)
    logins = [u["login"] for u in c.iter_stargazers("o", "r", max_pages=1)]
    assert logins == ["a"]


def test_5xx_retries_then_succeeds():
    sess = FakeSession([FakeResp(502, {}), FakeResp(200, {"ok": True})])
    c = GitHubClient(token="t", session=sess, sleeper=lambda _s: None)
    assert c.get_repo("o", "r") == {"ok": True}


def test_5xx_exhausted_raises():
    sess = FakeSession([FakeResp(502, {}), FakeResp(502, {}), FakeResp(502, {})])
    c = GitHubClient(token="t", session=sess, sleeper=lambda _s: None)
    with pytest.raises(GitHubServerError) as ei:
        c.get_repo("o", "r")
    assert ei.value.status == 502

