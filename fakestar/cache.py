"""A tiny on-disk memo.

The archive lives on someone else's free public server. Asking it the same
question twice is both slow and rude, so answers are kept locally and reused.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL = 7 * 24 * 3600  # a week: star history barely moves


def cache_dir() -> Path:
    env = os.environ.get("FAKESTAR_CACHE")
    if env:
        return Path(env)
    base = (os.environ.get("XDG_CACHE_HOME")
            or os.environ.get("LOCALAPPDATA")
            or str(Path.home() / ".cache"))
    return Path(base) / "fakestar"


class Cache:
    def __init__(self, directory: Path | None = None, ttl: float = DEFAULT_TTL,
                 enabled: bool = True):
        self._dir = directory or cache_dir()
        self._ttl = ttl
        self._enabled = enabled

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
        return self._dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        if not self._enabled:
            return None
        path = self._path(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if time.time() - raw.get("_at", 0) > self._ttl:
            return None
        return raw.get("value")

    def put(self, key: str, value: Any) -> None:
        if not self._enabled:
            return
        path = self._path(key)
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            # atomic: a half-written cache file must never be read back
            fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"_at": time.time(), "value": value}, fh)
            os.replace(tmp, path)
        except OSError:
            pass  # a cache that can't write is a slow tool, not a broken one

