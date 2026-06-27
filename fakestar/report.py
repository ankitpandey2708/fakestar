from __future__ import annotations

import json
from dataclasses import asdict

from .scoring import ANCHORS, axis_of, calibrated_severity
from .models import Signal, Verdict

_GREEN, _YELLOW, _RED, _CYAN, _RESET = (
    "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[36m", "\x1b[0m")
_BAND_COLOR = {
    "LIKELY ORGANIC": _GREEN,
    "SUSPICIOUS": _YELLOW,
    "LIKELY MANIPULATED": _RED,
    "UNCERTAIN": _CYAN,
}

# Presentation metadata per signal: (label, healthy direction, formatter).
_META: dict[str, tuple[str, str, str]] = {
    "ghost_pct":          ("Empty 'ghost' accounts",      "low",  "pct"),
    "suspicious_pct":     ("New low-activity accounts",    "low",  "pct"),
    "zero_followers_pct": ("Stargazers with 0 followers",  "low",  "pct"),
    "zero_repos_pct":     ("Stargazers with 0 repos",      "low",  "pct"),
    "zero_following_pct": ("Stargazers following nobody",  "low",  "pct"),
    "young_median_age":   ("Median account age",           "high", "days"),
    "temporal_burst":     ("Biggest star burst",           "low",  "pct"),
    "fork_to_star":       ("Forks (per 1k stars)",         "high", "per_k"),
    "watcher_to_star":    ("Watchers (per 1k stars)",      "high", "per_k"),
    "low_issues":         ("Open issues (per 1k stars)",   "high", "per_k"),
    "low_contributors":   ("Contributors",                 "high", "count"),
    "commit_staleness":   ("Days since last commit",       "low",  "days"),
}
_AXIS_TITLE = {
    "stargazer": "Who starred it",
    "usage": "Is the code actually used",
    "advisory": "Project activity (advisory, not scored)",
    "other": "Other checks",
}
_AXIS_ORDER = ["stargazer", "usage", "advisory", "other"]
_LABEL_W, _VALUE_W = 30, 11


def _fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "per_k":
        return f"{value * 1000:.0f} per 1k"
    if kind == "days":
        return f"{value:.0f} days"
    return f"{value:.0f}"


def _meta(name: str) -> tuple[str, str, str]:
    return _META.get(name, (name, "low", "count"))


def _sub(score: int | None) -> str:
    return "n/a" if score is None else f"{score}/100"


def render_json(verdict: Verdict) -> str:
    payload = {
        "repo": verdict.repo,
        "score": verdict.score,
        "band": verdict.band,
        "stargazer_score": verdict.stargazer_score,
        "usage_score": verdict.usage_score,
        "sample_size": verdict.sample_size,
        "notes": verdict.notes,
        "signals": [asdict(s) for s in verdict.signals],
    }
    return json.dumps(payload, indent=2)


def _row(s: Signal, sample_size: int) -> tuple[str, bool]:
    label, good, kind = _meta(s.name)
    axis = axis_of(s.name)
    sev = calibrated_severity(s, sample_size)
    value = _fmt(s.value, kind)

    if axis == "advisory":
        marker, flagged = "·   ", False
    elif sev is None:
        marker, flagged = "n/a ", False   # abstained: too few sampled to judge
    else:
        flagged = sev >= 0.5
        marker = "FLAG" if flagged else "OK"

    if s.name in ANCHORS:
        word = "above" if good == "low" else "below"
        ref = f"(typical organic ~{_fmt(ANCHORS[s.name][0], kind)}; worse {word})"
    else:
        ref = ""
    return f"  {marker:<4}  {label:<{_LABEL_W}}{value:<{_VALUE_W}}  {ref}", flagged


def _detailed_table(verdict: Verdict) -> list[str]:
    lines = [f"{'SIGNAL':<18}{'VALUE':>10}{'CAL.SEV':>9}{'AXIS':>11}",
             "-" * 50]
    for s in verdict.signals:
        sev = calibrated_severity(s, verdict.sample_size)
        sv = "n/a" if sev is None else f"{sev:.2f}"
        lines.append(f"{s.name:<18}{s.value:>10}{sv:>9}{axis_of(s.name):>11}")
    return lines


def _grouped(verdict: Verdict) -> list[str]:
    buckets: dict[str, list[Signal]] = {}
    for s in verdict.signals:
        buckets.setdefault(axis_of(s.name), []).append(s)

    body, flags = [], 0
    for axis in _AXIS_ORDER:
        rows = buckets.get(axis)
        if not rows:
            continue
        body.append(f"{_AXIS_TITLE[axis]}:")
        for s in rows:
            line, flagged = _row(s, verdict.sample_size)
            body.append(line)
            flags += flagged
        body.append("")

    if flags:
        summary = f"Result:  {flags} signal(s) flagged - look for FLAG below"
    else:
        summary = "Result:  no stargazer/usage signals flagged"
    return [summary, ""] + body


def render_text(verdict: Verdict, color: bool = False, detailed: bool = False) -> str:
    band = verdict.band
    if color:
        band = f"{_BAND_COLOR.get(verdict.band, '')}{verdict.band}{_RESET}"
    lines = [
        f"Repo:    {verdict.repo}",
        f"Verdict: {band}   (risk {verdict.score} / 100)",
        f"         stargazer-quality {_sub(verdict.stargazer_score)} | "
        f"real-usage {_sub(verdict.usage_score)}",
        f"Sample:  {verdict.sample_size} stargazers analyzed",
        "",
    ]
    lines += _detailed_table(verdict) if detailed else _grouped(verdict)

    caveats = [s.caveat for s in verdict.signals if s.caveat]
    if caveats or verdict.notes:
        lines.append("Notes:")
        for n in verdict.notes:
            lines.append(f"  - {n}")
        for c in dict.fromkeys(caveats):
            lines.append(f"  - {c}")
    return "\n".join(lines).rstrip() + "\n"
