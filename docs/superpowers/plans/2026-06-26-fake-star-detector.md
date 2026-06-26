# Fake-Star Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python CLI (`fakestar-check <owner/repo>`) that scores a GitHub repo 0–100 for inauthentic-star evidence using engagement ratios, stargazer-profile sampling, and star-timeline burst analysis.

**Architecture:** A thin GitHub API client feeds three independent detectors (`ratios`, `profiles`, `temporal`), each returning normalized `Signal` objects. A weighted scoring engine aggregates signals into a `Verdict`, which a renderer emits as a text report or JSON. Detectors never import scoring or rendering; the client is the only shared dependency.

**Tech Stack:** Python 3.11+, `requests` for HTTP, `pytest` for tests. No ML / heavy deps.

## Global Constraints

- Python **3.11+** (uses `X | None` unions, `dataclasses`).
- Only third-party runtime dependency: **`requests`**. Dev dependency: **`pytest`**.
- No live network calls in unit tests — clients are injected/faked.
- TDD: every behavior gets a failing test first. Commit after each task.
- Package name `fakestar`; CLI entry point `fakestar-check` → `fakestar.cli:main`.
- All detectors are pure of side effects beyond the injected client; each returns `list[Signal]`.
- Each `Signal` carries `severity` (0.0–1.0); scoring multiplies `weight * severity`. Detectors own severity computation; scoring stays dumb.

---

## File Structure

```
fakestar/                     # repo root (already git-init'd)
  pyproject.toml              # Task 1
  fakestar/
    __init__.py               # Task 1
    models.py                 # Task 1  — Signal, Verdict, dataclasses
    baselines.py              # Task 2  — thresholds, weights, bands
    scoring.py                # Task 3  — score_signals() -> Verdict
    github.py                 # Task 4  — GitHubClient + exceptions
    detectors/
      __init__.py             # Task 5
      ratios.py               # Task 5
      profiles.py             # Task 6
      temporal.py             # Task 7
    report.py                 # Task 8  — render_text(), render_json()
    cli.py                    # Task 9  — main(), arg parsing, orchestration
  tests/
    __init__.py
    fixtures/                 # Task 4+ — recorded API JSON
    test_models.py            # Task 1
    test_scoring.py           # Task 3
    test_github.py            # Task 4
    test_ratios.py            # Task 5
    test_profiles.py          # Task 6
    test_temporal.py          # Task 7
    test_report.py            # Task 8
    test_cli.py               # Task 9
```

---

### Task 1: Project scaffolding + data models

**Files:**
- Create: `pyproject.toml`, `fakestar/__init__.py`, `fakestar/models.py`, `tests/__init__.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Signal(name: str, value: float, baseline: float, threshold: float, weight: int, tripped: bool, severity: float, detail: str, caveat: str | None = None)` — frozen dataclass.
  - `Verdict(score: int, band: str, signals: list[Signal], sample_size: int, repo: str, notes: list[str])` — dataclass.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "fakestar"
version = "0.1.0"
description = "Score a GitHub repo for inauthentic-star evidence"
requires-python = ">=3.11"
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
fakestar-check = "fakestar.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create empty `fakestar/__init__.py` and `tests/__init__.py`**

```python
# fakestar/__init__.py
__version__ = "0.1.0"
```
```python
# tests/__init__.py
```

- [ ] **Step 3: Write the failing test** in `tests/test_models.py`

```python
from fakestar.models import Signal, Verdict


def test_signal_defaults_caveat_none():
    s = Signal(
        name="fork_to_star", value=0.02, baseline=0.16, threshold=0.05,
        weight=30, tripped=True, severity=0.6, detail="low forks",
    )
    assert s.caveat is None
    assert s.tripped is True


def test_verdict_holds_signals():
    s = Signal("ghost_pct", 0.3, 0.01, 0.10, 25, True, 1.0, "many ghosts")
    v = Verdict(score=70, band="LIKELY MANIPULATED", signals=[s],
                sample_size=150, repo="o/r", notes=["temporal skipped"])
    assert v.signals[0].name == "ghost_pct"
    assert v.notes == ["temporal skipped"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.models'`

- [ ] **Step 5: Write `fakestar/models.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Signal:
    name: str
    value: float
    baseline: float
    threshold: float
    weight: int
    tripped: bool
    severity: float  # 0.0-1.0
    detail: str
    caveat: str | None = None


@dataclass
class Verdict:
    score: int
    band: str
    signals: list[Signal]
    sample_size: int
    repo: str
    notes: list[str] = field(default_factory=list)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml fakestar/__init__.py fakestar/models.py tests/__init__.py tests/test_models.py
git commit -m "feat: project scaffolding and data models"
```

---

### Task 2: Baseline constants

**Files:**
- Create: `fakestar/baselines.py`, `tests/test_baselines.py`

**Interfaces:**
- Consumes: nothing.
- Produces module-level constants:
  - `WEIGHTS: dict[str, int]` — keys `fork_to_star`, `ghost_pct`, `suspicious_pct`, `watcher_to_star`, `temporal_burst`.
  - `THRESHOLDS: dict[str, float]`, `BASELINES: dict[str, float]`.
  - `MIN_STARS_FOR_RATIO: int = 10_000`.
  - `BANDS: list[tuple[int, str]]` — (upper_inclusive, label) sorted ascending.
  - `band_for(score: int) -> str`.

