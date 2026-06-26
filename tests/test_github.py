import pytest

from fakestar.github import GitHubClient, RepoNotFound, RateLimited


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

    def get(self, url, headers=None):
        self.urls.append(url)
        return self._responses.pop(0)


def test_get_repo_returns_json():
    sess = FakeSession([FakeResp(200, {"stargazers_count": 100})])
    c = GitHubClient(token="t", session=sess)
    assert c.get_repo("o", "r")["stargazers_count"] == 100


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
