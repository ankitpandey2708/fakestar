"""End-to-end check against the held-out labeled repos (corpus/labeled_repos.json).

Labels come from published investigations, are about STAR authenticity rather
than repo quality, and are dated — GitHub strips fake stars over time, so a
once-flagged repo can legitimately look clean today. Read this as "manipulated
repos should rank above organic ones", not as an accuracy score.

Usage:  python tools/validate_repos.py [--sample N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fakestar.cache import Cache  # noqa: E402
from fakestar.collect import gather  # noqa: E402
from fakestar.sources.archive import ArchiveSource  # noqa: E402
from fakestar.sources.github import GitHubSource  # noqa: E402
from fakestar.token import resolve_token  # noqa: E402
from fakestar.verdict import assess  # noqa: E402

LABELS = ROOT / "corpus" / "labeled_repos.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=200)
    args = ap.parse_args(argv)

    token = resolve_token(None)
    if not token:
        print("ERROR: a GitHub token is required", file=sys.stderr)
        return 3
    gh = GitHubSource(token=token, wait=True)
    archive = ArchiveSource(cache=Cache())

    data = json.loads(LABELS.read_text(encoding="utf-8"))
    rows = ([(r["repo"], "manipulated") for r in data["manipulated"]] +
            [(r["repo"], "organic") for r in data["organic"]])

    results = []
    print(f"{'repo':<38}{'label':<13}{'verdict':<24}{'risk':>5}{'cover':>7}{'conf':>8}")
    print("-" * 95)
    for repo, label in rows:
        owner, _, name = repo.partition("/")
        try:
            ev = gather(gh, archive, owner, name, sample_size=args.sample)
            v = assess(ev.facts, ev.sample, ev.measurements, len(ev.accounts),
                       context=ev.context, notes=ev.notes)
            score = "-" if v.score is None else v.score
            print(f"{repo:<38}{label:<13}{v.band:<24}{score:>5}"
                  f"{ev.sample.coverage.fraction:>6.0%}{v.confidence:>8}")
            results.append((label, v.band, v.score))
        except Exception as exc:
            print(f"{repo:<38}{label:<13}ERROR: {exc}")

    man = [s for lbl, _, s in results if lbl == "manipulated" and s is not None]
    org = [s for lbl, _, s in results if lbl == "organic" and s is not None]
    flagged = sum(1 for lbl, b, _ in results if lbl == "manipulated"
                  and b in ("SUSPICIOUS", "LIKELY MANIPULATED"))
    clean = sum(1 for lbl, b, _ in results
                if lbl == "organic" and b == "LIKELY ORGANIC")
    print("\n--- summary ---")
    if man and org:
        print(f"median risk:  manipulated={sorted(man)[len(man) // 2]}  "
              f"organic={sorted(org)[len(org) // 2]}")
    print(f"manipulated flagged:            {flagged}/"
          f"{sum(1 for lbl, _, _ in results if lbl == 'manipulated')}")
    print(f"organic returned LIKELY ORGANIC: {clean}/"
          f"{sum(1 for lbl, _, _ in results if lbl == 'organic')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
