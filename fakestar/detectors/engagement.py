from __future__ import annotations

from datetime import datetime, timezone

from ..baselines import MIN_STARS_FOR_RATIO, THRESHOLDS
from ..models import Signal
from ._common import make_signal, parse_dt, sev_low, sev_ratio

# Real-adoption signals from the blog's "What VCs should use instead": a repo
# with huge stars but few contributors, no recent commits, and almost no issues
# shows no genuine engagement. "You can fake a star count, but you can't fake a
# bug fix that saves someone's weekend."


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
    low_contributors = make_signal(
        "low_contributors", float(contributors), c_tripped,
        sev_low(contributors, c_thr, c_tripped),
        f"{contributors} contributors for {stars} stars")

    # commit_staleness — higher is worse (days since last push).
    # Intentionally NOT gated on star count: a dead repo is informative at any
    # size (unlike the ratio signals, which need scale to be meaningful).
    s_thr = THRESHOLDS["commit_staleness"]
    if pushed_at:
        stale_days = (now - parse_dt(pushed_at)).days
        s_tripped = stale_days > s_thr
        s_sev = sev_ratio(stale_days, s_thr, s_tripped)
        s_detail = f"last push {stale_days} days ago"
    else:
        stale_days, s_tripped, s_sev = 0, False, 0.0
        s_detail = "no pushed_at available"
    commit_staleness = make_signal(
        "commit_staleness", float(stale_days), s_tripped, s_sev, s_detail)

    # low_issues — lower is worse (open_issues / stars); high-star repos only.
    # Note: GitHub's open_issues_count includes open PRs, so this is a coarse
    # proxy — hence the low weight. Near-zero on a popular repo still signals
    # "nobody actually uses this."
    i_thr = THRESHOLDS["low_issues"]
    issues_ratio = open_issues / stars if stars else 0.0
    i_tripped = big and issues_ratio < i_thr
    low_issues = make_signal(
        "low_issues", round(issues_ratio, 5), i_tripped,
        sev_low(issues_ratio, i_thr, i_tripped),
        f"{open_issues} open issues / {stars} stars = {issues_ratio:.5f}")

    return [low_contributors, commit_staleness, low_issues]
