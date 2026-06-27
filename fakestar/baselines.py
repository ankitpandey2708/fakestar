from __future__ import annotations

# ---------------------------------------------------------------------------
# Provenance of the numbers below (see README "Reading a result" + design spec):
#   [blog]    explicitly stated in the source investigation
#   [organic] from the blog's MEASURED organic baseline tables (Flask/LangChain/AutoGPT)
#   [tuned]   my calibration: trip line drawn between the blog's organic & manipulated figures
#   [n/a]     not in the blog's study at all — my addition
# All WEIGHTS are [tuned]: the blog defines no scoring model. They are design
# choices informed by which signals the blog emphasizes most.
# ---------------------------------------------------------------------------

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
    "fork_to_star": 0.05,        # [blog]  "below 0.05 ... warrants scrutiny"
    "ghost_pct": 0.10,           # [tuned] organic ~1% vs manipulated 19-28%
    "suspicious_pct": 0.15,      # [tuned] organic 0% vs openai-fm 66%
    "zero_followers_pct": 0.35,  # [tuned] organic 6-12% vs manipulated 52-81%
    "zero_repos_pct": 0.20,      # [tuned] organic 2-6% vs manipulated 28-38%
    "zero_following_pct": 0.55,  # [n/a]   prose only ("follow other users"); not measured
    "young_median_age": 730.0,   # [tuned] organic ~3000d vs manip ~1000d / openai-fm 116d
    "watcher_to_star": 0.002,    # [tuned] organic floor ~0.005 vs FreeDomain 0.001
    "temporal_burst": 0.30,      # [n/a]   temporal analysis not in the blog's study
    # Engagement ("lower is worse" except staleness, which is "higher is worse")
    "low_contributors": 10.0,    # [n/a]   concept from blog; cutoff is mine. trip if fewer (and stars > MIN)
    "commit_staleness": 365.0,   # [n/a]   days since last push; trip if older
    "low_issues": 0.001,         # [n/a]   open_issues / stars; trip if lower (and stars > MIN)
}

# Baselines are display-only ("typical organic looks like this") — NOT used in
# any scoring math. The profile/ratio ones come from the blog's measured tables.
BASELINES: dict[str, float] = {
    "fork_to_star": 0.16,        # [organic] blog avg 0.160
    "ghost_pct": 0.01,           # [organic] "about 1%"
    "suspicious_pct": 0.00,      # [organic] "0.0%"
    "zero_followers_pct": 0.10,  # [organic] 6-12%
    "zero_repos_pct": 0.05,      # [organic] 2-6%
    "zero_following_pct": 0.40,  # [n/a]     estimate; not measured by the blog
    "young_median_age": 3000.0,  # [organic] medians 2967-4801d (low end)
    "watcher_to_star": 0.015,    # [organic] range 0.005-0.030
    "temporal_burst": 0.05,      # [n/a]     not in the blog's study
    "low_contributors": 50.0,    # [n/a]     my reference, not from the blog
    "commit_staleness": 30.0,    # [n/a]     my reference, not from the blog
    "low_issues": 0.02,          # [n/a]     my reference, not from the blog
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
