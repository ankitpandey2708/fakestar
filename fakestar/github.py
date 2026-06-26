from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

API = "https://api.github.com"


class RepoNotFound(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, reset_ts: int):
        super().__init__(f"GitHub rate limit hit; resets at {reset_ts}")
        self.reset_ts = reset_ts


class GitHubServerError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"GitHub server error {status} after 3 attempts: {url}")
        self.status = status


MAX_RATE_LIMIT_WAITS = 5


class GitHubClient:
    def __init__(self, token: str | None = None, session=None, sleeper=time.sleep,
                 wait: bool = False):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._token = token
        self._sleep = sleeper
        self._wait = wait

    @staticmethod
    def _seconds_until(reset_ts: int) -> int:
        # +1s buffer so we resume just after the window opens
        return max(0, reset_ts - int(time.time())) + 1

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        server_attempts = 0
        rate_waits = 0
        while True:
            resp = self._session.get(url, headers=self._headers(accept))
            status = resp.status_code
            if status == 404:
                raise RepoNotFound(url)
            if status in (403, 429) and resp.headers.get("X-RateLimit-Remaining") == "0":
                reset_ts = int(resp.headers.get("X-RateLimit-Reset", "0"))
                if self._wait and rate_waits < MAX_RATE_LIMIT_WAITS:
                    self._sleep(self._seconds_until(reset_ts))
                    rate_waits += 1
                    continue
                raise RateLimited(reset_ts)
            if 500 <= status < 600:
                if server_attempts < 2:
                    self._sleep(2 ** server_attempts)
                    server_attempts += 1
                    continue
                raise GitHubServerError(status, url)
            return resp

    def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return self._request(f"{API}/repos/{owner}/{repo}").json()

    def get_user(self, login: str) -> dict[str, Any]:
        return self._request(f"{API}/users/{login}").json()

    def get_stargazer_page(
        self, owner: str, repo: str, page: int, per_page: int = 100,
    ) -> list[dict[str, Any]]:
        url = (f"{API}/repos/{owner}/{repo}/stargazers"
               f"?per_page={per_page}&page={page}")
        return self._request(url).json()

    def count_contributors(self, owner: str, repo: str) -> int:
        """Total contributors (capped by GitHub at ~500).

        Uses the per_page=1 + Link `rel="last"` trick: the last page number
        equals the contributor count, so we learn the count from one request.
        """
        resp = self._request(
            f"{API}/repos/{owner}/{repo}/contributors?per_page=1&anon=true")
        last = resp.links.get("last")
        if last:
            m = re.search(r"[?&]page=(\d+)", last["url"])
            if m:
                return int(m.group(1))
        return len(resp.json())  # 0 or 1 contributor (no pagination)

    def iter_stargazers(
        self, owner: str, repo: str,
        with_timestamps: bool = False, max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        accept = ("application/vnd.github.star+json" if with_timestamps
                  else "application/vnd.github+json")
        url = f"{API}/repos/{owner}/{repo}/stargazers?per_page=100"
        pages = 0
        while url:
            resp = self._request(url, accept)
            for item in resp.json():
                yield item
            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            nxt = resp.links.get("next")
            url = nxt["url"] if nxt else None
