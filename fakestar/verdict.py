"""Turning measurements into a verdict — and refusing to when we shouldn't.

Three rules govern everything here:

  1. A measurement may only be compared to a reference produced the same way.
     Cohort fingerprints are anchored on all-time stargazer populations, so a
     sample of a repo's *recent* stargazers is measured and displayed but never
     scored. Skipping this rule is what makes healthy popular repos look bought.

  2. Coverage is part of the answer, not a footnote. A verdict drawn from a
     tenth of the stars is a different object from one drawn from all of them,
     and says so on its face.

  3. Silence beats a guess. With no scorable evidence the answer is
     INSUFFICIENT EVIDENCE, and a clean structural reading alone can never be
     promoted to a clean verdict.
"""
from __future__ import annotations

from .baselines import (ANCHORS, COHORT_SIGNALS, HIGH_COVERAGE, INSUFFICIENT,
                        MIN_ACCOUNTS, MIN_COVERAGE, RECENT_SIGNALS,
                        STRUCTURAL_SIGNALS, WEIGHTS, anchored_severity,
                        band_for, clamp01, confidence_for, infer_kind,
                        peer_reference, recent_reference, shrink)
from .evidence import RepoFacts, StarSample
from .models import Measurement, Signal, Verdict

# Reasons a measurement was left unscored, in the words the report will use.
_RECENT_ONLY = ("sampled from recent stars only; the fake-vs-organic reference "
                "describes all-time stargazers, so this is not comparable")
_TOO_FEW = "too few accounts sampled to be meaningful"
_THIN_COVERAGE = "too small a share of this repo's stars to represent them"
_PARTIAL_HISTORY = ("needs most of the star history; only part of it is on "
                    "record, which inflates any single month's share")
_UNEVEN_HISTORY = ("the record captures recent months far less completely than "
                   "older ones, which distorts any month-to-month comparison")
_NO_PEERS = "no comparable repositories on file for this kind and size"


def _cohort_scorable(sample: StarSample, accounts: int) -> str | None:
    """None if the cohort may be scored, else the reason it may not."""
    if not sample.provenance.is_all_time:
        return _RECENT_ONLY
    if accounts < MIN_ACCOUNTS:
        return _TOO_FEW
    if sample.coverage.fraction < MIN_COVERAGE:
        return _THIN_COVERAGE
    return None


RECENT_PREFIX = "recent_"
_TOO_FEW_RECENT = "too few recent stargazers to judge"
_NO_RECENT_PEERS = ("no measured norm for what a comparable repo's newest "
                    "stargazers look like")


def _signal(m: Measurement, severity: float | None, reference: float | None,
            note: str | None, prefix: str = "") -> Signal:
    """Every signal is a measurement plus a reference, a severity and a reason.
    Only those three differ between the families; the rest is bookkeeping."""
    return Signal(name=prefix + m.name, value=m.value, severity=severity,
                  reference=reference, weight=WEIGHTS.get(m.name, 0),
                  detail=m.detail, n=m.n, note=note)


def _cohort_signal(m: Measurement, blocked: str | None) -> Signal:
    """Judged against the labeled all-time anchors, shrunk by sample size."""
    pair = ANCHORS.get(m.name)
    severity = (None if blocked is not None
                else anchored_severity(m.name, shrink(m.name, m.value, m.n)))
    return _signal(m, severity, pair[0] if pair else None, blocked)


def _structural_signal(m: Measurement, kind: str, stars: int) -> Signal:
    """Judged against fork/watcher ratios of same-kind, same-size repos."""
    ref = peer_reference(kind, stars, m.name)
    if ref is None:
        return _signal(m, None, None, _NO_PEERS)
    reference, peers = ref
    # Fake anchor is zero: no forks at all is as far from normal as it goes.
    severity = (0.0 if m.value >= reference or reference <= 0
                else clamp01((reference - m.value) / reference))
    return _signal(m, severity, reference,
                   f"compared against {peers} {kind} repos of similar size")