- [ ] **Step 1: Write the failing test** in `tests/test_baselines.py`

```python
from fakestar.baselines import WEIGHTS, band_for


def test_weights_sum_to_100():
    assert sum(WEIGHTS.values()) == 100


def test_band_boundaries():
    assert band_for(0) == "LIKELY ORGANIC"
    assert band_for(25) == "LIKELY ORGANIC"
    assert band_for(26) == "SUSPICIOUS"
    assert band_for(60) == "SUSPICIOUS"
    assert band_for(61) == "LIKELY MANIPULATED"
    assert band_for(100) == "LIKELY MANIPULATED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_baselines.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.baselines'`

- [ ] **Step 3: Write `fakestar/baselines.py`**

```python
from __future__ import annotations

WEIGHTS: dict[str, int] = {
    "fork_to_star": 30,
    "ghost_pct": 25,
    "suspicious_pct": 20,
    "watcher_to_star": 15,
    "temporal_burst": 10,
}

THRESHOLDS: dict[str, float] = {
    "fork_to_star": 0.05,
    "ghost_pct": 0.10,
    "suspicious_pct": 0.15,
    "watcher_to_star": 0.002,
    "temporal_burst": 0.30,
}

BASELINES: dict[str, float] = {
    "fork_to_star": 0.16,
    "ghost_pct": 0.01,
    "suspicious_pct": 0.00,
    "watcher_to_star": 0.015,
    "temporal_burst": 0.05,
}

MIN_STARS_FOR_RATIO: int = 10_000

# (upper_inclusive_score, label), ascending
BANDS: list[tuple[int, str]] = [
    (25, "LIKELY ORGANIC"),
    (60, "SUSPICIOUS"),
    (100, "LIKELY MANIPULATED"),
]


def band_for(score: int) -> str:
    for upper, label in BANDS:
        if score <= upper:
            return label
    return BANDS[-1][1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_baselines.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/baselines.py tests/test_baselines.py
git commit -m "feat: baseline thresholds, weights, and verdict bands"
```

---

### Task 3: Scoring engine

**Files:**
- Create: `fakestar/scoring.py`, `tests/test_scoring.py`

**Interfaces:**
- Consumes: `Signal`, `Verdict` (Task 1); `band_for` (Task 2).
- Produces: `score_signals(signals: list[Signal], repo: str, sample_size: int, notes: list[str] | None = None) -> Verdict`. Score = `round(sum(weight * severity))` clamped to 0–100; band via `band_for`.

- [ ] **Step 1: Write the failing test** in `tests/test_scoring.py`

```python
from fakestar.models import Signal
from fakestar.scoring import score_signals


def _sig(name, weight, severity, tripped=True):
    return Signal(name, 0.0, 0.0, 0.0, weight, tripped, severity, "d")


def test_no_signals_scores_zero_and_organic():
    v = score_signals([], repo="o/r", sample_size=0)
    assert v.score == 0
    assert v.band == "LIKELY ORGANIC"


def test_full_severity_all_signals_caps_at_100():
    sigs = [_sig("a", 30, 1.0), _sig("b", 25, 1.0), _sig("c", 20, 1.0),
            _sig("d", 15, 1.0), _sig("e", 10, 1.0)]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.score == 100
    assert v.band == "LIKELY MANIPULATED"


def test_partial_severity_sums_proportionally():
    # 30*0.5 + 25*0.4 = 15 + 10 = 25 -> ORGANIC boundary
    sigs = [_sig("a", 30, 0.5), _sig("b", 25, 0.4)]
    v = score_signals(sigs, repo="o/r", sample_size=150)
    assert v.score == 25
    assert v.band == "LIKELY ORGANIC"


def test_notes_passed_through():
    v = score_signals([], repo="o/r", sample_size=0, notes=["x"])
    assert v.notes == ["x"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.scoring'`

- [ ] **Step 3: Write `fakestar/scoring.py`**

```python
from __future__ import annotations

from .baselines import band_for
from .models import Signal, Verdict


def score_signals(
    signals: list[Signal],
    repo: str,
    sample_size: int,
    notes: list[str] | None = None,
) -> Verdict:
    raw = sum(s.weight * s.severity for s in signals)
    score = max(0, min(100, round(raw)))
    return Verdict(
        score=score,
        band=band_for(score),
        signals=signals,
        sample_size=sample_size,
        repo=repo,
        notes=notes or [],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_scoring.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/scoring.py tests/test_scoring.py
git commit -m "feat: weighted signal scoring engine"
```

---

### Task 4: GitHub API client

**Files:**
- Create: `fakestar/github.py`, `tests/test_github.py`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces:
  - Exceptions `RepoNotFound(Exception)`, `RateLimited(Exception)` (attr `reset_ts: int`).
  - `GitHubClient(token: str | None = None, session=None, sleeper=time.sleep)`.
  - `get_repo(owner: str, repo: str) -> dict` — raises `RepoNotFound` on 404.
  - `get_user(login: str) -> dict`.
  - `iter_stargazers(owner, repo, with_timestamps=False, max_pages=None) -> Iterator[dict]` — yields user dicts, or `{"starred_at": ..., "user": {...}}` when `with_timestamps=True`. Follows `Link` `rel="next"`.

Notes for implementer: a `session` is any object with `.get(url, headers=...)` returning a response exposing `.status_code`, `.json()`, `.headers` (a dict), and `.links` (dict of `{rel: {"url": ...}}`, matching `requests.Response.links`). Tests inject a fake session; production passes `requests.Session()`.

