from __future__ import annotations

import json
from dataclasses import asdict

from .models import Verdict

_GREEN, _YELLOW, _RED, _RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[0m"
_BAND_COLOR = {
    "LIKELY ORGANIC": _GREEN,
    "SUSPICIOUS": _YELLOW,
    "LIKELY MANIPULATED": _RED,
}


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


def render_text(verdict: Verdict, color: bool = False) -> str:
    lines: list[str] = []
    band = verdict.band
    if color:
        band = f"{_BAND_COLOR.get(verdict.band, '')}{verdict.band}{_RESET}"
    lines.append(f"Repo:    {verdict.repo}")
    lines.append(f"Verdict: {band}  (risk score {verdict.score}/100)")
    lines.append(f"Sample:  {verdict.sample_size} stargazers")
    lines.append("")
    lines.append(f"{'SIGNAL':<18}{'VALUE':>10}{'BASELINE':>10}{'THRESH':>10}  TRIPPED")
    lines.append("-" * 60)
    for s in verdict.signals:
        mark = "YES" if s.tripped else "no"
        lines.append(
            f"{s.name:<18}{s.value:>10}{s.baseline:>10}{s.threshold:>10}  {mark}")
    caveats = [s.caveat for s in verdict.signals if s.caveat]
    if caveats or verdict.notes:
        lines.append("")
        lines.append("Notes & caveats:")
        for n in verdict.notes:
            lines.append(f"  - {n}")
        for c in dict.fromkeys(caveats):  # dedupe, keep order
            lines.append(f"  - {c}")
    return "\n".join(lines)
