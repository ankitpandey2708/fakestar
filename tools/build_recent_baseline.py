"""Build corpus/recent_baseline.json: what a NORMAL repo's most-recent
stargazers look like.

The problem this solves. The labeled fake-vs-organic anchors describe all-time
stargazer populations. A repo's last few hundred stars are a different animal —
whoever discovered a project this week skews newer and emptier than its lifetime
average — so judging a recent sample against all-time anchors condemns healthy
repos. Measured on pallets/flask: 44% of its recent stargazers have no
followers, against an all-time norm of 36% and a lifetime figure of 23%.

Since GH Archive now misses roughly the last year of stars, the recent window is
the only view of the period where a live campaign would show up. Making it
scorable means measuring the norm through the identical pipeline: pull peer
repos' recent star events, profile those accounts, record the distribution.

Usage:  python tools/build_recent_baseline.py [--per-cell N] [--accounts N]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from _shared import bands, dedupe, percentiles, search, spread  # noqa: E402
from fakestar.baselines import infer_kind  # noqa: E402
from fakestar.detectors.accounts import measure  # noqa: E402
from fakestar.sources.github import GitHubSource, RateLimited  # noqa: E402
from fakestar.token import resolve_token  # noqa: E402

# Recent-window cohorts are only meaningful for repos still gaining stars.
MIN_RECENT_STARS = 25
# A peer whose ALL-TIME cohort already looks bought must not help define what
# normal looks like — it would raise the ceiling and make the tool forgiving.
# The published-label list is five entries long, so each candidate is screened
# on its own evidence. The screen uses the StarScout anchors, which are measured
# from labeled data and owe nothing to this peer pool, so this is a bootstrap
# rather than a circle.
SCREEN_SEVERITY = 0.35


def screen(archive, gh: GitHubSource, full: str, stars: int,
           now: datetime, accounts: int = 60) -> tuple[bool, str]:
    """Would this candidate peer itself be flagged as bought?

    Judges its ALL-TIME cohort — sampled from the archive, scored against the
    StarScout anchors — so the decision rests on labeled data rather than on the
    pool being built. Candidates the archive cannot speak to are kept: absence
    of evidence is not evidence of manipulation, and dropping them would bias
    the pool toward old repos.
    """
    from fakestar.baselines import anchored_severity, shrink
    try:
        sample = archive.star_sample(full, stars, limit=accounts)
    except Exception:
        return True, "archive unavailable"
    if len(sample.logins) < 30:
        return True, "too little history to screen"
    try:
        profiles = gh.accounts(list(sample.logins), workers=8)
    except Exception:
        return True, "profiles unavailable"
    worst, worst_name = 0.0, ""
    for m in measure(profiles, now):
        sev = anchored_severity(m.name, shrink(m.name, m.value, m.n))
        if sev is not None and sev > worst:
            worst, worst_name = sev, m.name
    if worst >= SCREEN_SEVERITY:
        return False, f"{worst_name} severity {worst:.2f}"
    return True, ""


def profile_recent(src: GitHubSource, owner: str, name: str, stars: int,
                   accounts: int, now: datetime) -> dict[str, float] | None:
    """Measure one repo's most-recent stargazers. None if too few to bother."""
    sample = src.recent_star_events(owner, name, stars)
    logins = list(sample.logins)[:accounts]
    if len(logins) < MIN_RECENT_STARS:
        return None
    profiles = src.accounts(logins, workers=8)
    return {m.name: m.value for m in measure(profiles, now)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--per-cell", type=int, default=8,
                    help="peer repos measured per kind/size cell")
    ap.add_argument("--accounts", type=int, default=60,
                    help="recent stargazers profiled per peer repo")
    ap.add_argument("--out", default=str(ROOT / "corpus" / "recent_baseline.json"))
    ap.add_argument("--no-screen", action="store_true",
                    help="skip the all-time screen on candidate peers")
    args = ap.parse_args(argv)

    token = resolve_token(None)
    if not token:
        print("ERROR: a GitHub token is required", file=sys.stderr)
        return 3
    src = GitHubSource(token=token, wait=True)
    now = datetime.now(timezone.utc)

    archive = None
    if not args.no_screen:
        from fakestar.cache import Cache
        from fakestar.sources.archive import ArchiveSource
        archive = ArchiveSource(cache=Cache())

    cells: dict[str, list[dict[str, float]]] = {}
    # floor at 2k stars: a repo with fewer has too little recent traffic to
    # yield a cohort worth measuring
    for label, low, high in bands(floor=2_000):
        print(f"\nband {label} ({low}..{high})", file=sys.stderr)
        candidates = dedupe(
            search(src, f"stars:{low}..{high}+pushed:>2026-06-01", pages=3)
            + search(src, f"stars:{low}..{high}+topic:awesome", pages=1))

        # take extra candidates: many quiet repos yield too few recent stars
        for it in spread(candidates, args.per_cell * 4):
            owner, _, name = it["full_name"].partition("/")
            try:
                facts = src.repo_facts(owner, name)
                key = f"{infer_kind(facts)}|{label}"
                if len(cells.get(key, [])) >= args.per_cell:
                    continue
                vals = profile_recent(src, owner, name, facts.stars,
                                      args.accounts, now)
                # Screen only candidates that actually qualify. Screening every
                # candidate up front costs an all-time cohort for repos that
                # then turn out to have too few recent stars to use at all.
                if vals and archive is not None:
                    ok, why = screen(archive, src, facts.full_name, facts.stars,
                                     now, accounts=30)
                    if not ok:
                        print(f"  SKIP {facts.full_name:<44} screened out: {why}",
                              file=sys.stderr)
                        continue
            except RateLimited:
                raise
            except Exception:
                continue
            if not vals:
                continue
            vals["_repo"] = facts.full_name   # recorded so the pool is auditable
            cells.setdefault(key, []).append(vals)
            print(f"  {facts.full_name:<44} {key:<16} "
                  f"zero_followers={vals.get('zero_followers_pct', 0):.0%} "
                  f"ghost={vals.get('ghost_pct', 0):.0%} "
                  f"age={vals.get('young_median_age', 0):.0f}d", file=sys.stderr)

    def signal_names(rows: list[dict]) -> set[str]:
        return {n for r in rows for n in r if not n.startswith("_")}

    summary: dict[str, dict] = {}
    for key, repos in cells.items():
        summary[key] = {"n_repos": len(repos)}
        for n in signal_names(repos):
            summary[key][n] = percentiles([r[n] for r in repos if n in r])
    for kind in ("code", "content"):
        pooled = [r for k, rs in cells.items() if k.startswith(f"{kind}|") for r in rs]
        if pooled:
            summary[f"{kind}|*"] = {"n_repos": len(pooled)}
            for n in signal_names(pooled):
                summary[f"{kind}|*"][n] = percentiles(
                    [r[n] for r in pooled if n in r])

    payload = {
        "_doc": "GENERATED by tools/build_recent_baseline.py. What the most "
                "recent stargazers of ordinary repos look like, measured "
                "through the same event-feed pipeline the tool uses. Exists so "
                "recent samples can be scored without borrowing all-time "
                "anchors, which condemn healthy repos.",
        "_caveat": "The peer pool is drawn from GitHub search and cannot be "
                   "assumed clean: a manipulated repo among the peers raises "
                   "the p90 ceiling and makes the tool more forgiving. Repos "
                   "with published manipulation labels are excluded, but that "
                   "list is short. `peers` below records exactly which repos "
                   "set these numbers so the pool can be audited and "
                   "challenged.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "accounts_per_repo": args.accounts,
        "peers": {key: [r.get("_repo", "?") for r in repos]
                  for key, repos in cells.items()},
        "cells": summary,
    }
    Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    for key in sorted(summary):
        c = summary[key]
        zf = (c.get("zero_followers_pct") or {})
        gh_ = (c.get("ghost_pct") or {})
        print(f"  {key:<18} repos={c['n_repos']:<3} "
              f"zero_followers p50={zf.get('p50', 0):.0%} p90={zf.get('p90', 0):.0%}  "
              f"ghost p50={gh_.get('p50', 0):.0%} p90={gh_.get('p90', 0):.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