- [ ] **Step 1: Write the failing test** in `tests/test_github.py`

```python
import pytest

from fakestar.github import GitHubClient, RepoNotFound, RateLimited


class FakeResp:
    def __init__(self, status, body=None, headers=None, links=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.links = links or {}

    def json(self):
        return self._body


class FakeSession:
    """Returns queued responses in order; records requested URLs."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.urls = []

    def get(self, url, headers=None):
        self.urls.append(url)
        return self._responses.pop(0)


def test_get_repo_returns_json():
    sess = FakeSession([FakeResp(200, {"stargazers_count": 100})])
    c = GitHubClient(token="t", session=sess)
    assert c.get_repo("o", "r")["stargazers_count"] == 100


def test_get_repo_404_raises():
    sess = FakeSession([FakeResp(404, {"message": "Not Found"})])
    c = GitHubClient(token="t", session=sess)
    with pytest.raises(RepoNotFound):
        c.get_repo("o", "r")


def test_rate_limit_raises_with_reset():
    sess = FakeSession([FakeResp(403, {}, headers={
        "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})])
    c = GitHubClient(token="t", session=sess)
    with pytest.raises(RateLimited) as ei:
        c.get_repo("o", "r")
    assert ei.value.reset_ts == 1700000000


def test_iter_stargazers_follows_pagination():
    page1 = FakeResp(200, [{"login": "a"}, {"login": "b"}],
                     links={"next": {"url": "https://api/page2"}})
    page2 = FakeResp(200, [{"login": "c"}])
    sess = FakeSession([page1, page2])
    c = GitHubClient(token="t", session=sess)
    logins = [u["login"] for u in c.iter_stargazers("o", "r")]
    assert logins == ["a", "b", "c"]


def test_iter_stargazers_respects_max_pages():
    page1 = FakeResp(200, [{"login": "a"}],
                     links={"next": {"url": "https://api/page2"}})
    page2 = FakeResp(200, [{"login": "b"}])
    sess = FakeSession([page1, page2])
    c = GitHubClient(token="t", session=sess)
    logins = [u["login"] for u in c.iter_stargazers("o", "r", max_pages=1)]
    assert logins == ["a"]


def test_5xx_retries_then_succeeds():
    sess = FakeSession([FakeResp(502, {}), FakeResp(200, {"ok": True})])
    c = GitHubClient(token="t", session=sess, sleeper=lambda _s: None)
    assert c.get_repo("o", "r") == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_github.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.github'`

- [ ] **Step 3: Write `fakestar/github.py`**

```python
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

API = "https://api.github.com"


class RepoNotFound(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, reset_ts: int):
        super().__init__(f"GitHub rate limit hit; resets at {reset_ts}")
        self.reset_ts = reset_ts


class GitHubClient:
    def __init__(self, token: str | None = None, session=None, sleeper=time.sleep):
        if session is None:
            import requests
            session = requests.Session()
        self._session = session
        self._token = token
        self._sleep = sleeper

    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _request(self, url: str, accept: str = "application/vnd.github+json"):
        for attempt in range(3):
            resp = self._session.get(url, headers=self._headers(accept))
            status = resp.status_code
            if status == 404:
                raise RepoNotFound(url)
            if status in (403, 429) and resp.headers.get("X-RateLimit-Remaining") == "0":
                raise RateLimited(int(resp.headers.get("X-RateLimit-Reset", "0")))
            if 500 <= status < 600 and attempt < 2:
                self._sleep(2 ** attempt)
                continue
            return resp
        return resp

    def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        return self._request(f"{API}/repos/{owner}/{repo}").json()

    def get_user(self, login: str) -> dict[str, Any]:
        return self._request(f"{API}/users/{login}").json()

    def iter_stargazers(
        self, owner: str, repo: str,
        with_timestamps: bool = False, max_pages: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        accept = ("application/vnd.github.star+json" if with_timestamps
                  else "application/vnd.github+json")
        url = f"{API}/repos/{owner}/{repo}/stargazers?per_page=100"
        pages = 0
        while url:
            resp = self._request(url, accept)
            for item in resp.json():
                yield item
            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            nxt = resp.links.get("next")
            url = nxt["url"] if nxt else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_github.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/github.py tests/test_github.py
git commit -m "feat: GitHub API client with pagination, rate-limit and retry"
```

---

### Task 5: Ratios detector

**Files:**
- Create: `fakestar/detectors/__init__.py`, `fakestar/detectors/ratios.py`, `tests/test_ratios.py`

**Interfaces:**
- Consumes: `Signal` (Task 1); `WEIGHTS`, `THRESHOLDS`, `BASELINES`, `MIN_STARS_FOR_RATIO` (Task 2).
- Produces: `analyze_ratios(repo: dict) -> list[Signal]`. `repo` is the dict from `GitHubClient.get_repo` (keys `stargazers_count`, `forks_count`, `subscribers_count`). Returns two signals: `fork_to_star`, `watcher_to_star`. Both carry the curated-list caveat. `fork_to_star` only trips when stars > `MIN_STARS_FOR_RATIO`. Severity for a "lower is worse" ratio = `clamp((threshold - value) / threshold, 0, 1)`.

- [ ] **Step 1: Write the failing test** in `tests/test_ratios.py`

