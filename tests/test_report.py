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
    assert "2 red flag(s)" in out
    # themed group headers give structure
    assert "Who starred it:" in out
    assert "Is the code actually used:" in out
    # friendly labels + FLAG marker + trip condition in words
    assert "FLAG" in out
    assert "Empty 'ghost' accounts" in out
    assert "Forks (per 1k stars)" in out
    assert "flag if over 10%" in out       # ghost_pct, higher is worse
    assert "flag if under 50 per 1k" in out  # fork_to_star, lower is worse
    assert "fork_to_star" not in out         # raw name hidden in default view
    assert "temporal skipped" in out
    assert "\x1b[" not in out


def test_render_text_no_flags_summary():
    out = render_text(_healthy_verdict(), color=False)
    assert "no red flags - all 2 checks healthy" in out
    assert "FLAG" not in out          # nothing tripped
    assert "OK" in out                # every line marked OK
    assert "Forks (per 1k stars)" in out
    assert "flag if under 50 per 1k" in out  # context shown on healthy rows too


def test_render_text_colorizes_band_only_when_enabled():
    assert "\x1b[" in render_text(_verdict(), color=True)
    assert "\x1b[" not in render_text(_verdict(), color=False)


def test_render_text_verbose_shows_raw_table():
    out = render_text(_verdict(), color=False, detailed=True)
    assert "fork_to_star" in out          # raw names
    assert "THRESH" in out                # raw columns
    assert "Forks (per 1k stars)" not in out
    assert "Who starred it" not in out    # grouped view suppressed in verbose
