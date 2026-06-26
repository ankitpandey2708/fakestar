from __future__ import annotations

WEIGHTS: dict[str, int] = {
    "fork_to_star": 30,
    "ghost_pct": 25,
    "suspicious_pct": 20,
    "watcher_to_star": 15,
    "temporal_burst": 10,
}

THRESHOLDS: dict[str, float] = {
    "fork_to_star": 0.05,
    "ghost_pct": 0.10,
    "suspicious_pct": 0.15,
    "watcher_to_star": 0.002,
    "temporal_burst": 0.30,
}

BASELINES: dict[str, float] = {
    "fork_to_star": 0.16,
    "ghost_pct": 0.01,
    "suspicious_pct": 0.00,
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
