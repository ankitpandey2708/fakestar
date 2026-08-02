"""Resolving a GitHub token, in its own module so tools don't import the CLI."""
from __future__ import annotations

import os
import shutil
import subprocess


def gh_cli_token() -> str | None:
    """Token from an authenticated `gh`, or None if gh is absent or logged out."""
    if not shutil.which("gh"):
        return None
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def resolve_token(token_arg: str | None = None, gh_token=None) -> str | None:
    """--token, then $GITHUB_TOKEN / $GH_TOKEN, then the gh CLI."""
    if token_arg:
        return token_arg
    env = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if env:
        return env
    return (gh_token or gh_cli_token)()
