"""Cheap-to-fake against expensive-to-fake.

Anyone can buy a star. A fork means someone wanted the code badly enough to take
a copy; a watch means they want to be told when it changes. When stars run far
ahead of both, the stars are the odd one out.

These are exact counts, never sampled, so they are the one line of evidence that
survives GitHub withholding stargazer identities. The judgement is always made
against repos of the same KIND and size — a curated list legitimately forks and
watches differently from a framework.
"""
from __future__ import annotations

from ..evidence import RepoFacts
from ..models import Measurement

# Below this, ratios are too noisy to mean much: a 300-star weekend project with
# 4 forks is unremarkable, and dividing small numbers amplifies nothing useful.
MIN_STARS = 2_000


def measure(facts: RepoFacts) -> list[Measurement]:
    if facts.stars < MIN_STARS:
        return []
    return [
        Measurement("fork_to_star", facts.fork_ratio, facts.stars,
                    f"{facts.forks:,} forks / {facts.stars:,} stars "
                    f"= {1000 * facts.fork_ratio:.0f} per 1k"),
        Measurement("watcher_to_star", facts.watcher_ratio, facts.stars,
                    f"{facts.watchers:,} watchers / {facts.stars:,} stars "
                    f"= {1000 * facts.watcher_ratio:.0f} per 1k"),
    ]
