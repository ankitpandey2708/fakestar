from __future__ import annotations

import json
from dataclasses import asdict

from .models import Signal, Verdict

_GREEN, _YELLOW, _RED, _RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[0m"
_BAND_COLOR = {
    "LIKELY ORGANIC": _GREEN,
    "SUSPICIOUS": _YELLOW,
    "LIKELY MANIPULATED": _RED,
}

# Presentation metadata per signal: (label, healthy direction, formatter, group).
# "good" = which way is healthy ("low" or "high"); it lets us phrase the trip
# condition in words ("flag if over/under X") so the reader never decodes < / >.
_META: dict[str, tuple[str, str, str, str]] = {
    # group: who starred it
    "ghost_pct":          ("Empty 'ghost' accounts",       "low",  "pct",   "Who starred it"),
    "suspicious_pct":     ("New low-activity accounts",    "low",  "pct",   "Who starred it"),
    "zero_followers_pct": ("Stargazers with 0 followers",  "low",  "pct",   "Who starred it"),
    "zero_repos_pct":     ("Stargazers with 0 repos",      "low",  "pct",   "Who starred it"),
    "zero_following_pct": ("Stargazers following nobody",  "low",  "pct",   "Who starred it"),
    "young_median_age":   ("Median account age",           "high", "days",  "Who starred it"),
    "temporal_burst":     ("Biggest 1-day star burst",     "low",  "pct",   "Who starred it"),
    # group: is the code actually used
    "fork_to_star":       ("Forks (per 1k stars)",         "high", "per_k", "Is the code actually used"),
    "watcher_to_star":    ("Watchers (per 1k stars)",      "high", "per_k", "Is the code actually used"),
    "low_issues":         ("Open issues (per 1k stars)",   "high", "per_k", "Is the code actually used"),
    # group: is the project real & active
    "low_contributors":   ("Contributors",                 "high", "count", "Is the project real & active"),
    "commit_staleness":   ("Days since last commit",       "low",  "days",  "Is the project real & active"),
}
_GROUP_ORDER = ["Who starred it", "Is the code actually used", "Is the project real & active"]
_OTHER = "Other checks"
_LABEL_W = 30
_VALUE_W = 11


def render_json(verdict: Verdict) -> str:
    payload = {
        "repo": verdict.repo,
        "score": verdict.score,
        "band": verdict.band,
        "sample_size": verdict.sample_size,
        "notes": verdict.notes,
        "signals": [asdict(s) for s in verdict.signals],
    }
    return json.dumps(payload, indent=2)


def _fmt(value: float, kind: str) -> str:
    if kind == "pct":
        return f"{value * 100:.0f}%"
    if kind == "per_k":
        return f"{value * 1000:.0f} per 1k"
    if kind == "days":
        return f"{value:.0f} days"
    return f"{value:.0f}"  # count


def _meta(name: str) -> tuple[str, str, str, str]:
    return _META.get(name, (name, "low", "count", _OTHER))


def _row(s: Signal) -> str:
    label, good, kind, _group = _meta(s.name)
    marker = "FLAG" if s.tripped else "OK"
    value = _fmt(s.value, kind)
    word = "over" if good == "low" else "under"  # which direction trips it
    hint = f"(flag if {word} {_fmt(s.threshold, kind)})"
    return f"  {marker:<4}  {label:<{_LABEL_W}}{value:<{_VALUE_W}}  {hint}"


def _detailed_table(verdict: Verdict) -> list[str]:
    lines = [f"{'SIGNAL':<18}{'VALUE':>10}{'BASELINE':>10}{'THRESH':>10}  TRIPPED",
             "-" * 60]
    for s in verdict.signals:
        mark = "YES" if s.tripped else "no"
        lines.append(
            f"{s.name:<18}{s.value:>10}{s.baseline:>10}{s.threshold:>10}  {mark}")
    return lines


def _grouped(verdict: Verdict) -> list[str]:
    flagged = sum(1 for s in verdict.signals if s.tripped)
    total = len(verdict.signals)
    if flagged:
        summary = f"Result:  {flagged} red flag(s) - look for FLAG below"
    else:
        summary = f"Result:  no red flags - all {total} checks healthy"

    buckets: dict[str, list[Signal]] = {}
    for s in verdict.signals:
        buckets.setdefault(_meta(s.name)[3], []).append(s)

    lines = [summary, ""]
    for group in _GROUP_ORDER + [_OTHER]:
        rows = buckets.get(group)
        if not rows:
            continue
        lines.append(f"{group}:")
        lines += [_row(s) for s in rows]
        lines.append("")
    return lines


def render_text(verdict: Verdict, color: bool = False, detailed: bool = False) -> str:
    band = verdict.band
    if color:
        band = f"{_BAND_COLOR.get(verdict.band, '')}{verdict.band}{_RESET}"
    lines = [
        f"Repo:    {verdict.repo}",
        f"Verdict: {band}   (risk {verdict.score} / 100)",
        f"Sample:  {verdict.sample_size} stargazers analyzed",
        "",
    ]
    lines += _detailed_table(verdict) if detailed else _grouped(verdict)

    caveats = [s.caveat for s in verdict.signals if s.caveat]
    if caveats or verdict.notes:
        lines.append("Notes:")
        for n in verdict.notes:
            lines.append(f"  - {n}")
        for c in dict.fromkeys(caveats):  # dedupe, keep order
            lines.append(f"  - {c}")
    return "\n".join(lines).rstrip() + "\n"