```python
from fakestar.detectors.ratios import analyze_ratios


def _repo(stars, forks, watchers):
    return {"stargazers_count": stars, "forks_count": forks,
            "subscribers_count": watchers}


def test_organic_repo_does_not_trip():
    sigs = {s.name: s for s in analyze_ratios(_repo(70000, 16450, 2030))}
    assert sigs["fork_to_star"].tripped is False
    assert sigs["watcher_to_star"].tripped is False


def test_manipulated_repo_trips_both():
    sigs = {s.name: s for s in analyze_ratios(_repo(157000, 2676, 168))}
    assert sigs["fork_to_star"].tripped is True
    assert sigs["watcher_to_star"].tripped is True
    assert 0.0 < sigs["fork_to_star"].severity <= 1.0


def test_fork_ratio_ignored_below_min_stars():
    # very low fork ratio but only 500 stars -> not enough to trip
    sigs = {s.name: s for s in analyze_ratios(_repo(500, 1, 1))}
    assert sigs["fork_to_star"].tripped is False


def test_zero_stars_is_safe():
    sigs = {s.name: s for s in analyze_ratios(_repo(0, 0, 0))}
    assert sigs["fork_to_star"].tripped is False
    assert sigs["fork_to_star"].value == 0.0


def test_caveat_present():
    sigs = analyze_ratios(_repo(70000, 16450, 2030))
    assert all(s.caveat for s in sigs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ratios.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.detectors'`

- [ ] **Step 3: Write `fakestar/detectors/__init__.py` (empty) and `fakestar/detectors/ratios.py`**

```python
# fakestar/detectors/__init__.py
```

```python
# fakestar/detectors/ratios.py
from __future__ import annotations

from ..baselines import BASELINES, MIN_STARS_FOR_RATIO, THRESHOLDS, WEIGHTS
from ..models import Signal

_CAVEAT = "Low forks/watchers can be normal for curated lists, docs, or tutorials."


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def analyze_ratios(repo: dict) -> list[Signal]:
    stars = repo.get("stargazers_count", 0) or 0
    forks = repo.get("forks_count", 0) or 0
    watchers = repo.get("subscribers_count", 0) or 0

    fs = forks / stars if stars else 0.0
    ws = watchers / stars if stars else 0.0

    fs_thr = THRESHOLDS["fork_to_star"]
    fs_tripped = fs < fs_thr and stars > MIN_STARS_FOR_RATIO
    fs_sev = _clamp((fs_thr - fs) / fs_thr) if fs_tripped else 0.0

    ws_thr = THRESHOLDS["watcher_to_star"]
    ws_tripped = stars > 0 and ws < ws_thr
    ws_sev = _clamp((ws_thr - ws) / ws_thr) if ws_tripped else 0.0

    return [
        Signal(
            name="fork_to_star", value=round(fs, 4),
            baseline=BASELINES["fork_to_star"], threshold=fs_thr,
            weight=WEIGHTS["fork_to_star"], tripped=fs_tripped, severity=fs_sev,
            detail=f"{forks} forks / {stars} stars = {fs:.4f}", caveat=_CAVEAT,
        ),
        Signal(
            name="watcher_to_star", value=round(ws, 4),
            baseline=BASELINES["watcher_to_star"], threshold=ws_thr,
            weight=WEIGHTS["watcher_to_star"], tripped=ws_tripped, severity=ws_sev,
            detail=f"{watchers} watchers / {stars} stars = {ws:.4f}", caveat=_CAVEAT,
        ),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ratios.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/detectors/__init__.py fakestar/detectors/ratios.py tests/test_ratios.py
git commit -m "feat: fork/star and watcher/star ratio detector"
```

---

### Task 6: Profiles detector

**Files:**
- Create: `fakestar/detectors/profiles.py`, `tests/test_profiles.py`

**Interfaces:**
- Consumes: `Signal` (Task 1); `WEIGHTS`/`THRESHOLDS`/`BASELINES` (Task 2); a client exposing `iter_stargazers(owner, repo, max_pages=...)` and `get_user(login)` (Task 4).
- Produces:
  - `classify_account(user: dict, now: datetime) -> tuple[bool, bool]` returning `(is_ghost, is_suspicious)`.
    - ghost: `public_repos == 0 and followers == 0 and not bio`.
    - suspicious: `age_days < 365 and public_repos < 2 and followers < 2`.
  - `analyze_profiles(client, owner: str, repo: str, sample: int = 150, now: datetime | None = None) -> list[Signal]`. Samples up to `sample` stargazers (fetch enough pages: `ceil(sample/100)`), fetches each user, computes `ghost_pct` and `suspicious_pct` signals. Severity for "higher is worse" = `clamp((value - threshold) / (1 - threshold))`. If zero accounts sampled, both signals untripped with severity 0.

- [ ] **Step 1: Write the failing test** in `tests/test_profiles.py`

