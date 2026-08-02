"""Helpers common to the corpus builders.

Both builders sample peer repositories the same way — walk the star bands,
search each one, spread the draw across it, summarise the result — so that
machinery lives here rather than in two copies that drift apart.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fakestar.baselines import SIZE_BANDS  # noqa: E402

API = "https://api.github.com"

# Repos with published manipulation labels. Excluded from every peer pool: a
# bought repo must never help define what normal looks like.
KNOWN_MANIPULATED = {
    "digitalplatdev/freedomain", "shardeum/shardeum", "unionlabs/union",
    "raga-ai-hub/ragaai-catalyst", "openai/openai-fm",
}


def bands(floor: int = 200, ceiling: int = 400_000) -> list[tuple[str, int, int]]:
    """(label, low, high) per star band, clipped to a sane range."""
    out, low = [], 0
    for upper, label in SIZE_BANDS:
        high = min(upper, ceiling)
        if low < high:
            out.append((label, max(low, floor), high))
        low = upper
    return out


def search(src, query: str, pages: int) -> list[dict]:
    """Paginated repo search. Search is rate-limited far more tightly than the
    core API, hence the pause between pages."""
    items: list[dict] = []
    for page in range(1, pages + 1):
        try:
            data = src._request(
                f"{API}/search/repositories?q={query}&per_page=100&page={page}"
                f"&sort=stars&order=desc").json()
        except Exception as exc:
            if type(exc).__name__ == "RateLimited":
                raise
            print(f"  search failed ({exc}); stopping this query", file=sys.stderr)
            break
        batch = data.get("items") or []
        items.extend(batch)
        if len(batch) < 100:
            break
        time.sleep(2)
    return items


def spread(items: list, n: int) -> list:
    """An evenly-spaced draw spanning the list, rather than skimming its top."""
    if len(items) <= n:
        return list(items)
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def dedupe(pool: list[dict]) -> list[dict]:
    """Unique repos, minus anything with a published manipulation label."""
    seen, out = set(), []
    for it in pool:
        full = (it.get("full_name") or "").lower()
        if full and full not in seen and full not in KNOWN_MANIPULATED:
            seen.add(full)
            out.append(it)
    return out


def percentiles(values: list[float]) -> dict[str, float]:
    """p10 matters for signals where lower is worse; p90 for the rest."""
    vs = sorted(values)
    if not vs:
        return {}

    def q(p: float) -> float:
        return round(vs[min(len(vs) - 1, int(p * (len(vs) - 1)))], 5)

    return {"p10": q(0.10), "p25": q(0.25), "p50": q(0.50), "p75": q(0.75),
            "p90": q(0.90), "mean": round(statistics.fmean(vs), 5)}
