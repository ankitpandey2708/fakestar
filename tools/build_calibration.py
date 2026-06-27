"""Build corpus/calibration.json (the MEASURED anchors + distributions) from the
vendored golden dataset (corpus/data/). The JSON is a generated artifact, never
hand-edited. The design knobs (groups, shrink/abstain, floors) are NOT here —
they live in fakestar/baselines.py, the single home for chosen parameters, and
are imported below. Run `python tools/build_calibration.py`; add `--validate`
to also report fake-vs-organic separation.

Anchor convention: [organic_value -> severity 0.0, fake_value -> severity 1.0].
"""
from __future__ import annotations

import json, random, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "corpus" / "data"
OUT = ROOT / "corpus" / "calibration.json"
REF = datetime(2025, 1, 1, tzinfo=timezone.utc)

sys.path.insert(0, str(ROOT))
from fakestar.baselines import (  # noqa: E402  (single home for chosen knobs)
    ABSTAIN_BELOW_N, BURST_MIN_STARS, LOW_ISSUES_ORGANIC_FLOOR, PROFILE_SIGNALS,
    SHRINK_PSEUDOCOUNT, STARGAZER_GROUP, UNCALIBRATED, USAGE_GROUP)


def _load_golden():
    return json.loads((DATA / "golden.json").read_text(encoding="utf-8"))


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0.0


def _quantile(xs, q):
    xs = sorted(xs)
    return xs[int(q * (len(xs) - 1))] if xs else 0.0


# ---- account distributions --------------------------------------------------
# record = [followers, public_repos, following, has_bio, created_at] or None (deleted)
def account_stats(records):
    n = zf = zr = zfo = ghost = susp = deleted = 0
    ages = []
    for rec in records:
        if rec is None:
            deleted += 1
            continue
        n += 1
        f, rp, fo, bio, created = rec[0], rec[1], rec[2], bool(rec[3]), rec[4]
        age = (REF - datetime.fromisoformat(created.replace("Z", "+00:00"))).days
        if f == 0: zf += 1
        if rp == 0: zr += 1
        if fo == 0: zfo += 1
        if rp == 0 and f == 0 and not bio: ghost += 1
        if age < 365 and rp < 2 and f < 2: susp += 1
        ages.append(age)
    pct = lambda x: round(100 * x / n, 1)
    total = n + deleted
    return {
        "zero_followers": pct(zf), "zero_repos": pct(zr), "zero_following": pct(zfo),
        "ghost": pct(ghost), "suspicious": pct(susp),
        "median_age_days": int(_median(ages)),
        "deleted_404": round(100 * deleted / total, 1) if total else 0.0,
        "_frac": {  # raw fractions for the anchors
            "zero_followers": zf / n, "zero_repos": zr / n, "zero_following": zfo / n,
            "ghost": ghost / n, "suspicious": susp / n, "median_age_days": _median(ages),
        },
    }


# ---- temporal burst ---------------------------------------------------------
def burst_median(pairs):
    # per-repo [total, max] aggregates; burst = biggest month / total
    fracs = [m / t for t, m in pairs if t >= BURST_MIN_STARS]
    return round(_median(fracs), 3)


# ---- control repo ratios ----------------------------------------------------
# row = [repo, stars, forks, watchers, issues]
def ratio_stats(rows):
    fork, watch, iss = [], [], []
    for _repo, s, f, w, i in rows:
        if s <= 0:
            continue
        fork.append(f / s)
        watch.append(w / s)
        iss.append(i / s)
    return {
        "fork_to_star": {"control_p10": round(_quantile(fork, .1), 4), "control_median": round(_median(fork), 4)},
        "watcher_to_star": {"control_p10": round(_quantile(watch, .1), 4), "control_median": round(_median(watch), 4)},
        "issues_to_star": {"control_p10": round(_quantile(iss, .1), 4), "control_median": round(_median(iss), 4)},
    }


