from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Signal:
    name: str
    value: float
    baseline: float
    threshold: float
    weight: int
    tripped: bool
    severity: float  # 0.0-1.0
    detail: str
    caveat: str | None = None


@dataclass
class Verdict:
    score: int
    band: str
    signals: list[Signal]
    sample_size: int
    repo: str
    notes: list[str] = field(default_factory=list)
    # Layer-C two-axis breakdown (None = not assessed, e.g. too few stargazers).
    stargazer_score: int | None = None
    usage_score: int | None = None
