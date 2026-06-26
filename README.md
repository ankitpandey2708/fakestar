# fakestar

> Score a GitHub repository 0–100 for evidence of purchased / inauthentic stars.

`fakestar-check <owner/repo>` pulls a repo's public signals from the GitHub API,
compares the cheap-to-fake metric (stars) against the expensive-to-fake ones
(forks, watchers, account substance, natural timing), and returns a risk score
with a clear verdict: **LIKELY ORGANIC · SUSPICIOUS · LIKELY MANIPULATED**.

---

## The 5 Ws

### What
A small Python CLI that estimates how many of a repository's stars are likely
fake. It runs three independent detectors and combines them into a weighted
0–100 risk score:

| Detector | Signal | Idea |
|----------|--------|------|
| **Ratios** | fork-to-star, watcher-to-star | A star is free; a fork/watch means someone actually uses the code. Real projects fork ~16% of star count; manipulated ones <5%. |
| **Profiles** | ghost%, suspicious%, zero-followers%, zero-repos%, zero-following%, young median age | Samples stargazer accounts (spread across the star history) and measures emptiness and youth. Zero-followers% is the strongest single discriminator (organic 6–12% vs manipulated 52–81%); it and zero-repos% catch *aged* empty accounts that the stricter ghost/suspicious tests miss. Zero-following% (accounts that follow nobody) is a weak supporting signal — real devs tend to follow others. |
| **Temporal** | burst fraction | Bins stars by day and flags days that exceed `k × median` daily rate — bought stars arrive in unnatural spikes. |
| **Engagement** | low-contributors, commit-staleness, low-issues | The blog's "what VCs should use instead": real adoption is hard to fake. A repo with huge stars but few contributors, no recent commits, and almost no issues shows no genuine engagement. Ratio signals gated to repos with >10k stars to avoid flagging small solo projects. |

Output is a human-readable report by default, or machine-readable JSON with `--json`.