```python
from datetime import datetime, timezone

from fakestar.detectors.profiles import analyze_profiles, classify_account

NOW = datetime(2026, 6, 26, tzinfo=timezone.utc)


def _user(login, age_days, repos, followers, bio=""):
    created = datetime(2026, 6, 26, tzinfo=timezone.utc)
    created = created.replace(year=2026) 
    from datetime import timedelta
    created = NOW - timedelta(days=age_days)
    return {"login": login, "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "public_repos": repos, "followers": followers, "bio": bio}


def test_classify_ghost():
    g, s = classify_account(_user("x", 2000, 0, 0, ""), NOW)
    assert g is True


def test_classify_suspicious_new_empty():
    g, s = classify_account(_user("x", 100, 0, 0, ""), NOW)
    assert s is True


def test_classify_real_developer():
    g, s = classify_account(_user("x", 3000, 40, 120, "I build things"), NOW)
    assert g is False and s is False


class FakeClient:
    def __init__(self, users):
        self._users = users

    def iter_stargazers(self, owner, repo, max_pages=None):
        for u in self._users:
            yield {"login": u["login"]}

    def get_user(self, login):
        return next(u for u in self._users if u["login"] == login)


def test_analyze_profiles_flags_ghost_heavy_repo():
    users = [_user(f"g{i}", 1000, 0, 0, "") for i in range(8)] + \
            [_user(f"r{i}", 3000, 30, 50, "dev") for i in range(2)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["ghost_pct"].value == 0.8
    assert sigs["ghost_pct"].tripped is True


def test_analyze_profiles_clean_repo_untripped():
    users = [_user(f"r{i}", 3000, 30, 50, "dev") for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["ghost_pct"].tripped is False
    assert sigs["suspicious_pct"].tripped is False


def test_empty_sample_is_safe():
    sigs = analyze_profiles(FakeClient([]), "o", "r", sample=10, now=NOW)
    assert all(s.tripped is False for s in sigs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.detectors.profiles'`

- [ ] **Step 3: Write `fakestar/detectors/profiles.py`**

```python
from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def classify_account(user: dict, now: datetime) -> tuple[bool, bool]:
    repos = user.get("public_repos", 0) or 0
    followers = user.get("followers", 0) or 0
    bio = (user.get("bio") or "").strip()
    age_days = (now - _parse_dt(user["created_at"])).days

    is_ghost = repos == 0 and followers == 0 and not bio
    is_suspicious = age_days < 365 and repos < 2 and followers < 2
    return is_ghost, is_suspicious


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _pct_signal(name: str, value: float) -> Signal:
    thr = THRESHOLDS[name]
    tripped = value > thr
    sev = _clamp((value - thr) / (1 - thr)) if tripped else 0.0
    return Signal(
        name=name, value=round(value, 4), baseline=BASELINES[name],
        threshold=thr, weight=WEIGHTS[name], tripped=tripped, severity=sev,
        detail=f"{value:.1%} of sampled stargazers",
    )


def analyze_profiles(
    client, owner: str, repo: str, sample: int = 150, now: datetime | None = None,
) -> list[Signal]:
    now = now or datetime.now(timezone.utc)
    max_pages = max(1, ceil(sample / 100))

    logins: list[str] = []
    for item in client.iter_stargazers(owner, repo, max_pages=max_pages):
        logins.append(item["login"])
        if len(logins) >= sample:
            break

    ghosts = suspicious = 0
    counted = 0
    for login in logins:
        user = client.get_user(login)
        g, s = classify_account(user, now)
        ghosts += g
        suspicious += s
        counted += 1

    ghost_pct = ghosts / counted if counted else 0.0
    susp_pct = suspicious / counted if counted else 0.0
    return [_pct_signal("ghost_pct", ghost_pct), _pct_signal("suspicious_pct", susp_pct)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_profiles.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/detectors/profiles.py tests/test_profiles.py
git commit -m "feat: stargazer profile sampling detector (ghost/suspicious)"
```

---

### Task 7: Temporal burst detector

**Files:**
- Create: `fakestar/detectors/temporal.py`, `tests/test_temporal.py`

**Interfaces:**
- Consumes: `Signal` (Task 1); `WEIGHTS`/`THRESHOLDS`/`BASELINES` (Task 2); client `iter_stargazers(owner, repo, with_timestamps=True, max_pages=...)` (Task 4).
- Produces:
  - `detect_burst(timestamps: list[str], k: int = 20) -> tuple[float, str]` — bins stars by calendar day, computes the median daily count, marks any day whose count exceeds `k × median` as a "burst day", and returns `(burst_fraction, detail)` where `burst_fraction = (stars on burst days) / total`. Degenerate guard: if all stars fall on a single day, return `1.0` (the most extreme burst). Empty input → `0.0`.
  - `analyze_temporal(client, owner, repo, max_pages: int = 40) -> list[Signal]` — one `temporal_burst` signal. Trips when fraction > threshold. Severity = `clamp((fraction - threshold) / (1 - threshold))`. Empty timeline → untripped.

- [ ] **Step 1: Write the failing test** in `tests/test_temporal.py`

