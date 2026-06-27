"""End-to-end validation: run fakestar on the held-out labeled repos
(corpus/labeled_repos.json) and report how it classifies each vs its published
label. Labels are about STAR authenticity and are probabilistic/dated — this is
a sanity check ("manipulated repos should rank higher than organic"), not a
pass/fail accuracy number. Needs a GitHub token (gh)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fakestar.cli import parse_args, resolve_token, run
from fakestar.github import GitHubClient

LABELS = ROOT / "corpus" / "labeled_repos.json"
MAX_SAMPLE = "200"   # deeper than default 150 so a fake cluster is visible on big repos


def main():
    data = json.loads(LABELS.read_text(encoding="utf-8"))
    client = GitHubClient(token=resolve_token(None), wait=True)
    rows = ([(r["repo"], "manipulated") for r in data["manipulated"]] +
            [(r["repo"], "organic") for r in data["organic"]])

    results = []
    print(f"{'repo':40s} {'label':12s} {'verdict':16s} {'risk':>5} {'star/use':>9}")
    for repo, label in rows:
        try:
            v = run(parse_args([repo, "--sample", "auto", "--max-sample", MAX_SAMPLE, "--wait"]), client)
            sg = "-" if v.stargazer_score is None else v.stargazer_score
            us = "-" if v.usage_score is None else v.usage_score
            print(f"{repo:40s} {label:12s} {v.band:16s} {v.score:>5} {str(sg)+'/'+str(us):>9}")
            results.append((label, v.band, v.score))
        except Exception as e:
            print(f"{repo:40s} {label:12s} ERROR: {e}")

    # summary: did manipulated rank above organic?
    man = [s for lbl, _, s in results if lbl == "manipulated"]
    org = [s for lbl, _, s in results if lbl == "organic"]
    flagged = sum(1 for lbl, b, _ in results
                  if lbl == "manipulated" and b in ("SUSPICIOUS", "LIKELY MANIPULATED"))
    clean = sum(1 for lbl, b, _ in results
                if lbl == "organic" and b == "LIKELY ORGANIC")
    print("\n--- summary ---")
    if man and org:
        print(f"median risk:  manipulated={sorted(man)[len(man)//2]}  organic={sorted(org)[len(org)//2]}")
    print(f"manipulated flagged (SUSPICIOUS/MANIPULATED): {flagged}/{len(man)}")
    print(f"organic stayed LIKELY ORGANIC:                {clean}/{len(org)}")


if __name__ == "__main__":
    main()
