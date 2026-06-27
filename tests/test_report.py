import json

from fakestar.models import Signal, Verdict
from fakestar.report import render_json, render_text


def _verdict():
    sigs = [
        Signal("fork_to_star", 0.02, 0.16, 0.05, 30, True, 0.6,
               "2676 forks / 157000 stars", caveat="curated lists differ"),
        Signal("ghost_pct", 0.28, 0.01, 0.10, 25, True, 0.2, "28% ghosts"),
    ]
    return Verdict(72, "LIKELY MANIPULATED", sigs, 150, "o/r", ["temporal skipped"])


def test_render_json_roundtrips():
    data = json.loads(render_json(_verdict()))
    assert data["score"] == 72
    assert data["band"] == "LIKELY MANIPULATED"
    assert data["signals"][0]["name"] == "fork_to_star"
    assert data["notes"] == ["temporal skipped"]
    assert "stargazer_score" in data and "usage_score" in data


def _healthy_verdict():
    sigs = [
        Signal("fork_to_star", 0.15, 0.16, 0.05, 20, False, 0.0, "ok"),
        Signal("ghost_pct", 0.0, 0.01, 0.10, 10, False, 0.0, "ok"),
    ]
    return Verdict(0, "LIKELY ORGANIC", sigs, 130, "zuplo/zudoku", [])


def test_render_text_grouped_view_marks_flags():
    out = render_text(_verdict(), color=False)
    assert "LIKELY MANIPULATED" in out
    assert "72" in out
    assert "flagged" in out
    # two-axis sub-scores shown in the header
    assert "stargazer-quality" in out and "real-usage" in out
    # themed axis headers give structure
    assert "Who starred it:" in out
    assert "Is the code actually used:" in out
    # friendly labels + FLAG marker + organic reference in words
    assert "FLAG" in out
    assert "Empty 'ghost' accounts" in out
    assert "Forks (per 1k stars)" in out
    assert "typical organic" in out          # calibrated reference, not a threshold
    assert "fork_to_star" not in out         # raw name hidden in default view
    assert "temporal skipped" in out
    assert "\x1b[" not in out


def test_render_text_no_flags_summary():
    out = render_text(_healthy_verdict(), color=False)
    assert "no stargazer/usage signals flagged" in out
    assert "OK" in out                # healthy lines marked OK
    assert "Forks (per 1k stars)" in out
    assert "typical organic" in out  # reference shown on healthy rows too


def test_render_text_colorizes_band_only_when_enabled():
    assert "\x1b[" in render_text(_verdict(), color=True)
    assert "\x1b[" not in render_text(_verdict(), color=False)


def test_render_text_unknown_signal_falls_into_other_group():
    # the 404 path emits a "repo_deleted" signal that isn't in _META
    sigs = [Signal("repo_deleted", 1.0, 0.0, 0.0, 100, True, 1.0, "repo returns 404")]
    v = Verdict(100, "LIKELY MANIPULATED", sigs, 0, "gone/repo", ["deleted"])
    out = render_text(v, color=False)
    assert "Other checks:" in out
    assert "repo_deleted" in out  # falls back to the raw name as label
    assert "FLAG" in out


def test_render_text_verbose_shows_raw_table():
    out = render_text(_verdict(), color=False, detailed=True)
    assert "fork_to_star" in out          # raw names
    assert "CAL.SEV" in out               # calibrated-severity column
    assert "Forks (per 1k stars)" not in out
    assert "Who starred it" not in out    # grouped view suppressed in verbose
