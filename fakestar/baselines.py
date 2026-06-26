from __future__ import annotations

# Weights sum to 100. zero_followers_pct is weighted heavily because the blog's
# data shows it is the single most discriminating profile metric (organic
# 6-12% vs manipulated 52-81%). ghost_pct is reduced: it is the strict
# intersection (no repos AND no followers AND no bio) and under-detects aged
# accounts that carry a bio, which zero_followers_pct / zero_repos_pct now catch.
# Note for tuners: ghost_pct ⊆ (zero_followers_pct ∩ zero_repos_pct), so these
# three are correlated and stack on a fake repo — kept deliberately (scores cap
# at 100, severities are proportional); don't re-inflate ghost_pct's weight.
WEIGHTS: dict[str, int] = {
    "fork_to_star": 20,
    "zero_followers_pct": 14,
    "watcher_to_star": 10,
    "ghost_pct": 10,
    "suspicious_pct": 11,
    "zero_repos_pct": 8,
    "young_median_age": 6,
    "temporal_burst": 5,
    # Weak signal: real devs tend to follow others, farmed accounts often
    # follow nobody. But many legitimate users also follow nobody, so it gets
    # a low weight and a high threshold to limit false positives.
    "zero_following_pct": 3,
    # Engagement / real-adoption signals (the blog's "What VCs should use
    # instead": contributors, issues, activity — "you can't fake a bug fix").
    # Noisier than stargazer fingerprints (legit small-team projects vary), so
    # modest weights and the ratio signals are gated on stars > MIN_STARS_FOR_RATIO.
    "low_contributors": 7,
    "commit_staleness": 4,
    "low_issues": 2,
}

# For percentage signals the value trips when it rises ABOVE the threshold.
# young_median_age is in DAYS and trips when the median falls BELOW the
# threshold (younger = more suspicious).
THRESHOLDS: dict[str, float] = {
    "fork_to_star": 0.05,
    "ghost_pct": 0.10,
    "suspicious_pct": 0.15,
    "zero_followers_pct": 0.35,
    "zero_repos_pct": 0.20,
    "zero_following_pct": 0.55,
    "young_median_age": 730.0,
    "watcher_to_star": 0.002,
    "temporal_burst": 0.30,
    # Engagement ("lower is worse" except staleness, which is "higher is worse")
    "low_contributors": 10.0,     # contributors; trip if fewer (and stars > MIN)
    "commit_staleness": 365.0,    # days since last push; trip if older
    "low_issues": 0.001,          # open_issues / stars; trip if lower (and stars > MIN)
}

BASELINES: dict[str, float] = {
    "fork_to_star": 0.16,
    "ghost_pct": 0.01,
    "suspicious_pct": 0.00,
    "zero_followers_pct": 0.10,
    "zero_repos_pct": 0.05,
    "zero_following_pct": 0.40,
    "young_median_age": 3000.0,
    "watcher_to_star": 0.015,
    "temporal_burst": 0.05,
    "low_contributors": 50.0,
    "commit_staleness": 30.0,
    "low_issues": 0.02,
}

MIN_STARS_FOR_RATIO: int = 10_000

# (upper_inclusive_score, label), ascending
BANDS: list[tuple[int, str]] = [
    (25, "LIKELY ORGANIC"),
    (60, "SUSPICIOUS"),
    (100, "LIKELY MANIPULATED"),
]


def band_for(score: int) -> str:
    for upper, label in BANDS:
        if score <= upper:
            return label
    return BANDS[-1][1]
