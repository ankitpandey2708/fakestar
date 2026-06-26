from __future__ import annotations

from datetime import datetime, timezone

from ..baselines import BASELINES, MIN_STARS_FOR_RATIO, THRESHOLDS, WEIGHTS
from ..models import Signal

# Real-adoption signals from the blog's "What VCs should use instead": a repo
# with huge stars but few contributors, no recent commits, and almost no issues
# shows no genuine engagement. "You can fake a star count, but you can't fake a
# bug fix that saves someone's weekend."


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _parse_dt(s: str) -> datetime:
    # GitHub timestamps: 2024-01-02T03:04:05Z
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _signal(name, value, tripped, severity, detail):
    return Signal(
        name=name, value=value, baseline=BASELINES[name],
        threshold=THRESHOLDS[name], weight=WEIGHTS[name],
        tripped=tripped, severity=severity, detail=detail,
    )


def analyze_engagement(
    client, owner: str, repo: str, repo_data: dict,
    now: datetime | None = None,
) -> list[Signal]:
    now = now or datetime.now(timezone.utc)
    stars = repo_data.get("stargazers_count", 0) or 0
    open_issues = repo_data.get("open_issues_count", 0) or 0
    pushed_at = repo_data.get("pushed_at")
    big = stars > MIN_STARS_FOR_RATIO

    # low_contributors — lower is worse; only meaningful for high-star repos
    contributors = client.count_contributors(owner, repo)
    c_thr = THRESHOLDS["low_contributors"]
    c_tripped = big and contributors < c_thr
    c_sev = _clamp((c_thr - contributors) / c_thr) if c_tripped and c_thr > 0 else 0.0
    low_contributors = _signal(
        "low_contributors", float(contributors), c_tripped, c_sev,
        f"{contributors} contributors for {stars} stars")

    # commit_staleness — higher is worse (days since last push)
    s_thr = THRESHOLDS["commit_staleness"]
    if pushed_at:
        stale_days = (now - _parse_dt(pushed_at)).days
        s_tripped = stale_days > s_thr
        s_sev = _clamp((stale_days - s_thr) / s_thr) if s_tripped else 0.0
        s_detail = f"last push {stale_days} days ago"
    else:
        stale_days, s_tripped, s_sev = 0, False, 0.0
        s_detail = "no pushed_at available"
    commit_staleness = _signal(
        "commit_staleness", float(stale_days), s_tripped, s_sev, s_detail)

    # low_issues — lower is worse (open_issues / stars); high-star repos only
    i_thr = THRESHOLDS["low_issues"]
    issues_ratio = open_issues / stars if stars else 0.0
    i_tripped = big and issues_ratio < i_thr
    i_sev = _clamp((i_thr - issues_ratio) / i_thr) if i_tripped and i_thr > 0 else 0.0
    low_issues = _signal(
        "low_issues", round(issues_ratio, 5), i_tripped, i_sev,
        f"{open_issues} open issues / {stars} stars = {issues_ratio:.5f}")

    return [low_contributors, commit_staleness, low_issues]
