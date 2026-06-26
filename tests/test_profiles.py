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

    def get_stargazer_page(self, owner, repo, page, per_page=100):
        start = (page - 1) * per_page
        return [{"login": u["login"]} for u in self._users[start:start + per_page]]

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


def test_aged_empty_accounts_with_bio_are_caught():
    # Aged (1100d), zero repos, zero followers, but WITH a bio: these escape
    # both ghost (has bio) and suspicious (too old) — the blog's emphasized
    # blind spot. zero_followers_pct / zero_repos_pct must still catch them.
    users = [_user(f"a{i}", 1100, 0, 0, "hi there") for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["ghost_pct"].tripped is False
    assert sigs["suspicious_pct"].tripped is False
    assert sigs["zero_followers_pct"].value == 1.0
    assert sigs["zero_followers_pct"].tripped is True
    assert sigs["zero_repos_pct"].tripped is True


def test_young_median_age_trips_even_when_accounts_look_active():
    # Young accounts (120d) that are otherwise active (repos+followers) still
    # trip the age signal — age is independent of the activity fingerprints.
    users = [_user(f"n{i}", 120, 5, 5, "dev") for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["young_median_age"].value == 120.0
    assert sigs["young_median_age"].tripped is True


def test_old_median_age_does_not_trip():
    users = [_user(f"o{i}", 3000, 30, 50, "dev") for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["young_median_age"].tripped is False


def _follow_user(login, following):
    # otherwise real-looking account (aged, repos, followers, bio)
    return {"login": login, "created_at": "2020-01-01T00:00:00Z",
            "public_repos": 5, "followers": 5, "following": following, "bio": "dev"}


def test_zero_following_flags_accounts_that_follow_nobody():
    users = [_follow_user(f"f{i}", 0) for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["zero_following_pct"].value == 1.0
    assert sigs["zero_following_pct"].tripped is True
    # the otherwise-real-looking fingerprints stay clean
    assert sigs["ghost_pct"].tripped is False
    assert sigs["zero_followers_pct"].tripped is False


def test_accounts_that_follow_others_do_not_trip():
    users = [_follow_user(f"f{i}", 10) for i in range(10)]
    sigs = {s.name: s for s in analyze_profiles(FakeClient(users), "o", "r",
                                                sample=10, now=NOW)}
    assert sigs["zero_following_pct"].tripped is False


def test_sampling_spans_recent_pages_not_just_first():
    # 1000 stars => 10 pages. Page 1 is all clean devs; the LAST page is all
    # ghosts (a recent campaign). Sampling only page 1 would see 0% ghosts and
    # miss it; spread sampling must pull from the last page too.
    clean = [_user(f"r{i}", 3000, 30, 50, "dev") for i in range(100)]   # page 1
    ghosts = [_user(f"g{i}", 1000, 0, 0, "") for i in range(100)]       # page 10
    by_login = {u["login"]: u for u in clean + ghosts}
    pages = {1: clean, 10: ghosts}

    class PagedClient:
        def get_stargazer_page(self, owner, repo, page, per_page=100):
            return [{"login": u["login"]} for u in pages.get(page, [])]

        def get_user(self, login):
            return by_login[login]

    sigs = {s.name: s for s in analyze_profiles(
        PagedClient(), "o", "r", total_stars=1000, sample=150, now=NOW)}
    # sample=150 over 10 pages -> 2 pages [1, 10], 75 from each -> half ghosts
    assert sigs["ghost_pct"].value == 0.5
    assert sigs["ghost_pct"].tripped is True
