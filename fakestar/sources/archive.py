"""GH Archive: the public record of who starred what, and when.

GitHub restricted its own stargazer list in July 2026, but the public event
stream it fed has been mirrored for 15 years by GH Archive. That mirror still
answers the question GitHub no longer will, with one large caveat: GH Archive's
capture rate has been falling since mid-2025 and sits under 20% through 2026.
Its crawler polls only page 1 of a 3-page rotating feed and so misses events
that surface further back (gharchive.org issues #310 and #320; fix unmerged).
The events it does keep are lost by page position rather than by who starred,
so what survives still behaves like a random sample of stargazers.

Reached over ClickHouse's public HTTP interface, which needs no credentials.
The endpoint is swappable (--archive-url, $FAKESTAR_ARCHIVE_URL) so anyone can
point at their own mirror instead of leaning on a free shared demo.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timezone
from urllib.parse import quote

from ..cache import Cache
from ..evidence import Coverage, Provenance, StarSample

DEFAULT_ENDPOINT = "https://play.clickhouse.com/?user=play"
DEFAULT_TABLE = "github_events"

# Repo names go into SQL. Only ever accept GitHub's own character set, so no
# quoting question can arise in the first place.
_SAFE_REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")

class ArchiveUnavailable(Exception):
    """The archive could not be reached or answered with an error."""


class InvalidRepoName(ValueError):
    pass


class ArchiveSource:
    def __init__(self, endpoint: str | None = None, session=None,
                 cache: Cache | None = None, timeout: float = 30.0,
                 table: str = DEFAULT_TABLE):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._endpoint = (endpoint or os.environ.get("FAKESTAR_ARCHIVE_URL")
                          or DEFAULT_ENDPOINT)
        self._cache = cache if cache is not None else Cache()
        self._timeout = timeout
        self._table = table

    # ---- plumbing ----------------------------------------------------------
    def _sql(self, query: str) -> list[list[str]]:
        sep = "&" if "?" in self._endpoint else "?"
        url = f"{self._endpoint}{sep}default_format=TabSeparated&query={quote(query)}"
        try:
            resp = self._session.get(url, timeout=self._timeout)
        except Exception as exc:  # network stack, DNS, TLS, timeouts
            raise ArchiveUnavailable(f"archive unreachable: {exc}") from None
        if resp.status_code != 200:
            raise ArchiveUnavailable(
                f"archive returned HTTP {resp.status_code}: "
                f"{resp.text.strip()[:200]}")
        text = resp.text.strip()
        if not text:
            return []
        return [line.split("\t") for line in text.split("\n")]

    def _cached_sql(self, key: str, query: str) -> list[list[str]]:
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        rows = self._sql(query)
        self._cache.put(key, rows)
        return rows

    @staticmethod
    def _check(repo: str | list[str]) -> list[str]:
        names = [repo] if isinstance(repo, str) else list(repo)
        for name in names:
            if not _SAFE_REPO.match(name):
                raise InvalidRepoName(f"not a valid owner/repo: {name!r}")
        return names

    @staticmethod
    def _key(names: list[str]) -> str:
        return "+".join(sorted(names))

    def _where(self, repo: str | list[str]) -> str:
        """Rows for one repo, or for a repo plus the names it used to have.

        The mirror stores `repo_name` and no repo id, so a rename splits a
        project's history into two unrelated buckets — pallets/flask carries
        stars from 2016 on, while its first five years sit under
        mitsuhiko/flask. Accepting several names is the only way to put them
        back together.
        """
        names = [repo] if isinstance(repo, str) else list(repo)
        quoted = ",".join(f"'{n}'" for n in names)
        return (f"FROM {self._table} WHERE event_type='WatchEvent' "
                f"AND repo_name IN ({quoted})")

    # ---- queries -----------------------------------------------------------
    def totals(self, repo: str | list[str]) -> tuple[int, datetime | None, datetime | None]:
        """(distinct stargazers, first star, last star) in the archive."""
        names = self._check(repo)
        rows = self._cached_sql(
            f"totals:{self._table}:{self._key(names)}",
            f"SELECT uniqExact(actor_login), min(created_at), max(created_at) "
            f"{self._where(names)}")
        if not rows or not rows[0] or not rows[0][0]:
            return 0, None, None
        n = int(rows[0][0])
        if not n:
            return 0, None, None
        return n, _parse(rows[0][1]), _parse(rows[0][2])

    def sample_logins(self, repo: str | list[str], limit: int) -> list[str]:
        """A deterministic pseudo-random draw of distinct stargazers.

        Hashing the login rather than taking the first N spreads the sample
        across the repo's whole history, and returns the same sample tomorrow.
        """
        names = self._check(repo)
        rows = self._cached_sql(
            f"logins:{self._table}:{self._key(names)}:{limit}",
            f"SELECT actor_login FROM (SELECT DISTINCT actor_login "
            f"{self._where(names)}) ORDER BY cityHash64(actor_login) "
            f"LIMIT {int(limit)}")
        return [r[0] for r in rows if r and r[0]]

    def daily(self, repo: str | list[str]) -> list[tuple[date, int]]:
        """Stars per calendar day across the archived history."""
        names = self._check(repo)
        rows = self._cached_sql(
            f"daily:{self._table}:{self._key(names)}",
            f"SELECT toDate(created_at) d, count() c {self._where(names)} "
            f"GROUP BY d ORDER BY d")
        out = []
        for r in rows:
            if len(r) < 2:
                continue
            day = _parse_date(r[0])
            if day:
                out.append((day, int(r[1])))
        return out

    def count_since(self, repo: str | list[str], since: datetime) -> int:
        """Archived stars for this repo since a timestamp."""
        names = self._check(repo)
        stamp = since.strftime("%Y-%m-%d %H:%M:%S")
        rows = self._cached_sql(
            f"since:{self._table}:{self._key(names)}:{stamp[:10]}",
            f"SELECT count() {self._where(names)} AND created_at >= '{stamp}'")
        if not rows or not rows[0] or not rows[0][0]:
            return 0
        return int(rows[0][0])

    def find_former_names(self, repo: str, first_star: datetime,
                          min_stars: int = 20) -> list[tuple[str, int]]:
        """Guess what this repo used to be called, from the record itself.

        A rename leaves a clean fingerprint: the old name's stars stop at the
        instant the new name's begin, because they are the same repo. Renames
        also nearly always keep one half of the path — `mitsuhiko/flask` became
        `pallets/flask` — which narrows the search from every repo on GitHub to
        a handful.

        These are candidates, not conclusions. The caller confirms each against
        GitHub, which still resolves old names to their current one.
        """
        (name,) = self._check(repo)
        owner, _, short = name.partition("/")
        stamp = first_star.strftime("%Y-%m-%d %H:%M:%S")
        rows = self._cached_sql(
            f"former:{self._table}:{name}:{stamp[:10]}",
            f"SELECT repo_name, count() AS stars, max(created_at) AS last "
            f"FROM {self._table} WHERE event_type='WatchEvent' "
            f"AND repo_name != '{name}' "
            f"AND (splitByChar('/', repo_name)[2] = '{short}' "
            f"     OR splitByChar('/', repo_name)[1] = '{owner}') "
            f"GROUP BY repo_name "
            f"HAVING last <= toDateTime('{stamp}') + INTERVAL 2 DAY "
            f"   AND last >= toDateTime('{stamp}') - INTERVAL 30 DAY "
            f"   AND stars >= {int(min_stars)} "
            f"ORDER BY stars DESC LIMIT 5")
        return [(r[0], int(r[1])) for r in rows if len(r) >= 2 and r[0]]

    # ---- assembled evidence ------------------------------------------------
    def star_sample(self, repo: str | list[str], population: int,
                    limit: int = 300,
                    repo_created_at: datetime | None = None) -> StarSample:
        examined, first, last = self.totals(repo)
        if not examined:
            return StarSample.empty(population)
        logins = self.sample_logins(repo, limit)
        # Archive rows carry the repo name as it was at event time, so a rename
        # strands the earlier history under the old name. Starting well after
        # the repo was created is the visible symptom.
        truncated = bool(
            repo_created_at and first
            and (first - repo_created_at).days > 365)
        return StarSample(
            logins=tuple(logins),
            provenance=Provenance.ARCHIVE,
            coverage=Coverage(examined, population, first, last,
                              may_be_truncated=truncated),
            daily=tuple(self.daily(repo)),
        )


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
