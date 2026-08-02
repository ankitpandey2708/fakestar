"""GitHub REST: exact repo counts, account enrichment, recent star events.

What this can and cannot do, as of 2026-08:
  - repo facts, account lookups: unrestricted.
  - the stargazer list: admins and collaborators only (404 otherwise) since
    GitHub's 2026-06-30 restriction. Still attempted, because it is the best
    source when you do own the repo.
  - the repo event feed: last ~300 events, which on a busy repo is hours.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any

from ..evidence import Account, Coverage, Provenance, RepoFacts, StarSample

API = "https://api.github.com"
MAX_RATE_LIMIT_WAITS = 5
EVENT_PAGES = 3  # GitHub serves ~300 repo events; page 4 answers 422


class RepoNotFound(Exception):
    pass


class StargazerListUnavailable(Exception):
    """GitHub withheld the stargazer list.

    Restricted to admins and collaborators in July 2026 (changelog 2026-06-30):
    404 for repositories the token holder doesn't own, 401 unauthenticated. The
    repository itself is fine — only the identity list is withheld — so this is
    deliberately distinct from RepoNotFound.
    """


class RateLimited(Exception):
    def __init__(self, reset_ts: int):
        super().__init__(f"GitHub rate limit hit; resets at {reset_ts}")
        self.reset_ts = reset_ts


class GitHubServerError(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"GitHub server error {status} after 3 attempts: {url}")
        self.status = status


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class GitHubSource:
    def __init__(self, token: str | None = None, session=None, sleeper=time.sleep,
                 wait: bool = False, timeout: float = 15.0):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._token = token
        self._sleep = sleeper
        self._wait = wait
        self._timeout = timeout

    # ---- plumbing ----------------------------------------------------------
    @staticmethod
    def _seconds_until(reset_ts: int) -> int:
        return max(0, reset_ts - int(time.time())) + 1  # +1s so the window is open

    def _headers(self, accept: str) -> dict[str, str]:
        h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        server_attempts = rate_waits = 0
        while True:
            resp = self._session.get(url, headers=self._headers(accept),
                                     timeout=self._timeout)
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

    # ---- facts -------------------------------------------------------------
    def repo_facts(self, owner: str, repo: str) -> RepoFacts:
        d = self._request(f"{API}/repos/{owner}/{repo}").json()
        return RepoFacts(
            full_name=d.get("full_name") or f"{owner}/{repo}",
            stars=d.get("stargazers_count") or 0,
            forks=d.get("forks_count") or 0,
            watchers=d.get("subscribers_count") or 0,
            open_issues=d.get("open_issues_count") or 0,
            created_at=_dt(d.get("created_at")),
            pushed_at=_dt(d.get("pushed_at")),
            language=d.get("language"),
            topics=tuple(d.get("topics") or ()),
            description=d.get("description") or "",
        )

    def resolves_to(self, candidate: str, expected_full_name: str) -> bool:
        """True if `candidate` is a former name of `expected_full_name`.

        GitHub keeps redirecting a renamed repo's old path forever, so asking
        for the old name returns the current repo. That makes a one-request
        confirmation of a rename guess — and rules out the case where two
        genuinely different repos merely share half a path.
        """
        owner, _, name = candidate.partition("/")
        if not owner or not name:
            return False
        try:
            facts = self.repo_facts(owner, name)
        except (RepoNotFound, GitHubServerError):
            return False
        return facts.full_name.lower() == expected_full_name.lower()

    def count_contributors(self, owner: str, repo: str) -> int:
        """Contributor count (GitHub caps around 500).

        per_page=1 plus the Link rel="last" page number gives the count in one
        request instead of paging through everybody.
        """
        resp = self._request(
            f"{API}/repos/{owner}/{repo}/contributors?per_page=1&anon=true")
        last = resp.links.get("last")
        if last:
            m = re.search(r"[?&]page=(\d+)", last["url"])
            if m:
                return int(m.group(1))
        return len(resp.json())

    # ---- accounts ----------------------------------------------------------
    def account(self, login: str) -> Account:
        try:
            d = self._request(f"{API}/users/{login}").json()
        except RepoNotFound:
            # The account is gone. Meaningful, not an error: only a historical
            # source can hand us a login that no longer resolves.
            return Account(login=login, deleted=True)
        return Account(
            login=login,
            followers=d.get("followers") or 0,
            public_repos=d.get("public_repos") or 0,
            following=d.get("following") or 0,
            has_bio=bool((d.get("bio") or "").strip()),
            created_at=_dt(d.get("created_at")),
        )

    def accounts(self, logins: list[str], workers: int = 8) -> list[Account]:
        """Fetch profiles concurrently; I/O-bound, so threads are the right tool."""
        if not logins:
            return []
        out: list[Account] = []
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = [pool.submit(self.account, lg) for lg in logins]
            for fut in as_completed(futures):
                out.append(fut.result())
        return out

    # ---- star identities ---------------------------------------------------
    def _stargazer_request(self, url: str, accept: str):
        try:
            resp = self._request(url, accept)
        except RepoNotFound:
            raise StargazerListUnavailable(
                "GitHub serves the stargazer list to admins and collaborators "
                "only (404)") from None
        if resp.status_code == 401:
            raise StargazerListUnavailable(
                "the stargazer list requires authentication (401)")
        return resp

    def stargazer_list(self, owner: str, repo: str, population: int,
                       limit: int = 300) -> StarSample:
        """The real stargazer list. Works only where we're an admin/collaborator."""
        logins: list[str] = []
        stamps: list[datetime] = []
        url = f"{API}/repos/{owner}/{repo}/stargazers?per_page=100"
        while url and len(logins) < limit:
            resp = self._stargazer_request(url, "application/vnd.github.star+json")
            data = resp.json()
            if not isinstance(data, list):
                break  # past the pagination limit GitHub returns an error object
            for item in data:
                user = item.get("user") or item
                login = user.get("login")
                if not login:
                    continue
                logins.append(login)
                when = _dt(item.get("starred_at"))
                if when:
                    stamps.append(when)
            nxt = resp.links.get("next")
            url = nxt["url"] if nxt else None
        return StarSample(
            logins=tuple(logins),
            provenance=Provenance.LIST,
            coverage=Coverage(len(set(logins)), population,
                              min(stamps, default=None), max(stamps, default=None)),
            daily=_daily(stamps),
        )

    def recent_star_events(self, owner: str, repo: str, population: int,
                           max_pages: int = EVENT_PAGES) -> StarSample:
        """Stargazers from the repo's event feed: the last ~300 events only.

        A genuinely recent slice — hours on a busy repo — so it is marked
        EVENTS and must never be judged against all-time baselines.
        """
        logins: list[str] = []
        stamps: list[datetime] = []
        url = f"{API}/repos/{owner}/{repo}/events?per_page=100"
        pages = 0
        while url and pages < max_pages:
            resp = self._request(url)
            data = resp.json()
            if not isinstance(data, list):
                break
            for ev in data:
                if ev.get("type") != "WatchEvent":
                    continue
                login = (ev.get("actor") or {}).get("login")
                if not login:
                    continue
                logins.append(login)
                when = _dt(ev.get("created_at"))
                if when:
                    stamps.append(when)
            pages += 1
            nxt = resp.links.get("next")
            url = nxt["url"] if nxt else None
        deduped = tuple(dict.fromkeys(logins))
        return StarSample(
            logins=deduped,
            provenance=Provenance.EVENTS if deduped else Provenance.NONE,
            coverage=Coverage(len(deduped), population,
                              min(stamps, default=None), max(stamps, default=None)),
            daily=_daily(stamps),
        )


def _daily(stamps: list[datetime]) -> tuple[tuple[Any, int], ...]:
    counts: dict[Any, int] = {}
    for s in stamps:
        counts[s.date()] = counts.get(s.date(), 0) + 1
    return tuple(sorted(counts.items()))
