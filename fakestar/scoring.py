from __future__ import annotations

from .baselines import band_for
from .models import Signal, Verdict


def score_signals(
    signals: list[Signal],
    repo: str,
    sample_size: int,
    notes: list[str] | None = None,
) -> Verdict:
    raw = sum(s.weight * s.severity for s in signals)
    score = max(0, min(100, round(raw)))
    return Verdict(
        score=score,
        band=band_for(score),
        signals=signals,
        sample_size=sample_size,
        repo=repo,
        notes=notes or [],
    )
