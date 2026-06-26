from fakestar.models import Signal, Verdict


def test_signal_defaults_caveat_none():
    s = Signal(
        name="fork_to_star", value=0.02, baseline=0.16, threshold=0.05,
        weight=30, tripped=True, severity=0.6, detail="low forks",
    )
    assert s.caveat is None
    assert s.tripped is True


def test_verdict_holds_signals():
    s = Signal("ghost_pct", 0.3, 0.01, 0.10, 25, True, 1.0, "many ghosts")
    v = Verdict(score=70, band="LIKELY MANIPULATED", signals=[s],
                sample_size=150, repo="o/r", notes=["temporal skipped"])
    assert v.signals[0].name == "ghost_pct"
    assert v.notes == ["temporal skipped"]
