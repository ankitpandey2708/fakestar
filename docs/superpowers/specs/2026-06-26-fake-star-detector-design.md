# Fake-Star Detector — Design

**Date:** 2026-06-26
**Status:** Approved
**Author:** Ankit

## 1. Purpose

A command-line tool that scores a single GitHub repository for evidence of
purchased / inauthentic stars. It codifies the detection logic described in the
"Inside GitHub's Fake Star Economy" investigation
(https://awesomeagents.ai/news/github-fake-stars-investigation/), implementing
the replicable GitHub-API layer (not the 20TB event-mining StarScout layer).

**Form factor:** CLI one-off check — `fakestar-check <owner/repo>`.
**Output:** 0–100 risk score + human-readable report + optional `--json`.

### Core premise

A star is free and signals nothing; real engagement (forks, watchers, account
substance, natural timing) is expensive or slow to fake. The tool compares the
cheap-to-fake metric (stars) against expensive-to-fake ones to expose the gap.

## 2. Scope

In scope (maximum detail, all three detection layers):

1. **Engagement ratios** — fork-to-star, watcher-to-star.
2. **Stargazer profile sampling** — sample N stargazers, measure account age,
   public repos, followers, bio → ghost% and suspicious%.
3. **Temporal burst analysis** — star timeline, detect unnatural spikes.

Out of scope:

- Large-scale event mining over GH Archive / BigQuery (the StarScout approach).
- Batch/portfolio scanning, library/API, web dashboard (possible later; this is
  a single-repo CLI).
- Detecting repo *type* (curated list vs library) — surfaced as a caveat, not
  auto-suppressed.

## 3. Architecture

```
fakestar/
  cli.py            # arg parsing, orchestration, output routing
  github.py         # API client: auth, pagination, rate-limit handling, retries
  detectors/
    ratios.py       # fork/star + watcher/star (1 call)
    profiles.py     # sample N stargazers -> age/repos/followers/bio -> ghost%/suspicious%
    temporal.py     # starred_at timeline -> burst detection
  scoring.py        # weighted signals -> 0-100 risk + verdict
  baselines.py      # organic reference constants (Flask/LangChain/AutoGPT-derived)
  report.py         # human-readable renderer + JSON serializer
  models.py         # dataclasses: RepoStats, ProfileSample, Signal, Verdict
tests/
  fixtures/         # recorded API responses (organic + manipulated repos)
```

**Runtime:** Python 3.11+. Dependencies: `requests` (HTTP). Optional: a color
library, otherwise ANSI codes directly. No heavy/ML deps.

**Data flow:**
`cli` → `github` fetches repo metadata + stargazer pages →
each `detector` returns `Signal` objects →
`scoring` aggregates into a `Verdict` →
`report` renders text or JSON.

**Isolation:** Each detector takes a `GitHubClient` + repo identifier and
returns a list of `Signal`s. No detector imports `scoring` or `report`. The
client is the only shared dependency. This makes each detector unit-testable
against fixtures.

## 4. Data Models (`models.py`)

```python
@dataclass
class Signal:
    name: str          # e.g. "fork_to_star"
    value: float       # observed value
    baseline: float    # organic reference
    threshold: float   # trip threshold
    weight: int        # contribution to score
    tripped: bool
    detail: str        # human explanation
    caveat: str | None # e.g. "low forks normal for curated lists"

@dataclass
class Verdict:
    score: int                 # 0-100
    band: str                  # LIKELY ORGANIC | SUSPICIOUS | LIKELY MANIPULATED
    signals: list[Signal]
    sample_size: int
    repo: str
    notes: list[str]           # gaps, degradations, caveats
```

## 5. Detectors & Signals

### 5.1 ratios.py (1 API call)

- `fork_to_star = forks / stars` — baseline ~0.16. **Trip if < 0.05 AND stars > 10,000.**
- `watcher_to_star = subscribers_count / stars` — baseline 0.005–0.03. **Trip if < 0.002.**
- Attach caveat to both: docs/curated-list repos naturally have low forks.

### 5.2 profiles.py (N+1 calls; N default 150, `--sample`)

- Page through `/repos/{owner}/{repo}/stargazers`; draw the sample spread across
  pages (not just page 1) for large repos.
- Per account capture: `created_at` (→ age in days), `public_repos`,
  `followers`, `bio`.
- Derived signals (all scored; all appear in the report whether tripped or not):
  - **ghost%** = accounts with `public_repos == 0 AND followers == 0 AND no bio`.
    Baseline ~1%. **Trip if > 10%.**
  - **suspicious%** = accounts with `age < 365d AND public_repos < 2 AND followers < 2`.
    Baseline ~0%. **Trip if > 15%.**
  - **zero_followers%** = accounts with `followers == 0`. Baseline ~10%.
    **Trip if > 35%.** Strongest single profile discriminator; catches aged
    empty accounts (with bios, >365d old) that ghost% and suspicious% miss.
  - **zero_repos%** = accounts with `public_repos == 0`. Baseline ~5%.
    **Trip if > 20%.**
  - **zero_following%** = accounts with `following == 0`. Baseline ~40%.
    **Trip if > 55%.** Weak supporting signal (real devs tend to follow
    others, but many legitimate users follow nobody) — low weight, high
    threshold to limit false positives. Not measured in the source study;
    derived from its prose ("…and follow other users").
  - **young_median_age** = median sampled account age in days ("lower is worse").
    Baseline ~3000d. **Trip if median < 730d.** Catches young campaigns
    (e.g. medians of ~100–500 days).

### 5.3 temporal.py (paginated timeline, capped)

- Fetch `starred_at` using header `Accept: application/vnd.github.star+json`.
- Cap pages fetched (default 40 pages / configurable `--timeline-pages`) so we
  don't pull 150k+ timestamps.
- Bin stars by day; compute median daily rate; flag **burst days** where
  `count > k * median` (k default 20).
- **Signal:** largest single-day burst as a fraction of sampled stars.
  **Trip if a burst day exceeds 30% of sampled stars** (tunable).

## 6. Scoring (`scoring.py`)

Weighted contribution model. Each tripped signal contributes proportionally to
how far it exceeds its threshold (not binary), capped at its weight.

Default weights (sum 100):

| Signal             | Weight |
|--------------------|--------|
| fork_to_star       | 23     |
| zero_followers_pct | 16     |
| watcher_to_star    | 12     |
| ghost_pct          | 12     |
| suspicious_pct     | 12     |
| zero_repos_pct     | 9      |
| young_median_age   | 7      |
| temporal_burst     | 5      |
| zero_following_pct | 4      |

`zero_followers_pct` is weighted highest among the profile signals: the
source investigation shows it is the single most discriminating profile
metric (organic 6–12% vs manipulated 52–81%). `ghost_pct` is the strict
intersection (no repos AND no followers AND no bio) and under-detects aged
accounts that carry a bio, so it is down-weighted in favour of
`zero_followers_pct` / `zero_repos_pct`. `young_median_age` ("lower is worse",
median sampled account age in days, threshold 730) catches young campaigns
that the emptiness fingerprints miss.

Verdict bands:

- **0–25:** LIKELY ORGANIC
- **26–60:** SUSPICIOUS
- **61–100:** LIKELY MANIPULATED

Weights and bands live in single constants for easy tuning. A deleted repo (404)
is itself strong evidence (90% of StarScout-flagged repos were deleted) and is
reported as a high-signal special case.

## 7. GitHub Client, Auth, Errors (`github.py`)

- Token resolution: `--token` flag, else `$GITHUB_TOKEN`. If absent: warn and
  **degrade to ratios-only** (unauthenticated = 60 req/hr, can't sample).
- Error handling:
  - **404** — repo gone → emit high-signal note, score accordingly.
  - **403 / 429** rate limit — read `X-RateLimit-Reset`, print clear message;
    `--wait` optionally sleeps until reset.
  - **5xx** — retry with exponential backoff (max 3).
- **Partial-failure tolerance:** if `temporal` (or any detector) fails, still
  produce a verdict from the others and record the gap in `Verdict.notes`.

## 8. Output (`report.py`)

- **Default text report:** signal table (`value | baseline | threshold |
  tripped`), verdict banner, caveats/notes section. ANSI color, degrades to
  plain on non-TTY.
- **`--json`:** full structured `Verdict` (every signal, raw counts, sample
  size, score, band, notes) to stdout for piping/storage.

## 9. Testing

- **TDD.** Unit tests run against `tests/fixtures/` — recorded JSON for one
  known-organic repo (Flask-like) and one known-manipulated repo (FreeDomain-like).
- Each detector tested in isolation on fixtures.
- `scoring` tested with synthetic `Signal` lists (boundary cases per band).
- `github` client tested with mocked responses (pagination, 404, 403, retry).
- No live network in unit tests. One optional `--live` smoke test, gated.

## 10. CLI Surface

```
fakestar-check <owner/repo> [options]

  --token TOKEN          GitHub token (else $GITHUB_TOKEN)
  --sample N             stargazer profiles to sample (default 150)
  --timeline-pages N     star-timeline pages to fetch (default 40)
  --ratios-only          skip profile + temporal detectors
  --json                 emit JSON instead of text report
  --wait                 sleep through rate-limit windows
```

## 11. Open Caveats (documented, not solved)

- Ratio heuristics false-positive on curated lists / docs / educational repos.
- Profile sampling reflects *current* account state; accounts deleted since the
  star event won't be counted (under-counts older campaigns).
- Thresholds are derived from the article's small sample; treated as tunable
  defaults, not ground truth.
