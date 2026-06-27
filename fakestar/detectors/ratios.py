from __future__ import annotations

from ..baselines import MIN_STARS_FOR_RATIO, THRESHOLDS
from ..models import Signal
from ._common import make_signal, sev_low

_CAVEAT = "Low forks/watchers can be normal for curated lists, docs, or tutorials."


def analyze_ratios(repo: dict) -> list[Signal]:
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    watchers = repo.get("subscribers_count", 0) or 0

    fs = forks / stars if stars else 0.0
    ws = watchers / stars if stars else 0.0

    fs_thr = THRESHOLDS["fork_to_star"]
    fs_tripped = fs < fs_thr and stars > MIN_STARS_FOR_RATIO

    ws_thr = THRESHOLDS["watcher_to_star"]
    ws_tripped = stars > 0 and ws < ws_thr

    return [
        make_signal(
            "fork_to_star", round(fs, 4), fs_tripped, sev_low(fs, fs_thr, fs_tripped),
            f"{forks} forks / {stars} stars = {fs:.4f}", caveat=_CAVEAT),
        make_signal(
            "watcher_to_star", round(ws, 4), ws_tripped, sev_low(ws, ws_thr, ws_tripped),
            f"{watchers} watchers / {stars} stars = {ws:.4f}", caveat=_CAVEAT),
    ]
