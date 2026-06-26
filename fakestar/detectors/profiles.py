from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from statistics import median

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _age_days(user: dict, now: datetime) -> int:
    return (now - _parse_dt(user["created_at"])).days


def classify_account(user: dict, now: datetime) -> tuple[bool, bool]:
    repos = user.get("public_repos", 0) or 0
    followers = user.get("followers", 0) or 0
    bio = (user.get("bio") or "").strip()

    is_ghost = repos == 0 and followers == 0 and not bio
    is_suspicious = _age_days(user, now) < 365 and repos < 2 and followers < 2
    return is_ghost, is_suspicious


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _pct_signal(name: str, value: float) -> Signal:
    """A 'higher is worse' percentage signal (fraction of sampled accounts)."""
    thr = THRESHOLDS[name]
    tripped = value > thr
    sev = _clamp((value - thr) / (1 - thr)) if tripped and thr < 1 else 0.0
    return Signal(
        name=name, value=round(value, 4), baseline=BASELINES[name],
        threshold=thr, weight=WEIGHTS[name], tripped=tripped, severity=sev,
        detail=f"{value:.1%} of sampled stargazers",
    )


def _young_age_signal(median_age: float, counted: int) -> Signal:
    """A 'lower is worse' signal: a young median account age is suspicious.

    Catches young bought-star campaigns (e.g. medians of ~100-500 days) that
    the aged-account fingerprints miss.
    """
    name = "young_median_age"
    thr = THRESHOLDS[name]
    tripped = counted > 0 and median_age < thr
    sev = _clamp((thr - median_age) / thr) if tripped and thr > 0 else 0.0
    return Signal(
        name=name, value=round(median_age, 1), baseline=BASELINES[name],
        threshold=thr, weight=WEIGHTS[name], tripped=tripped, severity=sev,
        detail=f"median account age {median_age:.0f} days "
               f"({counted} sampled)" if counted else "no accounts sampled",
    )


PER_PAGE = 100


def _select_pages(total_pages: int, n_pages: int) -> list[int]:
    """Pick n_pages page numbers spread evenly across [1, total_pages].

    Always includes the first and last page so the sample spans the oldest
    and the most recent stargazers (where a bought-star campaign is most
    likely to show up), rather than only the chronologically-oldest stars on
    page 1.
    """
    n_pages = max(1, min(n_pages, total_pages))
    if n_pages == 1:
        return [1]
    return sorted({1 + round(i * (total_pages - 1) / (n_pages - 1))
                   for i in range(n_pages)})


def analyze_profiles(
    client, owner: str, repo: str, total_stars: int | None = None,
    sample: int = 150, now: datetime | None = None,
) -> list[Signal]:
    now = now or datetime.now(timezone.utc)

    if total_stars is not None and total_stars > 0:
        total_pages = max(1, ceil(total_stars / PER_PAGE))
    else:
        total_pages = max(1, ceil(sample / PER_PAGE))
    n_pages = min(total_pages, max(1, ceil(sample / PER_PAGE)))
    pages = _select_pages(total_pages, n_pages)
    per_page_take = ceil(sample / len(pages))

    logins: list[str] = []
    for page in pages:
        taken = 0
        for item in client.get_stargazer_page(owner, repo, page, per_page=PER_PAGE):
            logins.append(item["login"])
            taken += 1
            if taken >= per_page_take or len(logins) >= sample:
                break
        if len(logins) >= sample:
            break

    ghosts = suspicious = zero_followers = zero_repos = zero_following = 0
    ages: list[int] = []
    counted = 0
    for login in logins:
        user = client.get_user(login)
        g, s = classify_account(user, now)
        ghosts += g
        suspicious += s
        if (user.get("followers", 0) or 0) == 0:
            zero_followers += 1
        if (user.get("public_repos", 0) or 0) == 0:
            zero_repos += 1
        if (user.get("following", 0) or 0) == 0:
            zero_following += 1
        ages.append(_age_days(user, now))
        counted += 1

    median_age = float(median(ages)) if ages else 0.0

    def pct(n: int) -> float:
        return n / counted if counted else 0.0

    return [
        _pct_signal("ghost_pct", pct(ghosts)),
        _pct_signal("suspicious_pct", pct(suspicious)),
        _pct_signal("zero_followers_pct", pct(zero_followers)),
        _pct_signal("zero_repos_pct", pct(zero_repos)),
        _pct_signal("zero_following_pct", pct(zero_following)),
        _young_age_signal(median_age, counted),
    ]
