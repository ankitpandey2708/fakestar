"""Refresh corpus/data/golden.json from StarScout + the GitHub API. Run only to
re-snapshot; build_calibration.py reads the vendored file offline."""
from __future__ import annotations

import csv, io, json, random, subprocess, urllib.request
from datetime import datetime, timezone
from pathlib import Path

REF = "2025-01-01"
SS = "https://raw.githubusercontent.com/hehao98/StarScout/main/data/250101/"
OUT = Path(__file__).resolve().parent.parent / "corpus" / "data" / "golden.json"
csv.field_size_limit(10 ** 7)
random.seed(1)

# Anchors are stable well before these sizes (proportions to <=2%, medians solid);
# more examples just balloon the file. See docs/calibration.md.
CAP_ACCOUNTS = 3000   # per cohort
CAP_TIMELINES = 1000  # per cohort


def _cap(rows, n):
    return random.sample(rows, n) if len(rows) > n else rows


def _get(url):
    return urllib.request.urlopen(url, timeout=300).read().decode("utf-8", "replace")


def accounts(src):
    # row = [followers, public_repos, following, has_bio, created_at]; None = deleted
    out = []
    for r in csv.DictReader(io.StringIO(_get(SS + src))):
        raw = (r.get("raw_response") or "").strip()
        try:
            u = json.loads(raw) if raw.startswith("{") else {}
        except Exception:
            u = {}
        if not u.get("created_at"):
            out.append(None); continue
        out.append([u.get("followers", 0) or 0, u.get("public_repos", 0) or 0,
                    u.get("following", 0) or 0, 1 if (u.get("bio") or "").strip() else 0,
                    u["created_at"]])
    return out


def timelines(src):
    # per-repo [total_stars, max_month_stars]
    by = {}
    for r in csv.DictReader(io.StringIO(_get(SS + src))):
        repo = r.get("repo") or r.get("repo_name")
        if repo and r.get("n_stars"):
            by.setdefault(repo, []).append(int(r["n_stars"]))
    return [[sum(v), max(v)] for v in by.values()]


def control_ratios(n=90):
    # live [repo, stars, forks, watchers, issues] for a deterministic control sample
    ids = [l.split(",")[0] for l in _get(SS + "sample_repo_ids.csv").splitlines()[1:] if l]
    rows, checked = [], 0
    for repo in ids[::max(1, len(ids) // 400)]:
        if len(rows) >= n or checked >= 300:
            break
        checked += 1
        try:
            r = subprocess.run(
                ["gh", "api", f"repos/{repo}", "--jq",
                 "{s:.stargazers_count,f:.forks_count,w:.subscribers_count,i:.open_issues_count}"],
                capture_output=True, text=True, timeout=30)
            if r.returncode:
                continue
            j = json.loads(r.stdout)
            if (j["s"] or 0) < 100:
                continue
            rows.append([repo, j["s"], j["f"], j["w"], j["i"]])
            print(f"  ratios {len(rows)}/{n}", flush=True)
        except Exception:
            continue
    return rows


def main():
    golden = {
        "manifest": {
            "source": "StarScout (He et al.), https://github.com/hehao98/StarScout, data/250101",
            "reference_date": REF,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "accounts": {"fake": _cap(accounts("fake_user_info.csv"), CAP_ACCOUNTS),
                     "control": _cap(accounts("sample_user_info.csv"), CAP_ACCOUNTS)},
        "timelines": {"fake": _cap(timelines("fake_stars_clustered_stars_by_month.csv"), CAP_TIMELINES),
                      "control": _cap(timelines("sample_repo_stars_by_month.csv"), CAP_TIMELINES)},
        "control_ratios": control_ratios(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(golden), encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
