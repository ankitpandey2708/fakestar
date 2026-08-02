# fakestar, from first principles

## The question the tool exists to answer

> Is this repository's star count trustworthy evidence of genuine interest?

One question. One verdict. Everything else in the codebase must earn its place by
helping answer it.

## What is actually knowable (measured 2026-08-03)

GitHub restricted the stargazers listing to admins and collaborators
([changelog 2026-06-30](https://github.blog/changelog/2026-06-30-upcoming-access-restrictions-to-public-api-endpoints-and-ui-views/)).
Separately, GH Archive's capture of star events collapsed. Same hour-of-day,
three dates, from GH Archive's raw hourly files:

| hour file | total events | WatchEvent | PullRequest | IssueComment |
|---|---|---|---|---|
| 2026-01-15 15:00 | 146,635 | 3,838 | 10,632 | 4,880 |
| 2026-05-01 15:00 | 159,145 | 422 | 1,577 | 698 |
| 2026-08-01 15:00 | 168,788 | 32 | 144 | 51 |

The cause is GH Archive's crawler, not GitHub. GitHub's global `/events`
endpoint still serves WatchEvents — 14 of 300 sampled live on 2026-08-03 — and
its composition (30% PushEvent) looks nothing like the archive's 95%. The
crawler polls only page 1 of a 3-page rotating feed, so at high volume it never
sees events that surface solely on pages 2–3; a GitHub change after the
2025-10-08 outage that caches those pages for ~10 minutes instead of ~1 second
made it far worse
([#310](https://github.com/igrigorik/gharchive.org/issues/310),
[#320](https://github.com/igrigorik/gharchive.org/issues/320); fix open in
PR #317, unmerged, project apparently unmaintained). Independent measurement in
#320: ~95–100% capture historically, under 20% in 2026.

Consequences for this design: losses are keyed to which page an event landed on,
not to who starred, so the surviving events approximate a random sample of
stargazers. Cohort percentages remain valid; absolute counts and timelines are
undercounts. A correctly-written collector polling all three pages would capture
near-100% going forward, which is the strongest argument for building watch
mode.

Three evidence channels remain, with different reach:

| Channel | Gives | Reach |
|---|---|---|
| GH Archive (public ClickHouse mirror, no auth) | stargazer logins + exact star timestamps | ~95-100% capture before mid-2025, under 20% through 2026 |
| GitHub REST `/repos/{o}/{r}` | exact counts: stars, forks, watchers | always |
| GitHub REST `/repos/{o}/{r}/events` | recent stargazer logins | last ~300 events (hours on a busy repo) |
| GitHub REST `/users/{login}` | account substance; 404 = deleted/suspended | always |

No fourth channel exists. OSSInsight and BigQuery are downstream of GH Archive
and carry identical gaps — verified: OSSInsight's series for
`Shubhamsaboo/awesome-llm-apps` totals 65,192 against the mirror's 65,383, with
monthly deltas agreeing to within two events. `go-faster/gh-archive-clickhouse`
is a better crawler but ships as software to self-host with a three-day TTL, not
as a public dataset. Wayback holds a handful of `/stargazers` HTML pages, a few
dozen accounts each. The missing events are not access-controlled; they were
never written down.

Archive coverage of a repo's current stars, measured:

| repo | stars | archive coverage |
|---|---|---|
| pallets/flask (2010) | 72,021 | full history (plus 21k under `mitsuhiko/flask` pre-rename) |
| Shubhamsaboo/awesome-llm-apps (2024) | 129,819 | 51% |
| openclaw/openclaw (2025-11) | 384,946 | 19% |
| NousResearch/hermes-agent (2025-07) | 224,257 | 12% |

## Why identity evidence is worth the trouble

Sampling each repo's archived stargazers and enriching via `/users`:

| repo | zero-followers | ghost | median age | deleted |
|---|---|---|---|---|
| DigitalPlatDev/FreeDomain *(labeled fake)* | 82% | 32% | 951d | 7% |
| shardeum/shardeum *(labeled fake)* | 55% | 30% | 1216d | 9% |
| pallets/flask *(labeled organic)* | 23% | 8% | 4016d | 7% |
| langchain-ai/langchain *(labeled organic)* | 20% | 4% | 2915d | 1% |

Clean separation, and consistent with the vendored StarScout anchors (fake
zero-followers 69.7%, control 36.0%). The existing calibration survives — but
only for all-time cohorts, which is what the archive yields.

## Design

### Invariant #1 — never cross measurement pipelines

A value measured one way may only be compared to a baseline measured the same
way. Violating this is what makes `pallets/flask` score SUSPICIOUS when its
recent-event window is judged against all-time anchors: recent stargazers of any
popular repo skew young and empty. Enforced structurally — every measurement
carries its `Provenance`, and scoring refuses anchors whose provenance differs.

### Invariant #2 — coverage is part of the answer

Every verdict states what fraction of the stars it could actually examine and
over what date range. A verdict from 12% coverage is not the same object as a
verdict from 100%, and the tool must never let them look alike.

### Invariant #3 — abstain over guess

No evidence for an axis means that axis is unscored, and a clean result from the
remaining axes cannot produce a clean *verdict* — it produces
`INSUFFICIENT EVIDENCE`.

### Evidence regimes

| Identity coverage | Verdict basis |
|---|---|
| ≥ 40% | account cohort + timeline + ratios |
| 5–40% | same, coverage-weighted, span stated |
| < 5% | ratios vs type-matched peers only |

### Confidence has two independent halves

Coverage and sample size measure different things, and conflating them is
wrong in both directions.

**Precision** comes from how many accounts were profiled. Because the archive
loses events by which page they landed on rather than by who starred, a sample
drawn from a fraction of a repo's stars is still a fair draw — 300 accounts are
300 accounts, worth about ±5.7% at 95% confidence whether they came from 12% of
the population or all of it.

**Representativeness** comes from coverage, because the losses are concentrated
in recent months. Thin coverage does not make the estimate noisy; it makes it a
statement about an older slice of the repo's life.

Reported confidence is the weaker of the two. This is why raising `--sample`
cannot buy back a verdict on a repo whose record stops a year ago.

### Recency: measuring the blind spot

Coverage averaged over a repo's lifetime hides the thing that matters most. A
campaign is recent, and the archive's gap is recent, so the two coincide
exactly.

The tool therefore measures its own currency per repo: GitHub's event feed gives
the live star rate, the archive gives what it recorded over the same recent
window, and the ratio is that repo's present-day capture rate. On
`Shubhamsaboo/awesome-llm-apps` this is ~1%, against 50% lifetime coverage —
two numbers that tell very different stories, only one of which was previously
visible.

Below 50% current capture the verdict carries an explicit `Blind spot:` line and
`burst` stops being scored: a record that captures old months better than recent
ones inflates old months' share and would hide exactly the recent spike worth
finding.

Recency does **not** cap confidence. It did briefly, and the result was that ten
of eleven labeled repos read `medium` — the archive is behind on every repo that
is still gaining stars, so the only `high` left was a repo that had stopped
gaining them. A field that says the same thing about react, flask and a known
fake-star repo is not carrying information. Recency is reported on its own line,
where it says something specific.

### Scoring the newest stars

The blind spot is not just a caveat to print; it is the period a campaign would
live in. Recent stargazers become scorable by measuring the norm through the
identical pipeline — `corpus/recent_baseline.json`, built by
`tools/build_recent_baseline.py` from the recent star events of 58 peer repos,
bucketed by kind and size.

The measured skew is large and kind-dependent, which is why borrowing the
all-time anchors here is so destructive:

| cell | zero-followers p50 | p90 |
|---|---|---|
| code, all sizes | 40% | 53% |
| content, all sizes | 47% | 80% |
| content 50k-200k | 55% | 80% |
| content 200k+ | 60% | 82% |

against an all-time organic norm of 36%. `trimstray/the-book-of-secret-knowledge`,
an ordinary awesome-list, runs 82% zero-followers and 57% ghost in its recent
window; judged against 36% it would read as flagrantly bought.

The normal line is the cell's **p90**, not its median. With a handful of peers
per cell and legitimate values spanning 40-82%, anything tighter flags healthy
repos. The far end reuses the fake-to-organic *ratio* measured on all-time
cohorts: the base rate for recent stargazers differs, but the separation
produced by buying is a property of the buying and transfers where the absolute
number does not.

Excluded from this axis: `burst` (a few hundred events spanning hours say
nothing about a busiest month), `deleted_pct` (an account that starred yesterday
has had no time to be removed), and `young_median_age` (the one signal where
lower is worse, pending a low percentile in the baseline).

**Known weakness: the peer pool is not known to be clean.** Peers come from
GitHub search. A manipulated repo among them raises the p90 ceiling and makes
the tool more forgiving — failing in the direction of missing fakes rather than
inventing them, but failing all the same. Repos carrying published manipulation
labels are excluded, and that list is five entries long.

Two mitigations, one done and one not. The baseline now records which repos set
each cell, so the pool can be audited rather than trusted. Not done: scoring
each peer's *all-time* cohort against the StarScout anchors — which are
independent of the peer table — and dropping any that flag, then rebuilding.
That is a bootstrap rather than a circularity, because the seed comes from
labeled data.

A partial audit of the peers via archived timelines was inconclusive. The three
flagged for extreme single-month concentration all turned out to have truncated
archive histories — `react/react` shows 46 archived stars against 200k+ real
ones, its history stranded under `facebook/react` — and a burst share computed
on a truncated history means nothing. The one peer checked properly,
`trimstray/the-book-of-secret-knowledge`, is clean by independent evidence:
194,309 distinct stargazers across 92 months, biggest month 3.9%, against a
labeled control median of 14% and a fake median of 100%.

Validated on `Shubhamsaboo/awesome-llm-apps`: its recent 52% zero-followers and
22% ghost score 0.0 against a 80%/35% ceiling, while a synthetic 95%/80% cohort
scores 0.75/0.69 and lands LIKELY MANIPULATED at 73.

### Recovering renamed repos

The mirror stores `repo_name` and no repo id, so a rename splits a project's
history into two unrelated buckets. `pallets/flask` carries stars from 2016;
its first five years sit under `mitsuhiko/flask`. Left alone this reads as 83%
coverage when the truth is 100%.

Former names are found automatically rather than asked for, since a user has no
way to know them. A rename leaves a clean fingerprint — the old name's stars
stop at the instant the new name's begin, and renames nearly always keep one
half of the path — so candidates come from a single cheap query over names
sharing an owner or repo component whose history ends as ours starts. Each
candidate is then confirmed against GitHub, which still redirects old paths to
their current repo, so a coincidence of naming can never quietly contaminate the
sample. `--also-known-as` remains as a manual override.

Measured on `pallets/flask`: 59,728 stargazers from 2016 (83%) becomes 79,595
from 2011 (100%). The control case, a repo never renamed, yields no candidates.

### Signals kept, cut, added

**Kept (scored).** Account cohort: `zero_followers_pct`, `ghost_pct`,
`zero_repos_pct`, `suspicious_pct`, `young_median_age`. Timeline: `burst`.
Ratios: `fork_to_star`, `watcher_to_star` — these are authenticity evidence
(cheap-to-fake vs expensive-to-fake), not a separate "liveness" axis.

**Added.** `deleted_pct` — accounts that starred and no longer exist. Only
measurable via the archive, since GitHub's live list never contained them.
StarScout: fake 18.2% vs control 9.4%.

**Cut.** `low_issues` — reads 0 per 1k on flask, langchain and awesome-llm-apps,
all organic, so it fires on healthy repos and carries no signal.
`low_contributors` and `commit_staleness` demote to unscored context: they
measure project liveness, which is a different question.

**Cut.** The blended two-axis score. One number, or the honest absence of one.

### Peer-conditioned ratios

Fork and watcher ratios are compared against repos of the same *kind* and size
band, not a global p10. Kind is inferred from repo metadata already in hand
(language, topics, name): `content` (curated list, docs, tutorial) vs `code`.
Curated lists and frameworks fork and watch at different rates, so a global
reference flags the former for behaving normally. Measured: content repos fork
*more* than code repos (median 120 vs 100 per 1k stars).

### Module layout

```
fakestar/
  cli.py           orchestration, exit codes
  evidence.py      StarSample, RepoFacts, Provenance, Coverage — the shared vocabulary
  models.py        Measurement, Signal, Verdict
  collect.py       picks the best available source, records which one it was
  sources/
    github.py      repo facts, user enrichment, recent events
    archive.py     ClickHouse mirror; pluggable endpoint; disk cache
  detectors/
    accounts.py    cohort fingerprints
    timeline.py    burst detection
    ratios.py      peer-conditioned ratio mismatch
  baselines.py     anchors, peer table, repo-kind inference
  verdict.py       scoring, confidence, band
  report.py        text + JSON
  cache.py         on-disk memo
  token.py         token resolution, importable without the CLI
```

Detectors are pure functions of evidence objects. Sources are the only code that
touches the network. Verdict never sees a raw HTTP response.

## Deferred: watch mode, a collector of our own

The firehose is healthy; only GH Archive's crawler is not. That makes the gap
fixable going forward by recording the stream ourselves, and it is the only
route to complete coverage on a repo nobody here owns.

### The technique, taken from the unmerged upstream fix

[PR #317](https://github.com/igrigorik/gharchive.org/pull/317) is Ruby against
EventMachine, so none of it ports literally, but its substance is three ideas
and roughly forty lines of Python:

1. **Poll every page, not just page 1.** GitHub's global `/events` serves three
   pages of 100 that rotate together. Polling page 1 alone means events that
   only ever surface on pages 2–3 are never seen — the entire root cause. The
   PR also corrects `per_page` from a nonexistent 500 down to 100.
2. **Conditional GET per page.** An `If-None-Match` with the page's last ETag
   returns 304 and costs nothing against the rate limit, which is what makes
   sub-second polling affordable.
3. **Deduplicate by event `id`** across polls, tracking the highest id seen.

Rate budget: 5,000 requests/hour against 3 pages is a poll every ~2.2 seconds,
and 304s are free, so keeping up with ~4,000 global stars/hour is comfortable.

### How it would slot in

A separate long-running command (`fakestar collect`), not part of
`fakestar-check`, which runs for thirty seconds. It writes to a local event
store that `collect.py` then consults as a source ranked *above* the archive for
recent stars, filling precisely the window the archive has lost.
`Provenance.WATCH` is already reserved in the data model, and the two-part
confidence rule already knows how to combine a fresh local record with an older
archived one.

Open design question: record the global firehose and filter later, or filter to
a watchlist at ingest. Global is simple and future-proof — every repo is covered
without deciding in advance which ones matter — at the cost of storing all of
GitHub's activity. A watchlist is far cheaper but only answers questions you
knew to ask.

### Why it is still deferred

It is forward-only. It recovers none of the 64,445 stars already missed on
`Shubhamsaboo/awesome-llm-apps`, because those events were never recorded by
anyone — GH Archive was the only public recorder, its crawler dropped them, and
the one authoritative back-fill (`/stargazers`) was restricted on 2026-06-30.
A record started today cannot answer a question asked today, and the core
verdict had to be trustworthy first.

## Success criteria, and results

1. Labeled-manipulated repos → SUSPICIOUS or MANIPULATED. **5/5**, risk 37-70.
2. Labeled-organic repos → ORGANIC, with nothing flagged for being a curated
   list. **6/6**, risk 0-6. No overlap between the groups.
3. A repo with no identity coverage never returns ORGANIC on ratios alone.
   Verified: `pallets/flask --no-archive` returns `INSUFFICIENT EVIDENCE` with
   all seven cohort signals unscored, where all-time anchors applied to the same
   recent-window sample had produced SUSPICIOUS (41).
4. Every run states coverage and the date span examined.
5. Synthetic cohorts drawn from the labeled account pool separate at **AUC
   1.00** for samples of 15 or more; organic p95 (13-17) sits below the
   organic band ceiling of 20.