def build():
    g = _load_golden()
    fake = account_stats(g["accounts"]["fake"])
    ctrl = account_stats(g["accounts"]["control"])
    burst_f = burst_median(g["timelines"]["fake"])
    burst_c = burst_median(g["timelines"]["control"])
    ratios = ratio_stats(g["control_ratios"])

    cf, ff = ctrl["_frac"], fake["_frac"]
    anchors = {
        "_doc": "[organic -> severity 0.0, fake -> severity 1.0]; fake<organic means lower-is-worse.",
        "ghost_pct":          [round(cf["ghost"], 3), round(ff["ghost"], 3)],
        "suspicious_pct":     [round(cf["suspicious"], 3), round(ff["suspicious"], 3)],
        "zero_followers_pct": [round(cf["zero_followers"], 3), round(ff["zero_followers"], 3)],
        "zero_repos_pct":     [round(cf["zero_repos"], 3), round(ff["zero_repos"], 3)],
        "zero_following_pct": [round(cf["zero_following"], 3), round(ff["zero_following"], 3)],
        "temporal_burst":     [burst_c, burst_f],
        "young_median_age":   [round(cf["median_age_days"], 1), round(ff["median_age_days"], 1)],
        "fork_to_star":       [ratios["fork_to_star"]["control_p10"], 0.0],
        "watcher_to_star":    [ratios["watcher_to_star"]["control_p10"], 0.0],
        "low_issues":         [LOW_ISSUES_ORGANIC_FLOOR, 0.0],
    }
    for d in (fake, ctrl):
        d.pop("_frac")

    out = {
        "_doc": "GENERATED by tools/build_calibration.py from corpus/data/. Do not hand-edit. "
                "Only the MEASURED anchors live here; chosen knobs are in fakestar/baselines.py. "
                "scoring.py reads `anchors`.",
        "source": g["manifest"]["source"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account_distributions": {"_unit": "percent of cohort, except median_age_days",
                                  "fake": fake, "control": ctrl},
        "repo_distributions": {"temporal_burst": {"fake_median": burst_f, "control_median": burst_c},
                               **ratios},
        "anchors": anchors,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"  anchors: {json.dumps({k: v for k, v in anchors.items() if not k.startswith('_')})}")


def validate(m=400):
    """Bootstrap synthetic repos from the vendored accounts; report separation."""
    import fakestar.scoring as cal
    from fakestar.baselines import WEIGHTS
    from dataclasses import dataclass
    cal._DATA, cal.ANCHORS = cal._load()            # reload freshly-built anchors
    cal.ABSTAIN_BELOW_N = 0
    random.seed(7)

    @dataclass
    class Sig:
        name: str; value: float; weight: int; severity: float; tripped: bool = False

    g = _load_golden()

    def load(cohort):
        pool = []
        for rec in g["accounts"][cohort]:
            if rec is None:
                pool.append(None); continue
            age = (REF - datetime.fromisoformat(rec[4].replace("Z", "+00:00"))).days
            pool.append((rec[0], rec[1], rec[2], bool(rec[3]), age))
        return pool

    def score(pool, n):
        draw = [random.choice(pool) for _ in range(n)]
        live = [a for a in draw if a]
        if not live:
            return None
        c = len(live)
        g = s = zf = zr = zfo = 0; ages = []
        for f, rp, fo, bio, age in live:
            if rp == 0 and f == 0 and not bio: g += 1
            if age < 365 and rp < 2 and f < 2: s += 1
            if f == 0: zf += 1
            if rp == 0: zr += 1
            if fo == 0: zfo += 1
            ages.append(age)
        v = {"ghost_pct": g/c, "suspicious_pct": s/c, "zero_followers_pct": zf/c,
             "zero_repos_pct": zr/c, "zero_following_pct": zfo/c,
             "young_median_age": float(_median(ages)), "temporal_burst": 0.0,
             "fork_to_star": 0.20, "watcher_to_star": 0.03, "low_issues": 0.02,
             "low_contributors": 50.0, "commit_staleness": 0.0}
        sigs = [Sig(k, val, WEIGHTS.get(k, 0), 0.0) for k, val in v.items()]
        return cal.subscores(sigs, c)["score"]

    fake, ctrl = load("fake"), load("control")
    print(f"\n{'n':>4} {'org_med':>8} {'fake_med':>9} {'org_p95':>8} {'AUC':>6}")
    for n in (10, 15, 20, 30, 50):
        o = sorted(x for x in (score(ctrl, n) for _ in range(m)) if x is not None)
        fk = sorted(x for x in (score(fake, n) for _ in range(m)) if x is not None)
        wins = sum(f > x for f in fk for x in o) + 0.5 * sum(f == x for f in fk for x in o)
        auc = wins / (len(fk) * len(o))
        print(f"{n:>4} {_median(o):>8} {_median(fk):>9} {_quantile(o, .95):>8} {auc:>6.2f}")


if __name__ == "__main__":
    build()
    if "--validate" in sys.argv:
        sys.path.insert(0, str(ROOT))
        validate()
