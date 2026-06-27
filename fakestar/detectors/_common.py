from __future__ import annotations

from datetime import datetime, timezone

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def parse_dt(s: str) -> datetime:
    # GitHub timestamps: 2024-01-02T03:04:05Z
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def make_signal(
    name: str, value: float, tripped: bool, severity: float, detail: str,
    caveat: str | None = None,
) -> Signal:
    """Build a Signal, pulling baseline/threshold/weight from the registries."""
    return Signal(
        name=name, value=value, baseline=BASELINES[name],
        threshold=THRESHOLDS[name], weight=WEIGHTS[name],
        tripped=tripped, severity=severity, detail=detail, caveat=caveat,
    )


def sev_low(value: float, thr: float, tripped: bool) -> float:
    """Severity for 'lower is worse': how far value sits below the threshold."""
    return clamp((thr - value) / thr) if tripped and thr > 0 else 0.0


def sev_high(value: float, thr: float, tripped: bool) -> float:
    """Severity for 'higher is worse', normalized to the headroom above thr."""
    return clamp((value - thr) / (1 - thr)) if tripped and thr < 1 else 0.0


def sev_ratio(value: float, thr: float, tripped: bool) -> float:
    """Severity for 'higher is worse', measured relative to the threshold."""
    return clamp((value - thr) / thr) if tripped and thr > 0 else 0.0
