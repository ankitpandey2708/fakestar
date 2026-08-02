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
from fakestar.baselines import BURST_MIN_STARS  # noqa: E402  (chosen knobs live there)


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
            # Accounts that starred and have since been removed by GitHub.
            # Only observable from a historical source: a live stargazer list
            # cannot contain accounts that no longer exist.
            "deleted": (deleted / total) if total else 0.0,
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
        "deleted_pct":        [round(cf["deleted"], 3), round(ff["deleted"], 3)],
        "burst":              [burst_c, burst_f],
        "young_median_age":   [round(cf["median_age_days"], 1), round(ff["median_age_days"], 1)],
        # Un-conditioned ratio references over 90 control repos. Superseded at
        # runtime by corpus/peers.json, which conditions on repo kind and size;
        # kept as the fallback for when that file is absent.
        "fork_to_star":       [ratios["fork_to_star"]["control_p10"], 0.0],
        "watcher_to_star":    [ratios["watcher_to_star"]["control_p10"], 0.0],
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
    """Draw synthetic cohorts from the vendored accounts and report how well the
    cohort score separates them. AUC is the probability that a random fake
    cohort outscores a random organic one; 0.5 is a coin flip, 1.0 is perfect."""
    import importlib

    import fakestar.baselines as bl
    importlib.reload(bl)                 # pick up the anchors just written
    from fakestar.detectors.accounts import measure
    from fakestar.evidence import Account

    random.seed(7)
    g = _load_golden()

    def load(cohort):
        pool = []
        for rec in g["accounts"][cohort]:
            if rec is None:
                pool.append(None)        # deleted account
                continue
            pool.append(Account(
                login="x", followers=rec[0], public_repos=rec[1],
                following=rec[2], has_bio=bool(rec[3]),
                created_at=datetime.fromisoformat(rec[4].replace("Z", "+00:00"))))
        return pool

    def score(pool, n):
        draw = [random.choice(pool) for _ in range(n)]
        accounts = [a if a is not None else Account(login="gone", deleted=True)
                    for a in draw]
        num = den = 0.0
        for meas in measure(accounts, REF):
            sev = bl.anchored_severity(
                meas.name, bl.shrink(meas.name, meas.value, meas.n))
            if sev is None:
                continue
            w = bl.WEIGHTS.get(meas.name, 0)
            num += w * sev
            den += w
        return round(100 * num / den) if den else None

    fake, ctrl = load("fake"), load("control")
    print(f"\n{'n':>4} {'org_med':>8} {'fake_med':>9} {'org_p95':>8} {'AUC':>6}")
    for n in (10, 15, 20, 30, 50, 100):
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
