"""Rendering a verdict a human can act on.

Every row says three things: what was measured, what normal looks like, and
whether this one is normal. Rows that could not be judged say why, in words,
rather than quietly showing a number that invites the reader to judge it anyway.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from .models import Signal, Verdict

_GREEN, _YELLOW, _RED, _CYAN, _DIM, _RESET = (
    "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[36m", "\x1b[2m", "\x1b[0m")
_BAND_COLOR = {
    "LIKELY ORGANIC": _GREEN,
    "SUSPICIOUS": _YELLOW,
    "LIKELY MANIPULATED": _RED,
    "INSUFFICIENT EVIDENCE": _CYAN,
}

# label, formatter, which direction is healthy
_META: dict[str, tuple[str, str, str]] = {
    "zero_followers_pct": ("Stargazers with no followers", "pct", "low"),
    "ghost_pct":          ("Completely empty accounts", "pct", "low"),
    "zero_repos_pct":     ("Stargazers with no repos", "pct", "low"),
    "suspicious_pct":     ("New and inactive accounts", "pct", "low"),
    "young_median_age":   ("Median account age", "days", "high"),
    "deleted_pct":        ("Accounts since deleted", "pct", "low"),
    "burst":              ("Stars in the busiest month", "pct", "low"),
    "fork_to_star":       ("Forks per 1k stars", "per_k", "high"),
    "watcher_to_star":    ("Watchers per 1k stars", "per_k", "high"),
    "contributors":       ("Contributors", "count", "high"),
    "commit_staleness":   ("Days since last commit", "days", "low"),
    "open_issues":        ("Open issues", "count", "high"),
}
_GROUPS = (
    ("Who starred it", ("zero_followers_pct", "ghost_pct", "zero_repos_pct",
                        "suspicious_pct", "young_median_age", "deleted_pct",
                        "burst")),
    ("Who starred it recently", ("recent_zero_followers_pct", "recent_ghost_pct",
                                 "recent_zero_repos_pct",
                                 "recent_suspicious_pct")),
    ("Stars against forks and watchers", ("fork_to_star", "watcher_to_star")),
)
_LABEL_W, _VALUE_W = 30, 10


def _fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "per_k":
        return f"{value * 1000:.0f}"
    if kind == "days":
        return f"{value:,.0f}d"
    return f"{value:,.0f}"


def _meta(name: str) -> tuple[str, str, str]:
    if name.startswith("recent_"):
        label, kind, healthy = _META.get(name[len("recent_"):],
                                         (name, "count", "low"))
        return label, kind, healthy
    return _META.get(name, (name, "count", "low"))


def _row(s: Signal, shared_note: str | None = None) -> str:
    """One line. `shared_note` is the reason already printed for the whole
    group, so an identical explanation isn't repeated on every row."""
    label, kind, healthy = _meta(s.name)
    value = _fmt(s.value, kind)
    if s.severity is None:
        marker = "  ? "
        if s.note and s.note != shared_note:
            trailer = f"not scored: {s.note}"
        else:
            trailer = "not scored"
    else:
        marker = "FLAG" if s.flagged else ("HIGH" if s.elevated else "  OK")
        if s.reference is None:
            trailer = ""
        else:
            word = "typical floor" if healthy == "high" else "typical"
            trailer = f"{word} {_fmt(s.reference, kind)}"
            if s.note and s.flagged:
                trailer += f"  ({s.note})"
    return f"  {marker}  {label:<{_LABEL_W}}{value:>{_VALUE_W}}   {trailer}".rstrip()


def _context_row(s: Signal) -> str:
    label, kind, _ = _meta(s.name)
    return f"    ·   {label:<{_LABEL_W}}{_fmt(s.value, kind):>{_VALUE_W}}"


_SOURCE_WORDS = {
    "archive": "public star archive (spans the repo's history)",
    "list": "GitHub stargazer list (spans the repo's history)",
    "events": "GitHub event feed (recent stars only)",
    "watch": "locally recorded history",
    "none": "no stargazer identities available",
}


def render_text(verdict: Verdict, color: bool = False) -> str:
    band = verdict.band
    if color:
        band = f"{_BAND_COLOR.get(verdict.band, '')}{verdict.band}{_RESET}"
    score = "n/a" if verdict.score is None else f"{verdict.score} / 100"

    lines = [
        f"Repo:      {verdict.repo}",
        f"Verdict:   {band}   (risk {score}, confidence {verdict.confidence})",
        f"Sampled:   {verdict.coverage}",
        f"Source:    {_SOURCE_WORDS.get(verdict.provenance, verdict.provenance)}",
    ]
    if verdict.blind_spot:
        lines.append(f"Blind spot: {verdict.blind_spot}")
    lines.append("")

    by_name = {s.name: s for s in verdict.signals}
    flags = [s for s in verdict.signals if s.flagged]
    elevated = [s for s in verdict.signals if s.elevated]
    unscored = [s for s in verdict.signals if s.severity is None]
    if flags:
        extra = f", {len(elevated)} borderline" if elevated else ""
        lines.append(f"Result:    {len(flags)} of "
                     f"{len(verdict.signals) - len(unscored)} scored checks "
                     f"look wrong{extra} - marked FLAG / HIGH below")
    elif elevated:
        lines.append(f"Result:    no check is damning, but {len(elevated)} "
                     f"sit above the organic norm - marked HIGH below")
    elif len(unscored) == len(verdict.signals):
        lines.append("Result:    nothing could be scored - see Notes")
    else:
        lines.append(f"Result:    all "
                     f"{len(verdict.signals) - len(unscored)} scored checks "
                     f"look normal")
    lines.append("")

    for title, names in _GROUPS:
        rows = [by_name[n] for n in names if n in by_name]
        if not rows:
            continue
        # When every row in a group went unscored for the same reason, say it
        # once in the heading instead of once per line.
        reasons = {s.note for s in rows if s.severity is None and s.note}
        shared = reasons.pop() if (len(reasons) == 1 and
                                   all(s.severity is None for s in rows)) else None
        lines.append(f"{title}:" if not shared else f"{title} - not scored, {shared}:")
        lines += [_row(s, shared) for s in rows]
        lines.append("")

    if verdict.context:
        lines.append("Project activity (context, never scored):")
        lines += [_context_row(s) for s in verdict.context]
        lines.append("")

    if verdict.notes:
        lines.append("Notes:")
        lines += [f"  - {n}" for n in verdict.notes]

    return "\n".join(lines).rstrip() + "\n"


def render_json(verdict: Verdict) -> str:
    payload = {
        "repo": verdict.repo,
        "verdict": verdict.band,
        "score": verdict.score,
        "confidence": verdict.confidence,
        "coverage": verdict.coverage,
        "blind_spot": verdict.blind_spot,
        "source": verdict.provenance,
        "cohort_score": verdict.cohort_score,
        "structural_score": verdict.structural_score,
        "signals": [asdict(s) for s in verdict.signals],
        "context": [asdict(s) for s in verdict.context],
        "notes": verdict.notes,
    }
    return json.dumps(payload, indent=2)
