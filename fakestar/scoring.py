"""Scoring: turn a repo's measured signals into a Verdict, using the data-derived
calibration (corpus/calibration.json, produced by tools/build_calibration.py).

Each signal's severity is anchored to two points measured from labeled data:
  - the ORGANIC anchor -> severity 0.0  (a typical legitimate repo/cohort)
  - the FAKE anchor    -> severity 1.0  (a typical manipulated repo/cohort)
linearly interpolated + clamped. When the fake anchor is LOWER than the organic
one (e.g. account age, fork ratio), severity rises as the value falls.

Layers: (A) shrink sampled signals toward the organic anchor by sample size and
abstain below a floor; (B) anchored severity; (C) combine each axis by WEIGHTED
MEAN so correlated signals can't multi-count, overall = max(stargazer, usage).
This module reads only the small derived artifact, never the raw dataset.
"""
from __future__ import annotations

import json
from pathlib import Path

from .baselines import (ABSTAIN_BELOW_N, PROFILE_SIGNALS, SHRINK_PSEUDOCOUNT,
                        STARGAZER_GROUP, UNCALIBRATED, USAGE_GROUP, WEIGHTS,
                        band_for)
from .models import Signal, Verdict

UNCERTAIN = "UNCERTAIN"
SHRINK_K = SHRINK_PSEUDOCOUNT

# Knobs come from baselines.py; only the MEASURED anchors come from the artifact.
_CALIB_PATH = Path(__file__).resolve().parent.parent / "corpus" / "calibration.json"


def _load():
    try:
        data = json.loads(_CALIB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    anchors = {k: tuple(v) for k, v in data.get("anchors", {}).items()
               if not k.startswith("_")}
    return data, anchors


_DATA, ANCHORS = _load()


# ---- per-signal severity (Layers A + B) ------------------------------------
def shrink(name: str, value: float, n: int) -> float:
    """Pull a sample-estimated value toward its organic anchor by sample size n
    (empirical-Bayes): (n*value + k*organic) / (n + k)."""
    if name not in ANCHORS:
        return value
    organic = ANCHORS[name][0]
    return (n * value + SHRINK_K * organic) / (n + SHRINK_K)


def anchored_severity(name: str, value: float) -> float | None:
    """Severity in [0,1] from the two empirical anchors, or None if uncalibrated."""
    if name not in ANCHORS:
        return None
    org, fake = ANCHORS[name]
    if fake == org:
        return 0.0
    return max(0.0, min(1.0, (value - org) / (fake - org)))


def _severity(s, sample_size, abstain):
    """Per-signal severity after Layer-A correction. None = no information."""
    is_profile = s.name in PROFILE_SIGNALS
    if is_profile and abstain:
        return None
    value = s.value
    if is_profile and sample_size is not None:
        value = shrink(s.name, s.value, sample_size)
    new = anchored_severity(s.name, value)
    return s.severity if new is None else new


def calibrated_severity(signal, sample_size: int | None = None):
    """Public per-signal severity (for report display, so markers match the score).
    None = no information (abstained profile signal)."""
    abstain = sample_size is not None and sample_size < ABSTAIN_BELOW_N
    return _severity(signal, sample_size, abstain)


def axis_of(name: str) -> str:
    """Which display/scoring axis a signal belongs to."""
    if name in UNCALIBRATED:
        return "advisory"
    if name in STARGAZER_GROUP:
        return "stargazer"
    if name in USAGE_GROUP:
        return "usage"
    return "other"


# ---- aggregation (Layer C) -------------------------------------------------
def _weighted_mean(sevs: dict[str, float], group: list[str]):
    """Combine a group's severities by WEIGHTED MEAN (not sum), so correlated
    signals can't multi-count. UNCALIBRATED signals (no fake-vs-organic data) are
    excluded from scoring. Returns None if the group has no scorable information."""
    num = den = 0.0
    for name in group:
        if name in UNCALIBRATED:
            continue
        sev = sevs.get(name)
        if sev is None:
            continue
        w = WEIGHTS.get(name, 0)
        num += w * sev
        den += w
    return (num / den) if den else None


def subscores(signals, sample_size: int | None = None) -> dict:
    """Two de-correlated axes (stargazer-quality, real-usage), each a 0-100
    weighted-mean severity, plus overall = max(axes)*100."""
    abstain = sample_size is not None and sample_size < ABSTAIN_BELOW_N
    sevs = {s.name: _severity(s, sample_size, abstain) for s in signals}

    star = None if abstain else _weighted_mean(sevs, STARGAZER_GROUP)
    usage = _weighted_mean(sevs, USAGE_GROUP)
    parts = [x for x in (star, usage) if x is not None]
    overall = max(parts) if parts else 0.0

    return {
        "score": round(100 * overall),
        "stargazer_score": None if star is None else round(100 * star),
        "usage_score": None if usage is None else round(100 * usage),
        "low_confidence": abstain,
        "sample_size": sample_size,
    }


# ---- verdict ----------------------------------------------------------------
def score_signals(
    signals: list[Signal],
    repo: str,
    sample_size: int,
    notes: list[str] | None = None,
) -> Verdict:
    notes = notes or []

    # Hard override: a deleted (404) repo is a strong manipulation signal on its
    # own, independent of any sampling.
    if any(s.name == "repo_deleted" and s.tripped for s in signals):
        return Verdict(score=100, band="LIKELY MANIPULATED", signals=signals,
                       sample_size=sample_size, repo=repo, notes=notes,
                       stargazer_score=None, usage_score=None)

    res = subscores(signals, sample_size)
    band = band_for(res["score"])

    # Honesty guard: when too few stargazers were sampled the stargazer axis is
    # unassessed; a "clean" verdict can't be trusted -> UNCERTAIN. Never masks a
    # flag raised by the (exact, sampling-independent) usage axis.
    if res["low_confidence"] and band == "LIKELY ORGANIC":
        band = UNCERTAIN

    return Verdict(
        score=res["score"],
        band=band,
        signals=signals,
        sample_size=sample_size,
        repo=repo,
        notes=notes,
        stargazer_score=res["stargazer_score"],
        usage_score=res["usage_score"],
    )