```python
from fakestar.detectors.temporal import analyze_temporal, detect_burst


def _ts(day):
    return f"2024-07-{day:02d}T12:00:00Z"


def test_detect_burst_spike():
    # 90 stars on one day, 10 spread across 10 days (median daily count = 1,
    # k*median = 20, only day 1 exceeds it -> 90/100 burst fraction)
    spike = [_ts(1)] * 90 + [_ts(d) for d in range(2, 12)]
    frac, _ = detect_burst(spike)
    assert frac == 0.9


def test_detect_burst_even_distribution_no_burst():
    # 1 per day for 20 days: median = 1, no day exceeds 20*median -> no burst
    even = [_ts(d) for d in range(1, 21)]
    frac, _ = detect_burst(even)
    assert frac == 0.0


def test_detect_burst_single_day_is_max():
    # everything on one day -> degenerate guard returns full burst
    frac, _ = detect_burst([_ts(1)] * 50)
    assert frac == 1.0


def test_detect_burst_empty():
    frac, _ = detect_burst([])
    assert frac == 0.0


class FakeClient:
    def __init__(self, timestamps):
        self._ts = timestamps

    def iter_stargazers(self, owner, repo, with_timestamps=False, max_pages=None):
        for t in self._ts:
            yield {"starred_at": t, "user": {"login": "x"}}


def test_analyze_temporal_trips_on_spike():
    spike = ["2024-07-01T00:00:00Z"] * 60 + ["2024-07-%02dT00:00:00Z" % d
                                             for d in range(2, 42)]
    sig = analyze_temporal(FakeClient(spike), "o", "r")[0]
    assert sig.name == "temporal_burst"
    assert sig.tripped is True


def test_analyze_temporal_clean():
    even = ["2024-07-%02dT00:00:00Z" % d for d in range(1, 29)]
    sig = analyze_temporal(FakeClient(even), "o", "r")[0]
    assert sig.tripped is False


def test_analyze_temporal_empty_safe():
    sig = analyze_temporal(FakeClient([]), "o", "r")[0]
    assert sig.tripped is False
    assert sig.value == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_temporal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.detectors.temporal'`

- [ ] **Step 3: Write `fakestar/detectors/temporal.py`**

```python
from __future__ import annotations

from collections import Counter
from statistics import median

from ..baselines import BASELINES, THRESHOLDS, WEIGHTS
from ..models import Signal


def detect_burst(timestamps: list[str], k: int = 20) -> tuple[float, str]:
    if not timestamps:
        return 0.0, "no timeline data"
    days = Counter(ts[:10] for ts in timestamps)  # bin by YYYY-MM-DD
    total = len(timestamps)
    if len(days) == 1:
        # all stars on a single day: the most extreme possible burst
        (only_day, count), = days.items()
        return 1.0, f"all {count} sampled stars on {only_day} (single-day burst)"
    med = median(days.values())
    cutoff = k * med
    burst_days = {d: c for d, c in days.items() if c > cutoff}
    burst_stars = sum(burst_days.values())
    fraction = burst_stars / total
    if burst_days:
        peak_day = max(burst_days, key=burst_days.get)
        detail = (f"{burst_stars}/{total} sampled stars on {len(burst_days)} "
                  f"burst day(s) (>{k}x median {med}); peak {peak_day}="
                  f"{days[peak_day]} ({fraction:.1%})")
    else:
        detail = f"no day exceeds {k}x median daily rate ({med}); evenly spread"
    return fraction, detail


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def analyze_temporal(client, owner: str, repo: str, max_pages: int = 40) -> list[Signal]:
    timestamps = [
        item["starred_at"]
        for item in client.iter_stargazers(
            owner, repo, with_timestamps=True, max_pages=max_pages)
    ]
    fraction, detail = detect_burst(timestamps)
    thr = THRESHOLDS["temporal_burst"]
    tripped = fraction > thr
    sev = _clamp((fraction - thr) / (1 - thr)) if tripped else 0.0
    return [Signal(
        name="temporal_burst", value=round(fraction, 4),
        baseline=BASELINES["temporal_burst"], threshold=thr,
        weight=WEIGHTS["temporal_burst"], tripped=tripped, severity=sev,
        detail=detail,
    )]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_temporal.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/detectors/temporal.py tests/test_temporal.py
git commit -m "feat: star-timeline burst detector"
```

---

### Task 8: Report renderers

**Files:**
- Create: `fakestar/report.py`, `tests/test_report.py`

**Interfaces:**
- Consumes: `Verdict`, `Signal` (Task 1).
- Produces:
  - `render_json(verdict: Verdict) -> str` — valid JSON with keys `repo`, `score`, `band`, `sample_size`, `notes`, `signals` (list of all Signal fields).
  - `render_text(verdict: Verdict, color: bool = False) -> str` — banner + aligned signal table + notes/caveats. `color=False` produces no ANSI codes (default for non-TTY / tests).

- [ ] **Step 1: Write the failing test** in `tests/test_report.py`

```python
import json

from fakestar.models import Signal, Verdict
from fakestar.report import render_json, render_text


def _verdict():
    sigs = [
        Signal("fork_to_star", 0.02, 0.16, 0.05, 30, True, 0.6,
               "2676 forks / 157000 stars", caveat="curated lists differ"),
        Signal("ghost_pct", 0.28, 0.01, 0.10, 25, True, 0.2, "28% ghosts"),
    ]
    return Verdict(72, "LIKELY MANIPULATED", sigs, 150, "o/r", ["temporal skipped"])


def test_render_json_roundtrips():
    data = json.loads(render_json(_verdict()))
    assert data["score"] == 72
    assert data["band"] == "LIKELY MANIPULATED"
    assert data["signals"][0]["name"] == "fork_to_star"
    assert data["notes"] == ["temporal skipped"]


def test_render_text_contains_verdict_and_signals():
    out = render_text(_verdict(), color=False)
    assert "LIKELY MANIPULATED" in out
    assert "72" in out
    assert "fork_to_star" in out
    assert "temporal skipped" in out
    assert "\x1b[" not in out  # no ANSI when color=False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.report'`

- [ ] **Step 3: Write `fakestar/report.py`**

