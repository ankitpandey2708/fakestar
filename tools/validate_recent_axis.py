"""Test whether the recent-window axis can actually catch anything.

The axis rests on an unproven assumption. Its "normal" line is measured — the
p90 of peer repos' recent stargazers — but its far end is inferred, by carrying
the fake-to-organic ratio from all-time cohorts onto that line. The reasoning is
that the base rate for recent stargazers differs while the separation produced
by buying does not. Plausible; unverified.

This checks it against the only labeled fakes available: if their recent
stargazers do not exceed a ceiling that ordinary repos stay under, the axis is
decoration and should be removed rather than shipped.

Usage:  python tools/validate_recent_axis.py [--accounts 100]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fakestar.baselines import RECENT_SIGNALS, infer_kind, recent_reference  # noqa: E402
from fakestar.detectors.accounts import measure  # noqa: E402
from fakestar.sources.github import GitHubSource  # noqa: E402
from fakestar.token import resolve_token  # noqa: E402

LABELS = ROOT / "corpus" / "labeled_repos.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--accounts", type=int, default=100)
    args = ap.parse_args(argv)

    token = resolve_token(None)
    if not token:
        print("ERROR: a GitHub token is required", file=sys.stderr)
        return 3
    gh = GitHubSource(token=token, wait=True)
    now = datetime.now(timezone.utc)

    data = json.loads(LABELS.read_text(encoding="utf-8"))
    rows = ([(r["repo"], "manipulated") for r in data["manipulated"]] +
            [(r["repo"], "organic") for r in data["organic"]])

    print(f"{'repo':<38}{'label':<13}{'kind':<9}{'n':>4}"
          f"{'zero_foll':>11}{'ceiling':>9}{'sev':>6}")
    print("-" * 90)
    results = []
    for repo, label in rows:
        owner, _, name = repo.partition("/")
        try:
            facts = gh.repo_facts(owner, name)
            sample = gh.recent_star_events(owner, name, facts.stars)
            logins = list(sample.logins)[:args.accounts]
            if len(logins) < 20:
                print(f"{repo:<38}{label:<13}{'-':<9}{len(logins):>4}"
                      f"  too few recent stars to judge")
                continue
            accounts = gh.accounts(logins, workers=8)
            vals = {m.name: m.value for m in measure(accounts, now)}
        except Exception as exc:
            print(f"{repo:<38}{label:<13}ERROR: {exc}")
            continue

        kind = infer_kind(facts)
        worst = 0.0
        for signal in RECENT_SIGNALS:
            if signal not in vals:
                continue
            ref = recent_reference(kind, facts.stars, signal)
            if ref is None:
                continue
            ceiling, far, _ = ref
            sev = 0.0 if vals[signal] <= ceiling else min(
                1.0, (vals[signal] - ceiling) / (far - ceiling))
            worst = max(worst, sev)

        zf = vals.get("zero_followers_pct", 0)
        ref = recent_reference(kind, facts.stars, "zero_followers_pct")
        ceiling = ref[0] if ref else float("nan")
        print(f"{repo:<38}{label:<13}{kind:<9}{len(accounts):>4}"
              f"{zf:>10.0%}{ceiling:>9.0%}{worst:>6.2f}")
        results.append((label, worst))

    man = [s for lbl, s in results if lbl == "manipulated"]
    org = [s for lbl, s in results if lbl == "organic"]
    print("\n--- summary (severity on the recent axis) ---")
    if man:
        print(f"manipulated: max={max(man):.2f} median={sorted(man)[len(man)//2]:.2f} "
              f"exceeding ceiling={sum(1 for s in man if s > 0)}/{len(man)}")
    if org:
        print(f"organic:     max={max(org):.2f} median={sorted(org)[len(org)//2]:.2f} "
              f"exceeding ceiling={sum(1 for s in org if s > 0)}/{len(org)}")
    if man and org:
        verdict = ("USEFUL - fakes exceed the ceiling and organics do not"
                   if max(org) < 0.25 <= max(man)
                   else "NOT DEMONSTRATED - the axis does not separate these labels")
        print(f"\n{verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
