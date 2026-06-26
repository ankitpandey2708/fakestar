from __future__ import annotations

from ..baselines import BASELINES, MIN_STARS_FOR_RATIO, THRESHOLDS, WEIGHTS
from ..models import Signal

_CAVEAT = "Low forks/watchers can be normal for curated lists, docs, or tutorials."


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def analyze_ratios(repo: dict) -> list[Signal]:
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    watchers = repo.get("subscribers_count", 0) or 0

    fs = forks / stars if stars else 0.0
    ws = watchers / stars if stars else 0.0

    fs_thr = THRESHOLDS["fork_to_star"]
    fs_tripped = fs < fs_thr and stars > MIN_STARS_FOR_RATIO
    fs_sev = _clamp((fs_thr - fs) / fs_thr) if fs_tripped else 0.0

    ws_thr = THRESHOLDS["watcher_to_star"]
    ws_tripped = stars > 0 and ws < ws_thr
    ws_sev = _clamp((ws_thr - ws) / ws_thr) if ws_tripped else 0.0

    return [
        Signal(
            name="fork_to_star", value=round(fs, 4),
            baseline=BASELINES["fork_to_star"], threshold=fs_thr,
            weight=WEIGHTS["fork_to_star"], tripped=fs_tripped, severity=fs_sev,
            detail=f"{forks} forks / {stars} stars = {fs:.4f}", caveat=_CAVEAT,
        ),
        Signal(
            name="watcher_to_star", value=round(ws, 4),
            baseline=BASELINES["watcher_to_star"], threshold=ws_thr,
            weight=WEIGHTS["watcher_to_star"], tripped=ws_tripped, severity=ws_sev,
            detail=f"{watchers} watchers / {stars} stars = {ws:.4f}", caveat=_CAVEAT,
        ),
    ]

