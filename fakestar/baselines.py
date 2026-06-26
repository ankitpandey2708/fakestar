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
    "fork_to_star": 23,
    "zero_followers_pct": 16,
    "watcher_to_star": 12,
    "ghost_pct": 12,
    "suspicious_pct": 12,
    "zero_repos_pct": 9,
    "young_median_age": 7,
    "temporal_burst": 5,
    # Weak signal: real devs tend to follow others, farmed accounts often
    # follow nobody. But many legitimate users also follow nobody, so it gets
    # a low weight and a high threshold to limit false positives.
    "zero_following_pct": 4,
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