def _recent_signal(m: Measurement, kind: str, stars: int) -> Signal:
    """Judged against the NEWEST stargazers of comparable repos.

    Never against the all-time anchors: whoever finds a project this week is
    newer and emptier than its lifetime average, so that comparison condemns
    healthy repos. Measured on ordinary awesome-lists, recent zero-follower
    rates run 40-82% against an all-time organic norm of 36%.
    """
    ref = recent_reference(kind, stars, m.name)
    if ref is None:
        return _signal(m, None, None, _NO_RECENT_PEERS, RECENT_PREFIX)
    ceiling, far, peers = ref
    severity = (0.0 if m.value <= ceiling
                else clamp01((m.value - ceiling) / (far - ceiling)))
    return _signal(m, severity, ceiling,
                   f"vs the newest stargazers of {peers} comparable repos",
                   RECENT_PREFIX)


def _weighted_mean(signals: list[Signal], names) -> float | None:
    num = den = 0.0
    for s in signals:
        if s.name not in names or s.severity is None:
            continue
        num += s.weight * s.severity
        den += s.weight
    return (num / den) if den else None


def assess(facts: RepoFacts, sample: StarSample, measurements: list[Measurement],
           accounts_sampled: int, context: list[Signal] | None = None,
           notes: list[str] | None = None,
           recent_measurements: list[Measurement] | None = None,
           recent_accounts: int = 0) -> Verdict:
    kind = infer_kind(facts)
    blocked = _cohort_scorable(sample, accounts_sampled)
    coverage = sample.coverage

    signals: list[Signal] = []
    for m in measurements:
        if m.name in STRUCTURAL_SIGNALS:
            signals.append(_structural_signal(m, kind, facts.stars))
        elif m.name == "burst":
            # A partial history mechanically concentrates stars into fewer
            # months, so the busiest-month share only means something when most
            # of the history is on record AND the record is even across it.
            # Recent months being captured worse than old ones would understate
            # a recent spike and overstate an old one.
            reason = blocked
            if reason is None and coverage.blind_to_recent:
                reason = _UNEVEN_HISTORY
            if reason is None and coverage.fraction < HIGH_COVERAGE:
                reason = _PARTIAL_HISTORY
            signals.append(_cohort_signal(m, reason))
        elif m.name in COHORT_SIGNALS:
            signals.append(_cohort_signal(m, blocked))

    # Third axis: the newest stars, which the archive largely cannot see. Judged
    # only against peers measured through the same recent-window pipeline.
    recent_names: list[str] = []
    if recent_measurements and recent_accounts >= MIN_ACCOUNTS:
        for m in recent_measurements:
            if m.name not in RECENT_SIGNALS:
                continue
            sig = _recent_signal(m, kind, facts.stars)
            signals.append(sig)
            recent_names.append(sig.name)
    elif recent_measurements:
        for m in recent_measurements:
            if m.name in RECENT_SIGNALS:
                sig = _signal(m, None, None, _TOO_FEW_RECENT, RECENT_PREFIX)
                signals.append(sig)
                recent_names.append(sig.name)

    cohort = _weighted_mean(signals, COHORT_SIGNALS)
    structural = _weighted_mean(signals, STRUCTURAL_SIGNALS)
    recent = _weighted_mean(signals, recent_names) if recent_names else None

    parts = [p for p in (cohort, structural, recent) if p is not None]
    score = round(100 * max(parts)) if parts else None

    if score is None:
        band = INSUFFICIENT
    elif cohort is None and recent is None:
        # Structural evidence alone. It can accuse, but it cannot acquit: plenty
        # of manipulated repos have ordinary fork counts.
        band = band_for(score)
        if band == "LIKELY ORGANIC":
            band = INSUFFICIENT
    else:
        band = band_for(score)

    return Verdict(
        repo=facts.full_name,
        band=band,
        score=score,
        confidence=confidence_for(accounts_sampled, coverage.fraction),
        signals=signals,
        context=list(context or []),
        notes=list(notes or []),
        coverage=coverage.describe(accounts_sampled),
        accounts_sampled=accounts_sampled,
        provenance=sample.provenance.value,
        blind_spot=(
            f"the record is currently capturing ~{coverage.recent_capture:.0%} "
            f"of this repo's stars, so the last few months went unexamined"
            if coverage.blind_to_recent else ""),
        cohort_score=None if cohort is None else round(100 * cohort),
        structural_score=None if structural is None else round(100 * structural),
    )