```python
from __future__ import annotations

import json
from dataclasses import asdict

from .models import Verdict

_GREEN, _YELLOW, _RED, _RESET = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[0m"
_BAND_COLOR = {
    "LIKELY ORGANIC": _GREEN,
    "SUSPICIOUS": _YELLOW,
    "LIKELY MANIPULATED": _RED,
}


def render_json(verdict: Verdict) -> str:
    payload = {
        "repo": verdict.repo,
        "score": verdict.score,
        "band": verdict.band,
        "sample_size": verdict.sample_size,
        "notes": verdict.notes,
        "signals": [asdict(s) for s in verdict.signals],
    }
    return json.dumps(payload, indent=2)


def render_text(verdict: Verdict, color: bool = False) -> str:
    lines: list[str] = []
    band = verdict.band
    if color:
        band = f"{_BAND_COLOR.get(verdict.band, '')}{verdict.band}{_RESET}"
    lines.append(f"Repo:    {verdict.repo}")
    lines.append(f"Verdict: {band}  (risk score {verdict.score}/100)")
    lines.append(f"Sample:  {verdict.sample_size} stargazers")
    lines.append("")
    lines.append(f"{'SIGNAL':<18}{'VALUE':>10}{'BASELINE':>10}{'THRESH':>10}  TRIPPED")
    lines.append("-" * 60)
    for s in verdict.signals:
        mark = "YES" if s.tripped else "no"
        lines.append(
            f"{s.name:<18}{s.value:>10}{s.baseline:>10}{s.threshold:>10}  {mark}")
    caveats = [s.caveat for s in verdict.signals if s.caveat]
    if caveats or verdict.notes:
        lines.append("")
        lines.append("Notes & caveats:")
        for n in verdict.notes:
            lines.append(f"  - {n}")
        for c in dict.fromkeys(caveats):  # dedupe, keep order
            lines.append(f"  - {c}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add fakestar/report.py tests/test_report.py
git commit -m "feat: text and JSON report renderers"
```

---

### Task 9: CLI orchestration

**Files:**
- Create: `fakestar/cli.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: all prior modules. `analyze_ratios` (T5), `analyze_profiles` (T6), `analyze_temporal` (T7), `score_signals` (T3), `render_text`/`render_json` (T8), `GitHubClient`/`RepoNotFound`/`RateLimited` (T4).
- Produces:
  - `parse_args(argv: list[str]) -> argparse.Namespace` — positional `repo` (`owner/repo`), flags `--token`, `--sample` (default 150), `--timeline-pages` (default 40), `--ratios-only`, `--json`, `--wait`.
  - `run(args, client) -> Verdict` — orchestrates detectors with partial-failure tolerance (a detector raising appends a note and is skipped; `RepoNotFound` short-circuits to a max-signal verdict). `client` injected for testing.
  - `main(argv: list[str] | None = None) -> int` — resolves token (`--token` or `$GITHUB_TOKEN`; if neither, force `ratios_only` + note), builds `GitHubClient`, calls `run`, prints report, returns exit code (0 organic, 1 suspicious, 2 manipulated, 3 error).

- [ ] **Step 1: Write the failing test** in `tests/test_cli.py`

```python
import json

import pytest

from fakestar.cli import parse_args, run
from fakestar.github import RepoNotFound


def test_parse_args_defaults():
    a = parse_args(["octocat/hello"])
    assert a.repo == "octocat/hello"
    assert a.sample == 150
    assert a.timeline_pages == 40
    assert a.ratios_only is False
    assert a.json is False


class FakeClient:
    def __init__(self, repo, users, timestamps, fail=None):
        self._repo, self._users, self._ts, self._fail = repo, users, timestamps, fail

    def get_repo(self, o, r):
        if self._fail == "404":
            raise RepoNotFound("x")
        return self._repo

    def iter_stargazers(self, o, r, with_timestamps=False, max_pages=None):
        if with_timestamps:
            for t in self._ts:
                yield {"starred_at": t, "user": {"login": "x"}}
        else:
            for u in self._users:
                yield {"login": u["login"]}

    def get_user(self, login):
        return next(u for u in self._users if u["login"] == login)


def _ghosty_users(n):
    return [{"login": f"g{i}", "created_at": "2023-01-01T00:00:00Z",
             "public_repos": 0, "followers": 0, "bio": ""} for i in range(n)]


def test_run_manipulated_repo(monkeypatch):
    repo = {"stargazers_count": 157000, "forks_count": 2676, "subscribers_count": 168}
    ts = ["2024-07-01T00:00:00Z"] * 60 + ["2024-07-%02dT00:00:00Z" % d
                                          for d in range(2, 42)]
    client = FakeClient(repo, _ghosty_users(150), ts)
    args = parse_args(["o/r"])
    v = run(args, client)
    assert v.band == "LIKELY MANIPULATED"
    assert v.score >= 61


def test_run_repo_not_found_short_circuits():
    client = FakeClient({}, [], [], fail="404")
    v = run(parse_args(["o/r"]), client)
    assert "deleted" in " ".join(v.notes).lower() or "not found" in " ".join(v.notes).lower()
    assert v.band == "LIKELY MANIPULATED"


def test_run_ratios_only_skips_sampling():
    repo = {"stargazers_count": 70000, "forks_count": 16450, "subscribers_count": 2030}
    client = FakeClient(repo, [], [])
    v = run(parse_args(["o/r", "--ratios-only"]), client)
    names = {s.name for s in v.signals}
    assert names == {"fork_to_star", "watcher_to_star"}


