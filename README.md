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

### Authenticate (required)
A GitHub token is **required** — the full analysis makes hundreds of API calls,
far beyond the 60/hour unauthenticated limit. A token raises that to 5,000/hour.
```bash
export GITHUB_TOKEN=ghp_xxx        # or pass --token
```
A classic token with `public_repo` scope is enough. Without one, the tool exits
with an error telling you to set it.

### Run
```bash
fakestar-check facebook/react
fakestar-check some/suspicious-repo --json
fakestar-check big/repo --sample 300 --timeline-pages 60
fakestar-check small/repo --sample 30        # faster: fewer profiles
```

### Options
| Flag | Default | Meaning |
|------|---------|---------|
| `--token TOKEN` | `$GITHUB_TOKEN` | GitHub personal access token (**required**) |
| `--sample N` | `auto` | stargazer profiles to sample; `auto` sizes from star count, or pass an integer |
| `--margin F` | 0.08 | target margin of error for `--sample auto` |
| `--max-sample N` | 150 | cap for `--sample auto` |
| `--timeline-pages N` | 40 | star-timeline pages to fetch |
| `--workers N` | 8 | parallel workers for stargazer profile fetching |
| `--json` | off | emit JSON instead of a text report (mutually exclusive with `--verbose`) |
| `--verbose` | off | show the raw value/baseline/threshold table (mutually exclusive with `--json`) |
| `--wait` | off | sleep until the rate-limit window resets and retry, instead of erroring out |

### Exit codes
`0` LIKELY ORGANIC · `1` SUSPICIOUS · `2` LIKELY MANIPULATED · `3` error (e.g. rate-limited)

### Sample size (`--sample auto`)
By default the sample size is **computed from the repo's star count**, not fixed.
It targets a ±8% margin of error (95% confidence) with finite-population
correction, so big repos converge to ~150 profiles while small repos sample
fewer (no point pulling 150 profiles from a 200-star repo). Examples: 100★→61,
1,000★→131, 12,887★→149, 1M★→150. Override with an explicit `--sample 300`, or
tune `--margin`/`--max-sample`.

### Performance & progress
Profile fetches run **concurrently** (`--workers`, default 8), cutting a ~60s
run to a few seconds. When attached to a terminal, the tool prints progress to
stderr (`... Sampling up to N stargazer profiles...`); this is suppressed for
pipes/`--json`. All HTTP requests use a 15s timeout so a stalled network can't
hang the run.

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
*are these real fans, or paid actors?* You don't have to interpret any numbers.
Every check is **grouped by theme**, marked **OK** or **FLAG**, and shows in
plain words what *would* make it a flag (`flag if over/under X`) — no thresholds
or `<`/`>` to decode. Here's a real run on `zuplo/zudoku`:

```
Repo:    zuplo/zudoku
Verdict: LIKELY ORGANIC   (risk 0 / 100)
Sample:  130 stargazers analyzed

Result:  no red flags - all 12 checks healthy

Who starred it:
  OK    Empty 'ghost' accounts        0%           (flag if over 10%)
  OK    New low-activity accounts     0%           (flag if over 15%)
  OK    Stargazers with 0 followers   5%           (flag if over 35%)
  OK    Stargazers with 0 repos       3%           (flag if over 20%)
  OK    Stargazers following nobody   5%           (flag if over 55%)
  OK    Median account age            3823 days    (flag if under 730 days)
  OK    Biggest 1-day star burst      0%           (flag if over 30%)

Is the code actually used:
  OK    Forks (per 1k stars)          151 per 1k   (flag if under 50 per 1k)
  OK    Watchers (per 1k stars)       11 per 1k    (flag if under 2 per 1k)
  OK    Open issues (per 1k stars)    115 per 1k   (flag if under 1 per 1k)

Is the project real & active:
  OK    Contributors                  47           (flag if under 10)
  OK    Days since last commit        0 days       (flag if over 365 days)
```

Read it top-down: the **risk score** (0 = squeaky clean, 100 = almost certainly
manipulated), then scan the left column for any **FLAG**. zudoku is all **OK**.

When something *is* off, that line is marked **FLAG** and the count appears in
the `Result:` line, so problems jump out:

```
Verdict: LIKELY MANIPULATED   (risk 72 / 100)
Sample:  150 stargazers analyzed

Result:  3 red flag(s) - look for FLAG below

Who starred it:
  FLAG  Stargazers with 0 followers   81%          (flag if over 35%)
  OK    Empty 'ghost' accounts        4%           (flag if over 10%)
  FLAG  Biggest 1-day star burst      60%          (flag if over 30%)
  ...
Is the code actually used:
  FLAG  Forks (per 1k stars)          20 per 1k    (flag if under 50 per 1k)
  ...
```

What each check is really asking:

| Check | In plain English |
|-------|------------------|
| Forks (per 1k stars) | Do people copy the code to actually use it? |
| Watchers (per 1k stars) | Do people subscribe for updates? |
| Empty 'ghost' accounts | How many clappers are empty bot accounts (no repos/followers/bio)? |
| New low-activity accounts | How many are brand-new, no-activity accounts? |
| Stargazers with 0 followers | How many have no friends on GitHub? (bought accounts usually don't) |
| Stargazers with 0 repos | How many have no projects of their own? |
| Stargazers following nobody | How many follow nobody? (real devs follow people) |
| Median stargazer account age | How old are the accounts? (fakes are young) |
| Biggest 1-day star burst | Did stars arrive in one suspicious spike? |
| Contributors | Did real people help build it? |
| Days since last commit | Is the project still alive? |
| Open issues (per 1k stars) | Are real users filing bugs/questions? |

**Bottom line for zudoku:** real coders, with friends and their own projects, on
decade-old accounts, starring gradually — plus an active project with real
contributors and bug reports. Nothing looks faked, so the verdict is confidently
organic. A *manipulated* repo typically passes some checks but trips the profile
ones hard (e.g. 50–80% zero-followers) — that mismatch is the giveaway.

> Want the raw numbers (exact value / baseline / threshold per signal)? Add
> `--verbose` for the detailed table.

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
python -m pytest -v        # injected fake clients — no GitHub calls
```

**2. Live validation against the blog's labels** (needs a token):
```bash
export GITHUB_TOKEN=ghp_xxx        # run in your own shell — don't paste tokens into chat tools
fakestar-check pallets/flask
fakestar-check DigitalPlatDev/FreeDomain
fakestar-check DigitalPlatDev/FreeDomain --sample 30   # quicker spot-check
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
