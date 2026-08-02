"""The three things that flow through the pipeline: a Measurement (what we
observed), a Signal (a measurement placed against a reference), and a Verdict
(what we're willing to say out loud)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Measurement:
    """An observed quantity and the sample size behind it. Carries no judgement."""

    name: str
    value: float
    n: int
    detail: str


@dataclass(frozen=True)
class Signal:
    """A measurement judged against a reference.

    `severity` is None when the measurement exists but cannot be judged — no
    reference, provenance mismatch, or too small a sample. That is different
    from a severity of 0.0, which is a real finding: this looks normal.
    """

    name: str
    value: float
    severity: float | None
    reference: float | None
    weight: int
    detail: str
    n: int = 0
    note: str | None = None

    @property
    def scored(self) -> bool:
        return self.severity is not None

    @property
    def flagged(self) -> bool:
        return self.severity is not None and self.severity >= 0.5

    @property
    def elevated(self) -> bool:
        """Worse than typical but short of damning.

        Without this, a value three times the organic norm can still print as
        OK because it sits well below the fake anchor — technically true, and
        exactly the kind of thing that makes a reader stop trusting the tool.
        """
        return self.severity is not None and 0.25 <= self.severity < 0.5


@dataclass
class Verdict:
    repo: str
    band: str
    score: int | None            # None when there is nothing scorable
    confidence: str              # high | medium | low
    signals: list[Signal] = field(default_factory=list)
    context: list[Signal] = field(default_factory=list)   # shown, never scored
    notes: list[str] = field(default_factory=list)
    coverage: str = ""
    accounts_sampled: int = 0    # profiles actually fetched, not the pool size
    provenance: str = "none"
    cohort_score: int | None = None
    structural_score: int | None = None
    # Set when the record no longer keeps up with the repo, so recent stars —
    # where a live campaign would be — went unexamined.
    blind_spot: str = ""
