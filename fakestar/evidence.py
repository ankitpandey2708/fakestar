"""The shared vocabulary: what we managed to observe about a repo's stars.

Every measurement carries its Provenance — the pipeline that produced it —
because a value is only comparable to a baseline measured the same way. That
rule is the difference between a trustworthy verdict and the failure mode where
a repo's *recent* stargazers get judged against *all-time* anchors and every
popular project looks manipulated.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum


class Provenance(str, Enum):
    """Where a star sample came from. Determines what it may be compared to."""

    ARCHIVE = "archive"   # GH Archive: a draw from the repo's whole star history
    LIST = "list"         # GitHub's stargazer list: same, but admins/collaborators only
    EVENTS = "events"     # repo event feed: the most recent ~300 events only
    WATCH = "watch"       # reserved: history this tool recorded itself
    NONE = "none"         # no identities obtainable

    @property
    def is_all_time(self) -> bool:
        """True when the sample spans the repo's history, so all-time anchors apply."""
        return self in (Provenance.ARCHIVE, Provenance.LIST)


@dataclass(frozen=True)
class Coverage:
    """How much of the star population we actually got to look at."""

    examined: int              # distinct stargazers identified
    population: int            # the repo's current star count
    first: datetime | None = None   # earliest star observed
    last: datetime | None = None    # latest star observed
    # Archive rows are keyed by the repo name at event time, so a renamed repo
    # loses its pre-rename history. Set when the evidence starts suspiciously
    # late relative to repo creation.
    may_be_truncated: bool = False
    # Share of this repo's CURRENT stars the archive is still capturing,
    # estimated by comparing its recent rows against the live event feed. The
    # archive's crawler misses events by page position, which is unbiased with
    # respect to who starred but badly biased in time — so a low value means
    # recent stars are unexamined, not that the sample is imprecise.
    recent_capture: float | None = None

    @property
    def fraction(self) -> float:
        if self.population <= 0:
            return 0.0
        return min(1.0, self.examined / self.population)

    @property
    def blind_to_recent(self) -> bool:
        """True when the record is missing most of the repo's current stars.

        The case that matters: a campaign run in the last few months lands
        almost entirely in the gap.
        """
        return self.recent_capture is not None and self.recent_capture < 0.5

    def describe(self, profiled: int = 0) -> str:
        """One line the reader can act on.

        Two different numbers matter and must not be conflated: how many
        stargazers could be IDENTIFIED at all (the pool the record still holds),
        and how many of those had their profiles actually FETCHED. The first
        governs whether the sample represents the repo; the second governs how
        precise the percentages are.
        """
        if not self.examined:
            return "no stargazers could be identified"
        window = ""
        if self.first and self.last:
            window = f", {self.first:%Y-%m-%d} to {self.last:%Y-%m-%d}"
        pool = (f"{self.examined:,} of {self.population:,} stars on record "
                f"({self.fraction:.0%}){window}")
        if profiled:
            return f"{profiled:,} accounts profiled, drawn from {pool}"
        return pool


@dataclass(frozen=True)
class Account:
    """A stargazer's account as it stands today. `deleted` means it 404s now —
    only observable when the login came from a historical source, since a live
    list can't contain accounts GitHub has already removed."""

    login: str
    deleted: bool = False
    followers: int = 0
    public_repos: int = 0
    following: int = 0
    has_bio: bool = False
    created_at: datetime | None = None

    def age_days(self, now: datetime) -> int:
        if self.created_at is None:
            return 0
        return (now - self.created_at).days


@dataclass(frozen=True)
class StarSample:
    """Identities and timing for some subset of a repo's stars."""

    logins: tuple[str, ...]
    provenance: Provenance
    coverage: Coverage
    # (day, stars that day) across the observed window; empty when unavailable.
    daily: tuple[tuple[date, int], ...] = ()

    @property
    def usable(self) -> bool:
        return bool(self.logins) and self.provenance is not Provenance.NONE

    @staticmethod
    def empty(population: int = 0) -> "StarSample":
        return StarSample((), Provenance.NONE, Coverage(0, population))


@dataclass(frozen=True)
class RepoFacts:
    """Exact counts from the GitHub API. Never sampled, never stale."""

    full_name: str
    stars: int
    forks: int
    watchers: int          # subscribers_count: people subscribed to notifications
    open_issues: int
    created_at: datetime | None
    pushed_at: datetime | None
    language: str | None
    topics: tuple[str, ...]
    description: str
    contributors: int | None = None   # context only; None when not fetched

    @property
    def fork_ratio(self) -> float:
        return self.forks / self.stars if self.stars else 0.0

    @property
    def watcher_ratio(self) -> float:
        return self.watchers / self.stars if self.stars else 0.0

    def age_days(self, now: datetime) -> int:
        if self.created_at is None:
            return 0
        return (now - self.created_at).days
