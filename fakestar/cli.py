from __future__ import annotations

import argparse
import os
import sys

from .detectors.engagement import analyze_engagement
from .detectors.profiles import analyze_profiles, auto_sample
from .detectors.ratios import analyze_ratios
from .detectors.temporal import analyze_temporal
from .github import GitHubClient, RateLimited, RepoNotFound
from .models import Signal, Verdict
from .report import render_json, render_text
from .scoring import score_signals

_EXIT = {"LIKELY ORGANIC": 0, "SUSPICIOUS": 1, "LIKELY MANIPULATED": 2}


def _sample_arg(v: str):
    if v == "auto":
        return "auto"
    try:
        n = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError("--sample must be an integer or 'auto'")
    if n < 1:
        raise argparse.ArgumentTypeError("--sample must be >= 1 or 'auto'")
    return n


def _positive_float(v: str) -> float:
    f = float(v)
    if f <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return f


def _positive_int(v: str) -> int:
    n = int(v)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def _progress(msg: str) -> None:
    # Status to stderr, only on an interactive terminal — keeps --json/stdout
    # clean and test output pristine (pytest's stderr isn't a tty).
    if sys.stderr.isatty():
        print(f"... {msg}", file=sys.stderr, flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="fakestar-check",
        description="Score a GitHub repo for inauthentic-star evidence.")
    p.add_argument("repo", help="target repository as owner/repo")
    p.add_argument("--token", help="GitHub token (else $GITHUB_TOKEN)")
    p.add_argument("--sample", type=_sample_arg, default="auto",
                   help="stargazer profiles to sample: an integer, or 'auto' "
                        "(default) to size from the repo's star count")
    p.add_argument("--margin", type=_positive_float, default=0.08,
                   help="target margin of error for --sample auto (default 0.08)")
    p.add_argument("--max-sample", type=_positive_int, default=150,
                   help="cap for --sample auto (default 150)")
    p.add_argument("--timeline-pages", type=int, default=40,
                   help="star-timeline pages to fetch (default 40)")
    p.add_argument("--ratios-only", action="store_true",
                   help="skip profile and temporal detectors")
    p.add_argument("--workers", type=int, default=8,
                   help="parallel workers for stargazer profile fetching (default 8)")
    # Output format is one choice: plain (default), --verbose, or --json.
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="emit JSON")
    out.add_argument("--verbose", action="store_true",
                     help="show the raw value/baseline/threshold table")
    p.add_argument("--wait", action="store_true",
                   help="sleep through rate-limit windows")
    return p.parse_args(argv)


def run(args: argparse.Namespace, client) -> Verdict:
    owner, _, repo = args.repo.partition("/")
    notes: list[str] = []

    _progress(f"Fetching {args.repo} metadata...")
    try:
        repo_data = client.get_repo(owner, repo)
    except RepoNotFound:
        notes.append("Repository not found (404) - likely deleted by GitHub, "
                     "itself a strong manipulation signal.")
        sig = Signal("repo_deleted", 1.0, 0.0, 0.0, 100, True, 1.0,
                     "repo returns 404")
        return score_signals([sig], repo=args.repo, sample_size=0, notes=notes)

    signals: list[Signal] = list(analyze_ratios(repo_data))
    sampled = 0

    if not args.ratios_only:
        stars = repo_data.get("stargazers_count", 0) or 0
        sample = (auto_sample(stars, margin=args.margin, max_sample=args.max_sample)
                  if args.sample == "auto" else args.sample)
        try:
            _progress(f"Sampling up to {sample} stargazer profiles "
                      f"({args.workers} workers)...")
            profile_signals, sampled = analyze_profiles(
                client, owner, repo,
                total_stars=stars, sample=sample, workers=args.workers)
            signals += profile_signals
        except Exception as e:  # tolerate detector failure
            notes.append(f"Profile sampling skipped: {e}")
        try:
            _progress("Analyzing star timeline...")
            signals += analyze_temporal(client, owner, repo,
                                        max_pages=args.timeline_pages)
        except Exception as e:
            notes.append(f"Temporal analysis skipped: {e}")
        try:
            _progress("Checking contributors & engagement...")
            signals += analyze_engagement(client, owner, repo, repo_data)
        except Exception as e:
            notes.append(f"Engagement analysis skipped: {e}")
    _progress("Scoring...")

    return score_signals(signals, repo=args.repo, sample_size=sampled,
                         notes=notes)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        args.ratios_only = True
        print("WARNING: no token ($GITHUB_TOKEN); running ratios-only "
              "(unauthenticated rate limits forbid profile sampling).",
              file=sys.stderr)

    client = GitHubClient(token=token, wait=args.wait)
    try:
        verdict = run(args, client)
    except RateLimited as e:
        print(f"ERROR: GitHub rate limit hit (resets at epoch {e.reset_ts}). "
              f"Retry later or pass --wait.", file=sys.stderr)
        return 3

    if args.json:
        print(render_json(verdict))
    else:
        print(render_text(verdict, color=sys.stdout.isatty(), detailed=args.verbose))
    return _EXIT.get(verdict.band, 3)


if __name__ == "__main__":
    raise SystemExit(main())
