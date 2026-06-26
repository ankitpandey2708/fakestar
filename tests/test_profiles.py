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
