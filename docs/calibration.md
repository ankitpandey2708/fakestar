# Calibration & tuning guide

How fakestar decides a verdict, and the few things a human can change.

## TL;DR

There are **two kinds of numbers** in the scorer:

1. **Measured facts** — what fake vs organic repos actually look like. Derived from
   labeled data; **never hand-edited**.
2. **Policy knobs** — how cautious the tool should be given those facts. Chosen by
   a human; live in one file (`fakestar/baselines.py`).

**The defaults are already data-derived and balanced. You are not expected to set
anything.** Touch a knob only when you observe a specific behaviour you dislike
(recipes below).

## The pipeline

```
BUILD-TIME (rare)
  StarScout + GitHub API ──fetch_data.py──► corpus/data/golden.json   (raw labeled data, frozen)
  golden.json            ──build_calibration.py──► corpus/calibration.json  (measured anchors)

RUN-TIME (every check)
  repo ──detectors──► signals ──scoring.py──► Verdict ──report.py──► output
                                   ▲                ▲
                      anchors (calibration.json)   knobs (baselines.py)
```

`golden.json` is never read at runtime — only `calibration.json` (anchors) and
`baselines.py` (knobs) are.

## Where things live

| Thing | File | Authored by | Edit it? |
|---|---|---|---|
| Raw labeled data | `corpus/data/golden.json` | `fetch_data.py` (fetched) | no — regenerate via fetch |
| Measured anchors + distributions | `corpus/calibration.json` | `build_calibration.py` (computed) | **no — generated, never by hand** |
| Policy knobs | `fakestar/baselines.py` | human | yes, when needed |
| The computation | `tools/build_calibration.py` | human | only to change *how* anchors are derived |

**Rule:** measured facts → `calibration.json`; chosen knobs → `baselines.py`. No overlap.

## The knobs (all in `fakestar/baselines.py`)

| Knob | Default | Dial? | How to choose (no expertise needed) |
|---|---|---|---|
| `STARGAZER_GROUP` / `USAGE_GROUP` | — | structural | which signals form each axis; ~never change |
| `UNCALIBRATED` | contributors, staleness | structural | signals with no fake-vs-organic data → advisory only |
| `SHRINK_PSEUDOCOUNT` | 20 | rarely | k = sample size at which you half-trust the observation. Leave it. |
| `WEIGHTS` | (priors) | rarely | relative signal importance; a future "learn from data" candidate |
| **`ABSTAIN_BELOW_N`** | 15 | **policy** | from `--validate`: AUC 0.97 @ n=10, 0.99 @ n=15. Higher = more UNCERTAIN, safer. |
| **`BANDS`** | 18 / 44 | **policy** | organic p95 ≈ 15 → set organic ceiling near there. Higher = fewer false alarms. |

Only `ABSTAIN_BELOW_N` and `BANDS` are real policy dials. The rest are
set-and-forget.

## The one question that drives policy

> When unsure, would you rather the tool **cry wolf** (flag a clean repo) or
> **stay quiet** (miss a fake)?

- Hate false alarms → raise the `BANDS` organic ceiling and/or `ABSTAIN_BELOW_N`.
- Hate missing fakes → lower them.

Can't answer yet? The defaults are the balanced choice (~5% organic false-positive
rate, ~99% separation). Leave them.

## Tuning recipes

Each is mechanical. Always re-validate after (next section).

| Symptom | Change | Direction |
|---|---|---|
| Too many repos read `UNCERTAIN` | `ABSTAIN_BELOW_N` | lower (e.g. 15 → 10) |
| Flagging repos you know are fine | `BANDS` organic ceiling | raise (e.g. 18 → 22) |
| Missing repos you know are bought | `BANDS` organic ceiling | lower (e.g. 18 → 14) |
| A signal over/under-reacts on small samples | `SHRINK_PSEUDOCOUNT` | raise to distrust small n more |

## Re-tuning workflow

1. **Baseline first.** `python tools/build_calibration.py --validate` → record AUC /
   organic-p95 / fake-medians. You can't tell if a change helped without this.
2. **Change one knob** in `baselines.py`, with a reason from the data — never to make
   one specific repo come out a certain way.
3. **Rebuild + re-validate.** `python tools/build_calibration.py --validate`; diff vs step 1.
4. **Accept only if symmetric:** separation holds or improves *and* organic scores
   stay low while fake scores rise. A change that only inflates scores is bias — reject.
5. **Run tests + spot-check.** `pytest`, then a couple of real repos via the CLI.

## Refetching `golden.json` (rare)

`golden.json` is a frozen snapshot. Refetch (`python tools/fetch_data.py`) only when:

- StarScout publishes a newer snapshot, or a better labeled dataset appears, or
- you add a signal needing a field the snapshot lacks (e.g. contributor counts to
  calibrate `low_contributors`).

Changing a *knob* needs only a rebuild, not a refetch. Realistically refetch ~annually
at most. Don't refetch on a timer — run `--validate` against the current snapshot and
refetch only if separation degrades.

### Sample size

`fetch_data.py` caps the snapshot at `CAP_ACCOUNTS = 3000` and `CAP_TIMELINES = 1000`
per cohort. The anchors are statistics (cohort proportions, medians) that converge
well before that — measured: every anchor moves ≤0.02 between 1k and the full ~8k
pool, and the burst median is stable by ~500. More examples only balloon the file
without changing the result, so the snapshot is deliberately kept small (~230 KB).
Raise the caps only if you add a signal that needs finer-grained estimates.

## Guardrails (so tuning stays honest)

- Keep the repos under evaluation **out** of the fit — never tune until one repo flips.
- Every change must survive `--validate` and **cut both ways** (organic ↓, fake ↑).
- `calibration.json` is generated — if you're hand-editing it, you're doing it wrong;
  edit a knob in `baselines.py` or the data, then rebuild.
