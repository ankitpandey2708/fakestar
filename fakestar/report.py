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

# Presentation metadata per signal: (friendly label, healthy direction, formatter).
# "good" = which way is healthy ("low" or "high") — lets us phrase the safe line
# as "healthy: under/over X" so the reader never has to reason about < or >.
_META: dict[str, tuple[str, str, str]] = {
    "fork_to_star":       ("Forks (per 1k stars)",         "high", "per_k"),
    "watcher_to_star":    ("Watchers (per 1k stars)",      "high", "per_k"),
    "ghost_pct":          ("Empty 'ghost' accounts",       "low",  "pct"),
    "suspicious_pct":     ("New low-activity accounts",    "low",  "pct"),
    "zero_followers_pct": ("Stargazers with 0 followers",  "low",  "pct"),
    "zero_repos_pct":     ("Stargazers with 0 repos",      "low",  "pct"),
    "zero_following_pct": ("Stargazers following nobody",  "low",  "pct"),
    "young_median_age":   ("Median stargazer account age", "high", "days"),
    "temporal_burst":     ("Biggest 1-day star burst",     "low",  "pct"),
    "low_contributors":   ("Contributors",                 "high", "count"),
    "commit_staleness":   ("Days since last commit",       "low",  "days"),
    "low_issues":         ("Open issues (per 1k stars)",   "high", "per_k"),
}
_LABEL_W = 32


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


def _meta(name: str) -> tuple[str, str, str]:
    return _META.get(name, (name, "low", "count"))


def _row(s: Signal, with_hint: bool) -> str:
    label, good, kind = _meta(s.name)
    line = f"  - {label:<{_LABEL_W}}{_fmt(s.value, kind)}"
    if with_hint:
        word = "under" if good == "low" else "over"
        line += f"   (healthy: {word} {_fmt(s.threshold, kind)})"
    return line


def _detailed_table(verdict: Verdict) -> list[str]:
    lines = [f"{'SIGNAL':<18}{'VALUE':>10}{'BASELINE':>10}{'THRESH':>10}  TRIPPED",
             "-" * 60]
    for s in verdict.signals:
        mark = "YES" if s.tripped else "no"
        lines.append(
            f"{s.name:<18}{s.value:>10}{s.baseline:>10}{s.threshold:>10}  {mark}")
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

    if detailed:
        lines += _detailed_table(verdict)
    else:
        flagged = [s for s in verdict.signals if s.tripped]
        healthy = [s for s in verdict.signals if not s.tripped]
        if flagged:
            lines.append(f"Red flags ({len(flagged)}):")
            lines += [_row(s, with_hint=True) for s in flagged]
            if healthy:
                lines += ["", f"Looks healthy ({len(healthy)}):"]
                lines += [_row(s, with_hint=False) for s in healthy]
        else:
            lines.append(f"No red flags. All {len(healthy)} checks look healthy:")
            lines += [_row(s, with_hint=False) for s in healthy]

    caveats = [s.caveat for s in verdict.signals if s.caveat]
    if caveats or verdict.notes:
        lines.append("")
        lines.append("Notes:")
        for n in verdict.notes:
            lines.append(f"  - {n}")
        for c in dict.fromkeys(caveats):  # dedupe, keep order
            lines.append(f"  - {c}")
    return "\n".join(lines)
