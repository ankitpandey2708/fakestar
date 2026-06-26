from __future__ import annotations

from collections import Counter
from statistics import median

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def detect_burst(timestamps: list[str], k: int = 20) -> tuple[float, str]:
    if not timestamps:
        return 0.0, "no timeline data"
    days = Counter(ts[:10] for ts in timestamps)  # bin by YYYY-MM-DD
    total = len(timestamps)
    if len(days) == 1:
        # all stars on a single day: the most extreme possible burst
        (only_day, count), = days.items()
        return 1.0, f"all {count} sampled stars on {only_day} (single-day burst)"
    med = median(days.values())
    cutoff = k * med
    burst_days = {d: c for d, c in days.items() if c > cutoff}
    burst_stars = sum(burst_days.values())
    fraction = burst_stars / total
    if burst_days:
        peak_day = max(burst_days, key=burst_days.get)
        detail = (f"{burst_stars}/{total} sampled stars on {len(burst_days)} "
                  f"burst day(s) (>{k}x median {med}); peak {peak_day}="
                  f"{days[peak_day]} ({fraction:.1%})")
    else:
        detail = f"no day exceeds {k}x median daily rate ({med}); evenly spread"
    return fraction, detail


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def analyze_temporal(client, owner: str, repo: str, max_pages: int = 40) -> list[Signal]:
    timestamps = [
        item["starred_at"]
        for item in client.iter_stargazers(
            owner, repo, with_timestamps=True, max_pages=max_pages)
    ]
    fraction, detail = detect_burst(timestamps)
    thr = THRESHOLDS["temporal_burst"]
    tripped = fraction > thr
    sev = _clamp((fraction - thr) / (1 - thr)) if tripped and thr < 1 else 0.0
    return [Signal(
        name="temporal_burst", value=round(fraction, 4),
        baseline=BASELINES["temporal_burst"], threshold=thr,
        weight=WEIGHTS["temporal_burst"], tripped=tripped, severity=sev,
        detail=detail,
    )]