def test_run_detector_failure_is_tolerated():
    repo = {"stargazers_count": 70000, "forks_count": 16450, "subscribers_count": 2030}

    class Boom(FakeClient):
        def get_user(self, login):
            raise RuntimeError("boom")

    client = Boom(repo, _ghosty_users(5), [])
    v = run(parse_args(["o/r"]), client)
    # profiles failed but ratios still present and a note recorded
    assert any(s.name == "fork_to_star" for s in v.signals)
    assert any("profile" in n.lower() for n in v.notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fakestar.cli'`

- [ ] **Step 3: Write `fakestar/cli.py`**

```python
from __future__ import annotations

import argparse
import os
import sys

from .detectors.profiles import analyze_profiles
from .detectors.ratios import analyze_ratios
from .detectors.temporal import analyze_temporal
from .github import GitHubClient, RateLimited, RepoNotFound
from .models import Signal, Verdict
from .report import render_json, render_text
from .scoring import score_signals

_EXIT = {"LIKELY ORGANIC": 0, "SUSPICIOUS": 1, "LIKELY MANIPULATED": 2}


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="fakestar-check",
        description="Score a GitHub repo for inauthentic-star evidence.")
    p.add_argument("repo", help="target repository as owner/repo")
    p.add_argument("--token", help="GitHub token (else $GITHUB_TOKEN)")
    p.add_argument("--sample", type=int, default=150,
                   help="stargazer profiles to sample (default 150)")
    p.add_argument("--timeline-pages", type=int, default=40,
                   help="star-timeline pages to fetch (default 40)")
    p.add_argument("--ratios-only", action="store_true",
                   help="skip profile and temporal detectors")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--wait", action="store_true",
                   help="sleep through rate-limit windows")
    return p.parse_args(argv)


def run(args: argparse.Namespace, client) -> Verdict:
    owner, _, repo = args.repo.partition("/")
    notes: list[str] = []

    try:
        repo_data = client.get_repo(owner, repo)
    except RepoNotFound:
        notes.append("Repository not found (404) — likely deleted by GitHub, "
                     "itself a strong manipulation signal.")
        sig = Signal("repo_deleted", 1.0, 0.0, 0.0, 100, True, 1.0,
                     "repo returns 404")
        return score_signals([sig], repo=args.repo, sample_size=0, notes=notes)

    signals: list[Signal] = list(analyze_ratios(repo_data))

    if not args.ratios_only:
        try:
            signals += analyze_profiles(client, owner, repo, sample=args.sample)
        except Exception as e:  # tolerate detector failure
            notes.append(f"Profile sampling skipped: {e}")
        try:
            signals += analyze_temporal(client, owner, repo,
                                        max_pages=args.timeline_pages)
        except Exception as e:
            notes.append(f"Temporal analysis skipped: {e}")

    return score_signals(signals, repo=args.repo, sample_size=args.sample,
                         notes=notes)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    token = args.token or os.environ.get("GITHUB_TOKEN")
    if not token:
        args.ratios_only = True
        print("WARNING: no token ($GITHUB_TOKEN); running ratios-only "
              "(unauthenticated rate limits forbid profile sampling).",
              file=sys.stderr)

    client = GitHubClient(token=token)
    try:
        verdict = run(args, client)
    except RateLimited as e:
        print(f"ERROR: GitHub rate limit hit (resets at epoch {e.reset_ts}). "
              f"Retry later or pass --wait.", file=sys.stderr)
        return 3

    if args.json:
        print(render_json(verdict))
    else:
        print(render_text(verdict, color=sys.stdout.isatty()))
    return _EXIT.get(verdict.band, 3)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tests green across all modules)

- [ ] **Step 6: Commit**

```bash
git add fakestar/cli.py tests/test_cli.py
git commit -m "feat: CLI orchestration with partial-failure tolerance"
```

---

## Self-Review

**Spec coverage:**
- §5.1 ratios → Task 5 ✓ | §5.2 profiles → Task 6 ✓ | §5.3 temporal → Task 7 ✓
- §6 scoring (weights, bands, proportional severity) → Tasks 2, 3 ✓
- §7 client (auth, 404, 403/429, retry, degrade, partial-failure) → Tasks 4, 9 ✓
- §8 output (text + `--json`) → Task 8 ✓
- §9 testing (fixtures, isolation, no live network) → all tasks use injected fakes ✓
- §10 CLI surface (all flags) → Task 9 `parse_args` ✓
- 404-as-signal (§6 deleted repo) → Task 9 `run` ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; commands have expected output.

**Type consistency:** `Signal`/`Verdict` field names consistent across Tasks 1, 3, 5–8. `analyze_ratios(repo)`, `analyze_profiles(client, owner, repo, sample, now)`, `analyze_temporal(client, owner, repo, max_pages)`, `score_signals(signals, repo, sample_size, notes)`, `render_text(verdict, color)`, `render_json(verdict)` — all match their call sites in Task 9. Client method names (`get_repo`, `get_user`, `iter_stargazers`) consistent across Tasks 4, 6, 7, 9.

**Note for executor:** `tests/fixtures/` is reserved (spec §9) for optional recorded-response and `--live` smoke tests; the unit tests above use inline fakes and need no fixture files to pass.
