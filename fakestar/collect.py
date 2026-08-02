"""Gathering the best evidence obtainable, and saying which it was.

Preference order for star identities, best first:

  1. GH Archive     — a draw from the repo's whole star history.
  2. Stargazer list — same reach, but GitHub serves it to admins/collaborators
                      only since July 2026, so it works on your own repos.
  3. Event feed     — the last ~300 events. Recent-only, and marked as such so
                      nothing downstream mistakes it for a history.

Each fallback is recorded as a note, because "we looked at the last two hours"
and "we looked at fifteen years" must never read the same in a report.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from .baselines import clamp01
from .detectors import accounts as accounts_detector
from .detectors import ratios as ratios_detector
from .detectors import timeline as timeline_detector
from .evidence import Account, Provenance, RepoFacts, StarSample
from .models import Measurement, Signal
from .sources.archive import ArchiveUnavailable, InvalidRepoName  # noqa: F401
from .sources.github import (GitHubServerError, RepoNotFound,
                             StargazerListUnavailable)


@dataclass
class Evidence:
    facts: RepoFacts
    sample: StarSample
    accounts: list[Account]
    measurements: list[Measurement]
    context: list[Signal]
    notes: list[str]
    # The newest stars, profiled separately. The archive is blind to roughly the
    # last year, and the event feed is blind to everything before ~yesterday, so
    # neither alone sees the whole repo. Kept apart rather than merged because
    # they answer about different periods and need different references.
    recent_sample: StarSample | None = None
    recent_accounts: list[Account] | None = None
    recent_measurements: list[Measurement] | None = None


RECENT_WINDOW_DAYS = 30


def _null_progress(_msg: str) -> None:
    pass


def _recent_capture(archive, live: StarSample, owner: str, repo: str,
                    now: datetime,
                    also_known_as: tuple[str, ...] = ()) -> float | None:
    """How much of this repo's CURRENT star traffic the archive is still seeing.

    GitHub's own event feed gives the live rate; the archive gives what it
    recorded over the same recent period. The ratio is this repo's present-day
    capture rate. It is the honest way to say "stars from the last few months
    are missing" instead of leaving the reader to infer it from a coverage
    percentage that averages over the repo's whole life.

    Takes the live sample rather than fetching it, so this and the recent-cohort
    analysis describe the same window instead of two fetches seconds apart.
    None when the live rate can't be established.
    """
    if len(live.logins) < 10 or not live.daily:
        return None  # too little traffic to estimate a rate from

    first, last = live.coverage.first, live.coverage.last
    if not (first and last):
        return None
    observed_days = max((last - first).total_seconds() / 86400, 1 / 24)
    per_day = len(live.logins) / observed_days
    expected = per_day * RECENT_WINDOW_DAYS
    if expected < 1:
        return None

    since = now - timedelta(days=RECENT_WINDOW_DAYS)
    try:
        recorded = archive.count_since([f"{owner}/{repo}", *also_known_as], since)
    except Exception:
        return None
    return clamp01(recorded / expected)


def _former_names(gh, archive, full: str, sample: StarSample,
                  notes: list[str], progress) -> list[str]:
    """Former names of this repo, found and confirmed automatically.

    Only worth looking when the record is visibly short of the repo's stars —
    a rename is the usual reason for that. Candidates come from the archive and
    are each confirmed against GitHub, so a guess never silently pollutes the
    sample with another repo's stargazers.
    """
    if sample.coverage.fraction >= 0.9 and not sample.coverage.may_be_truncated:
        return []
    if not sample.coverage.first:
        return []
    progress("Looking for former names of this repo...")
    try:
        candidates = archive.find_former_names(full, sample.coverage.first)
    except (ArchiveUnavailable, InvalidRepoName):
        return []

    confirmed = []
    for candidate, stars in candidates:
        if gh.resolves_to(candidate, full):
            confirmed.append(candidate)
            notes.append(f"{candidate} is a former name of this repo; its "
                         f"{stars:,} archived stars are included.")
    return confirmed


def _star_sample(gh, archive, owner: str, repo: str, facts: RepoFacts,
                 sample_size: int, notes: list[str], progress,
                 also_known_as: tuple[str, ...] = ()) -> StarSample:
    full = f"{owner}/{repo}"
    names = [full, *also_known_as]

    if archive is not None:
        progress("Reading the public star archive...")
        try:
            sample = archive.star_sample(names, facts.stars, limit=sample_size,
                                         repo_created_at=facts.created_at)
            if sample.usable and not also_known_as:
                found = _former_names(gh, archive, full, sample, notes, progress)
                if found:
                    sample = archive.star_sample(
                        [full, *found], facts.stars, limit=sample_size,
                        repo_created_at=facts.created_at)
            if sample.usable:
                if sample.coverage.may_be_truncated:
                    notes.append(
                        "The archive's first star lands over a year after the "
                        "repo was created. The record is keyed by repo name "
                        "with no id, so a rename strands the earlier history "
                        "under the old name - pass it with --also-known-as "
                        "old/name to recover those stars. It can also simply "
                        "mean nobody starred the repo for a year.")
                return sample
            notes.append("The public star archive has no record of this repo.")
        except InvalidRepoName as exc:
            notes.append(str(exc))
        except ArchiveUnavailable as exc:
            notes.append(f"Public star archive unavailable ({exc}).")

    progress("Trying GitHub's stargazer list...")
    try:
        sample = gh.stargazer_list(owner, repo, facts.stars, limit=sample_size)
        if sample.usable:
            return sample
    except StargazerListUnavailable:
        notes.append(
            "GitHub serves the stargazer list to a repo's own admins and "
            "collaborators only (since 2026-06-30).")

    progress("Falling back to the recent event feed...")
    sample = gh.recent_star_events(owner, repo, facts.stars)
    if sample.usable:
        notes.append(
            "Only the most recent stars could be identified. Recent stargazers "
            "of any popular repo skew new and empty, so these accounts are "
            "reported but not scored.")
    return sample


def _context_signals(gh, owner: str, repo: str, facts: RepoFacts,
                     now: datetime, notes: list[str]) -> list[Signal]:
    """Project liveness. Real information, different question — never scored."""
    out: list[Signal] = []
    try:
        contributors = gh.count_contributors(owner, repo)
        out.append(Signal("contributors", float(contributors), None, None, 0,
                          f"{contributors} contributors", facts.stars))
    except (RepoNotFound, GitHubServerError):
        # Context only — a missing contributor count must not sink the run.
        notes.append("Contributor count unavailable.")
    if facts.pushed_at:
        days = (now - facts.pushed_at).days
        out.append(Signal("commit_staleness", float(days), None, None, 0,
                          f"last push {days} days ago", facts.stars))
    if facts.stars:
        per_k = 1000 * facts.open_issues / facts.stars
        out.append(Signal("open_issues", float(facts.open_issues), None, None, 0,
                          f"{facts.open_issues} open issues "
                          f"({per_k:.0f} per 1k stars)", facts.stars))
    return out


def gather(gh, archive, owner: str, repo: str, sample_size: int = 300,
           workers: int = 8, now: datetime | None = None,
           progress=_null_progress, recent_sample_size: int = 100,
           also_known_as: tuple[str, ...] = ()) -> Evidence:
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []

    progress(f"Fetching {owner}/{repo}...")
    facts = gh.repo_facts(owner, repo)

    sample = _star_sample(gh, archive, owner, repo, facts, sample_size,
                          notes, progress, also_known_as)

    # The newest stars, fetched once and used twice: to measure how current the
    # archive still is for this repo, and as a second cohort if it isn't.
    live: StarSample | None = None
    if archive is not None and sample.provenance is Provenance.ARCHIVE:
        progress("Checking how current the archive is for this repo...")
        try:
            live = gh.recent_star_events(owner, repo, facts.stars)
        except (RepoNotFound, GitHubServerError):
            live = None

    if live is not None:
        capture = _recent_capture(archive, live, owner, repo, now, also_known_as)
        if capture is not None:
            sample = replace(
                sample, coverage=replace(sample.coverage, recent_capture=capture))
            if sample.coverage.blind_to_recent:
                notes.append(
                    f"The public record is currently capturing only "
                    f"~{capture:.0%} of this repo's stars, so stars from the "
                    f"last few months are effectively unexamined. A campaign "
                    f"run recently would largely fall in that gap.")

    account_list: list[Account] = []
    if sample.logins:
        progress(f"Checking {len(sample.logins)} stargazer accounts...")
        account_list = gh.accounts(list(sample.logins), workers=workers)

    measurements = list(ratios_detector.measure(facts))
    if account_list:
        measurements += accounts_detector.measure(account_list, now)
    if sample.daily and sample.provenance is not Provenance.NONE:
        measurements += timeline_detector.measure(sample.daily)

    # Second cohort: the newest stars, reusing the feed already fetched above.
    # Only when the primary sample is historical and has fallen behind —
    # otherwise these stars either are the primary sample, or add nothing.
    recent_sample = recent_accounts = recent_measurements = None
    if live is not None and recent_sample_size and sample.coverage.blind_to_recent:
        progress("Sampling the newest stars the archive missed...")
        recent_sample = live
        logins = list(live.logins)[:recent_sample_size]
        if logins:
            recent_accounts = gh.accounts(logins, workers=workers)
            recent_measurements = accounts_detector.measure(recent_accounts, now)

    progress("Checking project activity...")
    context = _context_signals(gh, owner, repo, facts, now, notes)

    return Evidence(facts=facts, sample=sample, accounts=account_list,
                    measurements=measurements, context=context, notes=notes,
                    recent_sample=recent_sample, recent_accounts=recent_accounts,
                    recent_measurements=recent_measurements)
