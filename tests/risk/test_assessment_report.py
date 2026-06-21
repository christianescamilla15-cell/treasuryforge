"""The decision-grade assessment report + its named verdicts (his three cases)."""

from __future__ import annotations

from treasuryforge.risk import assess_and_report


def _series(mu_per, n=400, vol=0.01, seed=0):
    import random
    rng = random.Random(seed)
    return [mu_per + rng.gauss(0, vol) for _ in range(n)]


def test_reject_no_edge():
    r = assess_and_report("neg", _series(-0.001), dsr=0.9, paths=1500)
    assert r.verdict == "REJECT: NO_EDGE" and not r.accepted


def test_reject_edge_not_reliable_on_low_dsr():
    # positive edge but DSR below the minimum -> not trustworthy enough to deploy
    r = assess_and_report("lowdsr", _series(0.0008, vol=0.005), dsr=0.43,
                          dsr_min=0.60, paths=1500)
    assert r.verdict == "REJECT: EDGE_IS_NOT_RELIABLE"


def test_reject_path_too_dangerous_on_ruin():
    # high DSR (passes reliability), high-Kelly scalp pushed to a high cap so the
    # sized f is large -> under stress the ruin/drawdown gates blow even with a real edge
    scalp = [0.003 if (i % 20) < 11 else -0.003 for i in range(300)]
    r = assess_and_report("danger", scalp, dsr=0.95, dsr_min=0.60, hard_cap=12.0,
                          max_p_ruin=0.01, max_expected_drawdown=0.15, paths=1500)
    assert r.verdict == "REJECT: PATH_TOO_DANGEROUS"


def test_accept_deploy_small_when_all_pass():
    # real edge, trustworthy DSR, low vol, gentle assumptions -> accept, but sized small
    r = assess_and_report("clean", _series(0.0006, vol=0.004), dsr=0.80,
                          dsr_min=0.60, hard_cap=2.0, max_p_ruin=0.30,
                          max_expected_drawdown=0.50, adverse_shift=0.0,
                          tail_shock_prob=0.0, paths=1500)
    assert r.verdict == "ACCEPT: DEPLOY_SMALL"
    assert r.sizing["dsr_pct"] < 1.0          # never full Kelly


def test_render_has_all_sections():
    r = assess_and_report("x", _series(0.0006), dsr=0.7, cv_folds=[1.2, -0.3, 0.8], paths=1000)
    out = r.render()
    for section in ("RAW METRICS", "VALIDATION", "SIZING", "RISK", "VERDICT"):
        assert section in out
    assert "UNSTABLE" in out                  # a negative fold flags instability
