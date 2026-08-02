"""fakestar-check — is this repo's star count trustworthy evidence of interest?"""
from __future__ import annotations

import argparse
import sys

from .baselines import INSUFFICIENT
from .cache import Cache
from .collect import gather
from .report import render_json, render_text
from .sources.archive import ArchiveSource
from .sources.github import GitHubSource, RateLimited, RepoNotFound
from .token import resolve_token
from .verdict import assess

EXIT = {
    "LIKELY ORGANIC": 0,
    "SUSPICIOUS": 1,
    "LIKELY MANIPULATED": 2,
    INSUFFICIENT: 4,
}
ERROR = 3


def _positive_int(v: str) -> int:
    n = int(v)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="fakestar-check",
        description="Judge whether a GitHub repo's stars are genuine.")
    p.add_argument("repo", help="target repository as owner/repo")
    p.add_argument("--token", help="GitHub token (else $GITHUB_TOKEN, or gh CLI)")
    p.add_argument("--sample", type=_positive_int, default=300,
                   help="stargazer accounts to examine (default 300)")
    p.add_argument("--workers", type=_positive_int, default=8,
                   help="parallel account lookups (default 8)")
    p.add_argument("--also-known-as", action="append", default=[],
                   metavar="OWNER/REPO",
                   help="former name of this repo, if auto-detection misses "
                        "it (repeatable). Renames are normally found and "
                        "confirmed automatically")
    p.add_argument("--archive-url", default=None,
                   help="star-archive SQL endpoint (else $FAKESTAR_ARCHIVE_URL)")
    p.add_argument("--no-archive", action="store_true",
                   help="skip the public star archive; GitHub API only")
    p.add_argument("--refresh", action="store_true",
                   help="ignore cached archive answers and re-query")
    p.add_argument("--wait", action="store_true",
                   help="sleep through GitHub rate-limit windows")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="emit JSON")
    return p.parse_args(argv)


def _progress(msg: str) -> None:
    # stderr, and only for a human at a terminal: keeps --json and pipes clean
    if sys.stderr.isatty():
        print(f"... {msg}", file=sys.stderr, flush=True)


def run(args: argparse.Namespace, gh, archive) -> object:
    owner, _, repo = args.repo.partition("/")
    progress = (lambda _m: None) if args.json else _progress

    try:
        evidence = gather(gh, archive, owner, repo, sample_size=args.sample,
                          workers=args.workers, progress=progress,
                          also_known_as=tuple(args.also_known_as))
    except RepoNotFound:
        from .evidence import Provenance
        from .models import Verdict
        return Verdict(
            repo=args.repo, band="LIKELY MANIPULATED", score=100,
            confidence="high", coverage="repository no longer exists",
            provenance=Provenance.NONE.value,
            notes=["GitHub returns 404 for this repository. Repos removed by "
                   "GitHub are the usual end state of a star campaign - the "
                   "CMU study found ~90% of flagged repos later deleted."])

    return assess(evidence.facts, evidence.sample, evidence.measurements,
                  accounts_sampled=len(evidence.accounts),
                  context=evidence.context, notes=evidence.notes,
                  recent_measurements=evidence.recent_measurements,
                  recent_accounts=len(evidence.recent_accounts or []))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if "/" not in args.repo.strip("/"):
        print(f"ERROR: expected owner/repo, got {args.repo!r}", file=sys.stderr)
        return ERROR

    token = resolve_token(args.token)
    if not token:
        print("ERROR: a GitHub token is required. Pass --token, set "
              "$GITHUB_TOKEN, or run `gh auth login`.", file=sys.stderr)
        return ERROR

    gh = GitHubSource(token=token, wait=args.wait)
    archive = None
    if not args.no_archive:
        archive = ArchiveSource(endpoint=args.archive_url,
                                cache=Cache(enabled=not args.refresh))

    try:
        verdict = run(args, gh, archive)
    except RateLimited as e:
        print(f"ERROR: GitHub rate limit hit (resets at epoch {e.reset_ts}). "
              f"Retry later or pass --wait.", file=sys.stderr)
        return ERROR

    print(render_json(verdict) if args.json
          else render_text(verdict, color=sys.stdout.isatty()))
    return EXIT.get(verdict.band, ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
