# fakestar

Answers one question about a GitHub repository: **are its stars genuine?**

```
fakestar-check owner/repo
```

It samples the repo's actual stargazers, measures how empty and how young those
accounts are against a labeled fake-vs-organic dataset, checks whether forks and
watchers keep pace with stars, and prints a verdict with the coverage it was
based on.

## Install

```bash
git clone https://github.com/ankitpandey2708/fakestar.git
cd fakestar
pip install -e .
```

Requires Python 3.11+ and a GitHub token, taken from `--token`, then
`$GITHUB_TOKEN` / `$GH_TOKEN`, then `gh auth token`. `gh auth login` once is the
least effort. Any token with `public_repo` works.

## Run

```bash
fakestar-check pallets/flask
fakestar-check some/repo --json
fakestar-check some/repo --sample 500        # examine more accounts
fakestar-check some/repo --no-archive        # GitHub API only
fakestar-check some/repo --refresh           # ignore cached archive answers

# a renamed repo's earlier stars are filed under the old name
fakestar-check pallets/flask --also-known-as mitsuhiko/flask
```

That last flag matters more than it looks. The star record is keyed by repo
name with no repo id, so a rename splits a project's history in two. On
`pallets/flask` it is the difference between 59,728 stargazers from 2016 (83%
coverage) and 79,595 from 2011 (100%). The tool flags the symptom — a first
star landing long after the repo was created — but cannot discover the old name
itself, because GitHub exposes no former-names field.

Example:

```
Repo:      Shubhamsaboo/awesome-llm-apps
Verdict:   LIKELY ORGANIC   (risk 0 / 100, confidence high)
Examined:  65,383 of 129,822 stargazers (50%), 2024-04-29 to 2026-08-02
Source:    public star archive (spans the repo's history)

Result:    all 9 scored checks look normal

Who starred it:
    OK  Stargazers with no followers         21%   typical 36%
    OK  Completely empty accounts             5%   typical 8%
    OK  Stargazers with no repos             10%   typical 10%
    OK  New and inactive accounts             2%   typical 2%
    OK  Median account age                2,546d   typical floor 2,358d
    OK  Accounts since deleted                5%   typical 9%
    OK  Stars in the busiest month           13%   typical 14%

Stars against forks and watchers:
    OK  Forks per 1k stars                   148   typical floor 61
    OK  Watchers per 1k stars                 10   typical floor 7

Project activity (context, never scored):
    ·   Contributors                          99
    ·   Days since last commit                0d
    ·   Open issues                           22
```

Exit codes: `0` organic, `1` suspicious, `2` manipulated, `3` error,
`4` insufficient evidence.

## Where the data comes from

Two independent things went wrong, and they have different causes.

