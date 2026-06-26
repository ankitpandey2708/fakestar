from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def classify_account(user: dict, now: datetime) -> tuple[bool, bool]:
    repos = user.get("public_repos", 0) or 0
    followers = user.get("followers", 0) or 0
    bio = (user.get("bio") or "").strip()
    age_days = (now - _parse_dt(user["created_at"])).days

    is_ghost = repos == 0 and followers == 0 and not bio
    is_suspicious = age_days < 365 and repos < 2 and followers < 2
    return is_ghost, is_suspicious


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _pct_signal(name: str, value: float) -> Signal:
    thr = THRESHOLDS[name]
    tripped = value > thr
    sev = _clamp((value - thr) / (1 - thr)) if tripped else 0.0
    return Signal(
        name=name, value=round(value, 4), baseline=BASELINES[name],
        threshold=thr, weight=WEIGHTS[name], tripped=tripped, severity=sev,
        detail=f"{value:.1%} of sampled stargazers",
    )


def analyze_profiles(
    client, owner: str, repo: str, sample: int = 150, now: datetime | None = None,
) -> list[Signal]:
    now = now or datetime.now(timezone.utc)
    max_pages = max(1, ceil(sample / 100))

    logins: list[str] = []
    for item in client.iter_stargazers(owner, repo, max_pages=max_pages):
        logins.append(item["login"])
        if len(logins) >= sample:
            break

    ghosts = suspicious = 0
    counted = 0
    for login in logins:
        user = client.get_user(login)
        g, s = classify_account(user, now)
        ghosts += g
        suspicious += s
        counted += 1

    ghost_pct = ghosts / counted if counted else 0.0
    susp_pct = suspicious / counted if counted else 0.0
    return [_pct_signal("ghost_pct", ghost_pct), _pct_signal("suspicious_pct", susp_pct)]
