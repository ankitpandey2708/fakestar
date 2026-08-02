"""Who starred it: fingerprints of a sampled stargazer cohort.

Pure functions over Account objects. No network, no config — hand it accounts,
it hands back measurements. Whether those measurements may be scored is decided
elsewhere, by provenance.
"""
from __future__ import annotations

from datetime import datetime
from statistics import median

from ..evidence import Account
from ..models import Measurement


def _is_ghost(a: Account) -> bool:
    """No repos, no followers, no bio: an account with nothing in it."""
    return a.public_repos == 0 and a.followers == 0 and not a.has_bio


def _is_suspicious(a: Account, now: datetime) -> bool:
    """Young AND inactive. Either alone is common; together is a farm signature."""
    return a.age_days(now) < 365 and a.public_repos < 2 and a.followers < 2


def measure(accounts: list[Account], now: datetime) -> list[Measurement]:
    """Cohort percentages plus median account age.

    Deleted accounts are counted for deleted_pct but excluded from every other
    percentage — a removed account has no follower count to average in.
    """
    total = len(accounts)
    if not total:
        return []

    live = [a for a in accounts if not a.deleted]
    gone = total - len(live)
    n = len(live)

    out = [Measurement("deleted_pct", gone / total, total,
                       f"{gone} of {total} sampled accounts no longer exist")]
    if not n:
        return out

    ghosts = sum(_is_ghost(a) for a in live)
    suspicious = sum(_is_suspicious(a, now) for a in live)
    zero_followers = sum(a.followers == 0 for a in live)
    zero_repos = sum(a.public_repos == 0 for a in live)
    ages = [a.age_days(now) for a in live if a.created_at]

    out += [
        Measurement("zero_followers_pct", zero_followers / n, n,
                    f"{zero_followers} of {n} have no followers"),
        Measurement("ghost_pct", ghosts / n, n,
                    f"{ghosts} of {n} are empty accounts"),
        Measurement("zero_repos_pct", zero_repos / n, n,
                    f"{zero_repos} of {n} have no repositories"),
        Measurement("suspicious_pct", suspicious / n, n,
                    f"{suspicious} of {n} are young and inactive"),
    ]
    if ages:
        out.append(Measurement(
            "young_median_age", float(median(ages)), len(ages),
            f"median account age {median(ages):.0f} days"))
    return out