**1. GitHub restricted the stargazer list.** Since
[2026-06-30](https://github.blog/changelog/2026-06-30-upcoming-access-restrictions-to-public-api-endpoints-and-ui-views/),
`/repos/{owner}/{repo}/stargazers` and `/subscribers` serve admins and
collaborators only; every other repo gets a 404, and the `/stargazers` web view
is gone too. This is deliberate, announced, and permanent-looking. The stated
reason is scraping of user lists for spam.

**2. GH Archive's star capture collapsed.** The cause is its crawler, not
GitHub. The public event firehose still carries WatchEvents — sampled live, 14
of 300 events on the global `/events` endpoint — and its composition looks
nothing like the archive's:

| hour file | total events | WatchEvent | PushEvent share |
|---|---:|---:|---:|
| 2026-01-15 15:00 | 146,635 | 3,838 | 67% |
| 2026-05-01 15:00 | 159,145 | 422 | 81% |
| 2026-08-01 15:00 | 168,788 | 32 | 95% |
| GitHub's live global `/events` | — | 4.7% of events | 30% |

Cause, per
[gharchive.org#310](https://github.com/igrigorik/gharchive.org/issues/310) and
[#320](https://github.com/igrigorik/gharchive.org/issues/320): the crawler polls
only page 1 of a 3-page rotating feed, so at high volume it never sees events
that appear solely on pages 2–3. An October 2025 GitHub change that caches those
pages for ~10 minutes instead of ~1 second made it far worse. A fix exists in
[PR #317](https://github.com/igrigorik/gharchive.org/pull/317), unmerged; the
project looks unmaintained. Independent measurement in #320 puts capture at
~95–100% historically and **under 20% in 2026**.

This matters for how much to trust the numbers: because events are lost by
*which page they landed on*, not by who starred, the captured subset behaves
like a random sample of stargazers. Cohort percentages stay sound; absolute
counts and the timeline are undercounts.

Identities are sourced in this order, and the report always states which was
used:

| Source | Reach |
|---|---|
| GH Archive, via a public ClickHouse mirror (no auth) | the repo's star history, thinning badly through 2026 |
| GitHub stargazer list | same reach, your own repos only |
| GitHub repo event feed | last ~300 events — hours, on a busy repo |

Archive answers are cached under `$FAKESTAR_CACHE` (default:
platform cache dir) for a week. Point `--archive-url` or `$FAKESTAR_ARCHIVE_URL`
at your own mirror to avoid leaning on a shared public demo.

Coverage falls off for young repos, because most of their stars arrived while
the archive's capture rate was collapsing. Measured 2026-08-03:

| repo | stars | coverage |
|---|---:|---:|
| pallets/flask (2010) | 72,021 | full history |
| Shubhamsaboo/awesome-llm-apps (2024) | 129,822 | 50% |
| openclaw/openclaw (2025-11) | 384,946 | 19% |
| NousResearch/hermes-agent (2025-07) | 224,257 | 12% |

## What it checks

**Who starred it** — sampled accounts, scored against anchors measured from the
StarScout dataset (He et al., 3,000 labeled fake and 3,000 control accounts):
share with no followers, completely empty, no repos, young-and-inactive, median
account age, and share whose accounts have since been deleted. Plus the share of
stars landing in the single busiest month (labeled control median 14%,
manipulated 100%).

**Stars against forks and watchers** — a star is free; a fork or a watch is not.
Compared against 238 sampled peer repos of the same kind and size band, not a
global average, because curated lists and frameworks fork differently.

**Who starred it recently** — the archive is roughly a year behind on any active
repo, which is precisely where a live campaign would be. Those newest stars are
scored against `recent_baseline.json`: 58 peer repos measured through the same
event-feed pipeline. This matters because recent stargazers of *any* popular
repo skew new and empty — ordinary awesome-lists run 40–82% zero-followers in
their recent window against an all-time norm of 36%, so the all-time anchors
would condemn them.

**Never scored** — contributors, days since last commit, open issues. Real
information about whether a project is alive, which is a different question.
Open-issue rate in particular reads 0 per 1k on flask, langchain and
awesome-llm-apps, all organic; it was dropped from scoring for being noise.

## Three rules it follows

1. **A measurement is only compared to a reference produced the same way.** The
   anchors describe all-time stargazer populations. A sample of a repo's
   *recent* stargazers is displayed but never scored — recent stargazers of any
   popular repo skew new and empty. Ignoring this rates `pallets/flask` as
   SUSPICIOUS.
2. **Coverage is part of the answer.** Every verdict states what share of the
   stars it saw and over what dates.
3. **Silence beats a guess.** No scorable evidence yields
   `INSUFFICIENT EVIDENCE`. Fork and watcher ratios alone can accuse, never
   acquit — plenty of manipulated repos have ordinary fork counts.

## Limits

- A first-pass filter, not proof. Labels in this space are probabilistic.
- Anchors were measured from data dated 2025-01. They still match live
  measurements, but that has a shelf life.
- Stars from 2026 are largely absent from the archive, so a campaign run in the
  last few months is the case this tool is weakest against — exactly when it
  would matter most. The recent-events sample is the only window into that
  period and is never scored.
- Accounts deleted before the archive recorded them are invisible, so old
  campaigns are undercounted.
- Repos renamed since their stars arrived lose the history filed under the old
  name; the tool says so when it detects the gap.
- The peer table is a 238-repo sample, thin in the largest size bands.

## Calibration

`corpus/` holds the measured reference data; nothing in it is hand-tuned.

| File | What it is |
|---|---|
| `data/golden.json` | vendored StarScout cohorts: 3,000 fake + 3,000 control accounts, 1,000 timelines each |
| `calibration.json` | anchors derived from it — generated, never hand-edited |
| `peers.json` | fork/watcher percentiles for 238 repos by kind and size |
| `recent_baseline.json` | what the *newest* stargazers of 58 peer repos look like, so recent samples can be scored without borrowing all-time anchors |
| `labeled_repos.json` | held-out repos with published labels, never used for calibration |

```bash
python tools/fetch_data.py            # re-snapshot StarScout into golden.json
python tools/build_calibration.py --validate   # rebuild anchors, report separation
python tools/build_peers.py           # rebuild the peer ratio table
python tools/build_recent_baseline.py # rebuild the recent-stargazer norm
python tools/validate_repos.py        # end-to-end against the held-out labels
```

`build_calibration.py --validate` draws synthetic cohorts from the labeled
accounts and reports how well the score separates them. AUC is the probability
a random fake cohort outscores a random organic one:

```
   n  org_med  fake_med  org_p95    AUC
  15        5        38       16   1.00
  30        5        54       17   1.00
 100        4        79       13   1.00
```

`validate_repos.py` runs the whole tool against the held-out labels
(2026-08-03):

| repo | label | verdict | risk | coverage |
|---|---|---|---:|---:|
| openai/openai-fm | manipulated | LIKELY MANIPULATED | 70 | 52% |
| DigitalPlatDev/FreeDomain | manipulated | LIKELY MANIPULATED | 58 | 54% |
| raga-ai-hub/RagaAI-Catalyst | manipulated | LIKELY MANIPULATED | 54 | 69% |
| unionlabs/union | manipulated | SUSPICIOUS | 43 | 97% |
| shardeum/shardeum | manipulated | SUSPICIOUS | 37 | 100% |
| django/django | organic | LIKELY ORGANIC | 6 | 100% |
| psf/requests | organic | LIKELY ORGANIC | 6 | 33% |
| pallets/flask | organic | LIKELY ORGANIC | 5 | 83% |
| numpy/numpy | organic | LIKELY ORGANIC | 4 | 100% |
| facebook/react | organic | LIKELY ORGANIC | 2 | 100% |
| fastapi/fastapi | organic | LIKELY ORGANIC | 0 | 17% |

5/5 manipulated flagged, 6/6 organic clean, no overlap between the groups
(worst organic 6, best manipulated 37).

## Layout

```
fakestar/
  cli.py           orchestration, exit codes
  evidence.py      StarSample, RepoFacts, Provenance, Coverage
  collect.py       picks the best available source, records which
  sources/         the only code that touches the network
  detectors/       pure functions over evidence: accounts, timeline, ratios
  baselines.py     anchors, peer table, repo-kind inference
  verdict.py       scoring, confidence, band
  report.py        text and JSON
```

Design notes: `docs/superpowers/specs/2026-08-03-fakestar-redesign.md`.

## License

MIT
