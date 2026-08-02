"""When the stars arrived.

Organic attention arrives in waves — a launch, a conference talk, a viral post —
so a spike alone proves nothing. What the labeled data separates is the SHARE of
a repo's whole history landing in its single busiest month: control repos median
14%, manipulated repos median 100%. Purchased stars don't have a history to
spread across.

That framing only works on a full history. Measuring "biggest month" over a
partial slice inflates it mechanically, so the caller checks coverage before
letting this be scored.
"""
from __future__ import annotations

from datetime import date

from ..models import Measurement


def _monthly(daily: tuple[tuple[date, int], ...]) -> dict[tuple[int, int], int]:
    months: dict[tuple[int, int], int] = {}
    for day, count in daily:
        key = (day.year, day.month)
        months[key] = months.get(key, 0) + count
    return months


def measure(daily: tuple[tuple[date, int], ...]) -> list[Measurement]:
    """Share of observed stars falling in the single busiest month."""
    total = sum(c for _, c in daily)
    if total <= 0:
        return []
    months = _monthly(daily)
    peak_key = max(months, key=lambda k: months[k])
    peak = months[peak_key]
    fraction = peak / total
    label = f"{peak_key[0]}-{peak_key[1]:02d}"
    if len(months) == 1:
        detail = f"all {total:,} observed stars landed in {label}"
    else:
        detail = (f"{peak:,} of {total:,} observed stars ({fraction:.0%}) "
                  f"landed in {label}, the busiest of {len(months)} months")
    return [Measurement("burst", fraction, total, detail)]
