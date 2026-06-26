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


def test_render_text_contains_verdict_and_signals():
    out = render_text(_verdict(), color=False)
    assert "LIKELY MANIPULATED" in out
    assert "72" in out
    assert "fork_to_star" in out
    assert "temporal skipped" in out
    assert "\x1b[" not in out  # no ANSI when color=False
