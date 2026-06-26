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


def test_render_text_plain_view_groups_flags():
    out = render_text(_verdict(), color=False)
    assert "LIKELY MANIPULATED" in out
    assert "72" in out
    assert "Red flags (2):" in out
    # friendly labels, not raw signal names, and direction spelled out
    assert "Forks (per 1k stars)" in out
    assert "Stargazers with 0 followers" not in out  # not in this verdict
    assert "Empty 'ghost' accounts" in out
    assert "healthy: under 10%" in out      # ghost_pct, "lower is worse"
    assert "healthy: over 50 per 1k" in out  # fork_to_star, "higher is worse"
    assert "fork_to_star" not in out         # raw name hidden in default view
    assert "temporal skipped" in out
    assert "\x1b[" not in out


def test_render_text_no_flags_message():
    out = render_text(_healthy_verdict(), color=False)
    assert "No red flags. All 2 checks look healthy" in out
    assert "Forks (per 1k stars)" in out
    assert "(healthy:" not in out  # no safe-line hints on healthy rows


def test_render_text_verbose_shows_raw_table():
    out = render_text(_verdict(), color=False, detailed=True)
    assert "fork_to_star" in out          # raw names
    assert "THRESH" in out                # raw columns
    assert "Forks (per 1k stars)" not in out