### Why
A GitHub star costs **$0.03–$0.85** on open marketplaces. A seed round is worth
millions, and VCs use star counts as a sourcing signal (the median seed-stage
repo has ~2,850 stars). That asymmetry created a mature fake-star economy: a
peer-reviewed CMU study (ICSE 2026) found ~6 million fake stars across 18,617
repositories. This tool codifies the detection heuristics from that research and
the [*Inside GitHub's Fake Star Economy*](https://awesomeagents.ai/news/github-fake-stars-investigation/)
investigation so anyone can run a first-pass check themselves.

### Who
- **Investors / analysts** doing technical due diligence on a repo's traction.
- **Maintainers & engineers** sanity-checking a dependency or a trending project before adopting it.
- **Researchers & journalists** quantifying manipulation across projects.

### Where
Runs anywhere Python 3.11+ runs (Windows/macOS/Linux). It only needs the public
GitHub REST API and a personal access token (for rate limits). No database, no
cloud service, no 20TB of event data — just the API.

### When
Use it when a repo's star count looks too good to be true: a sudden spike in
stars, a high star count with almost no forks/watchers, or before you cite stars
as evidence of adoption. It's a **first-pass filter**, not proof — see *Caveats*.

---

## How to use it

### Install
```bash
git clone https://github.com/ankitpandey2708/fakestar.git
cd fakestar
pip install -e .
```

### Authenticate
A GitHub token raises your rate limit from 60 to 5,000 requests/hour, which is
required for profile sampling.
```bash
export GITHUB_TOKEN=ghp_xxx        # or pass --token
```
Without a token the tool automatically degrades to **ratios-only** mode.

### Run
```bash
fakestar-check facebook/react
fakestar-check some/suspicious-repo --json
fakestar-check big/repo --sample 300 --timeline-pages 60
fakestar-check any/repo --ratios-only     # 1 API call, no sampling
```

### Options
| Flag | Default | Meaning |
|------|---------|---------|
| `--token TOKEN` | `$GITHUB_TOKEN` | GitHub personal access token |
| `--sample N` | 150 | stargazer profiles to sample |
| `--timeline-pages N` | 40 | star-timeline pages to fetch |
| `--ratios-only` | off | skip profile + temporal detectors |
| `--workers N` | 8 | parallel workers for stargazer profile fetching |
| `--json` | off | emit JSON instead of a text report |
| `--wait` | off | sleep until the rate-limit window resets and retry, instead of erroring out |

### Exit codes
`0` LIKELY ORGANIC · `1` SUSPICIOUS · `2` LIKELY MANIPULATED · `3` error (e.g. rate-limited)

### Performance & progress
A full run fetches ~150 stargazer profiles plus the timeline — these profile
fetches run **concurrently** (`--workers`, default 8), cutting a ~60s run to a
few seconds. When attached to a terminal, the tool prints progress to stderr
(`… Sampling 150 stargazer profiles…`); this is suppressed for pipes/`--json`.
All HTTP requests use a 15s timeout so a stalled network can't hang the run.

---

## How the score works
Each detector emits `Signal`s with a `severity` in `[0, 1]`. The final score is
`round(Σ weight × severity)`, clamped to 0–100:

| Signal | Weight |
|--------|-------:|
| fork-to-star | 20 |
| zero-followers% | 14 |
| suspicious% | 11 |
| watcher-to-star | 10 |
| ghost% | 10 |
| zero-repos% | 8 |
| low-contributors | 7 |
| young median age | 6 |
| temporal burst | 5 |
| commit-staleness | 4 |
| zero-following% | 3 |
| low-issues | 2 |

A repo that returns `404` is scored as deleted (a strong manipulation signal —
~90% of repos flagged by the CMU study were later removed by GitHub).

---

## Reading a result (worked example, in plain English)

Think of a repo's stars as **people who clapped** for a project. The tool asks:
*are these real fans, or paid actors?* Here's a real run on `zuplo/zudoku`:

```
Repo:    zuplo/zudoku
Verdict: LIKELY ORGANIC  (risk score 0/100)
Sample:  130 stargazers

SIGNAL                 VALUE  BASELINE    THRESH  TRIPPED
------------------------------------------------------------
fork_to_star          0.1514      0.16      0.05  no
watcher_to_star       0.0108     0.015     0.002  no
ghost_pct                0.0      0.01       0.1  no
suspicious_pct           0.0       0.0      0.15  no
zero_followers_pct    0.0538       0.1      0.35  no
zero_repos_pct        0.0308      0.05       0.2  no
zero_following_pct    0.0538       0.4      0.55  no
young_median_age      3823.0    3000.0     730.0  no
temporal_burst           0.0      0.05       0.3  no
low_contributors        47.0      50.0      10.0  no
commit_staleness         0.0      30.0     365.0  no
low_issues           0.11532      0.02     0.001  no
```

**How to read the columns:** `THRESH` is the "uh-oh line" — a signal only counts
against the repo if `VALUE` crosses it (`TRIPPED = yes`). `BASELINE` is just what a
typical organic repo looks like, for reference. Here nothing tripped, so the score
is **0/100 → LIKELY ORGANIC** (higher score = more suspicious).

What each signal is really asking:

| Signal | In plain English | zudoku |
|--------|------------------|--------|
| `fork_to_star` | Did people copy the code to actually use it? | Yes ✅ |
| `watcher_to_star` | Did people subscribe for updates? | Yes ✅ |
| `ghost_pct` | How many clappers are empty bot accounts (no repos/followers/bio)? | ~0% ✅ |
| `suspicious_pct` | How many are brand-new, no-activity accounts? | 0% ✅ |
| `zero_followers_pct` | How many have no friends on GitHub? (bought accounts usually don't) | 5% ✅ |
| `zero_repos_pct` | How many have no projects of their own? | 3% ✅ |
| `zero_following_pct` | How many follow nobody? (real devs follow people) | 5% ✅ |
| `young_median_age` | How old are the accounts? (fakes are young) | ~10 years ✅ |
| `temporal_burst` | Did stars arrive in one suspicious spike? | No, gradual ✅ |
| `low_contributors` | Did real people help build it? | 47 contributors ✅ |
| `commit_staleness` | Is the project still alive? | Updated today ✅ |
| `low_issues` | Are real users filing bugs/questions? | Lots ✅ |

**Bottom line:** real coders, with friends and their own projects, on decade-old
accounts, starring gradually — plus an active project with real contributors and
bug reports. No part of the story looks faked, so the verdict is confidently
organic. A *manipulated* repo typically passes some checks but trips the
profile ones hard (e.g. 50–80% zero-followers) — that mismatch is the giveaway.

---

## Caveats
- **First-pass filter, not proof.** Curated lists, docs, and tutorial repos
  naturally have low fork/watcher ratios — and often few contributors, no
  issue tracker, and infrequent pushes — so they can trip the ratio and
  engagement signals despite being legitimate. The modest engagement weights
  mean these alone won't reach LIKELY MANIPULATED, but treat such repos with
  judgment.
- Profile sampling reflects accounts' *current* state; accounts deleted since the
  star event aren't counted, so old campaigns are under-counted.
- Thresholds are tunable defaults derived from a small sample, not ground truth.

## Testing & validation

**1. Automated tests** (no network, instant):
```bash
pip install -e ".[dev]"
python -m pytest -v        # 61 tests, injected fake clients — no GitHub calls
```

**2. Quick live check, no token** — auto-degrades to ratios-only (1 API call, fits the 60/hr unauthenticated limit):
```bash
python -m fakestar.cli pallets/flask --ratios-only
python -m fakestar.cli DigitalPlatDev/FreeDomain --ratios-only
```
On real data this reproduces the investigation's numbers — Flask's fork-to-star
is ~0.235, FreeDomain's ~0.020. (Ratios-only contributes ≤35 points, so flagged
repos stay in the lower bands here; the profile/engagement signals that fully
condemn them need a token — see below.)

**3. Full validation against the blog's labels** (needs a token for sampling):
```bash
export GITHUB_TOKEN=ghp_xxx        # run in your own shell — don't paste tokens into chat tools
fakestar-check DigitalPlatDev/FreeDomain
```
Confirm the two groups separate cleanly:

| Expectation | Repos |
|---|---|
| **Low score** (LIKELY ORGANIC) | `pallets/flask`, `langchain-ai/langchain`, `Significant-Gravitas/AutoGPT` |
| **High score** (SUSPICIOUS / MANIPULATED) | `DigitalPlatDev/FreeDomain`, `shardeum/shardeum`, `unionlabs/union`, `raga-ai-hub/RagaAI-Catalyst` |

If you see a `RequestsDependencyWarning` about urllib3/charset versions, that's a
local environment mismatch, not this tool — `pip install -U urllib3 charset_normalizer` clears it.

## Development
Architecture: isolated detectors (`fakestar/detectors/`) feed a scoring engine
(`scoring.py`); a thin API client (`github.py`) is the only shared dependency.
Each detector returns `Signal`s and is independently unit-testable against fake
clients. See `docs/superpowers/specs/` and `docs/superpowers/plans/` for the design.

## License
MIT
