from __future__ import annotations

import itertools

import numpy as np
import pytest

from app.coupons import Selection, _at_least, combine_system
from app.model.goals import calibrate_matrix, score_matrix, score_matrix_cal
from app.model.pipeline import apply_player_calibration, platt


def _sel(mid: str, odd: float, p: float, mbs: int = 1) -> Selection:
    return Selection(mid, 1, "a", "b", "L", "2026-01-01T00:00:00Z", "1:1:", "ms", "Maç Sonucu", "ms", None, 1, "1",
                     odd, p, p, p, p * odd - 1, mbs, "yüksek")


def test_at_least_matches_enumeration():
    ps = [0.6, 0.7, 0.55, 0.8]
    for k in range(5):
        brute = 0.0
        for outcome in itertools.product([0, 1], repeat=4):
            if sum(outcome) >= k:
                brute += np.prod([p if o else 1 - p for p, o in zip(ps, outcome)])
        assert _at_least(ps, k) == pytest.approx(brute)


def test_system_coupon_math():
    sels = [_sel("1", 1.8, 0.6), _sel("2", 1.6, 0.65), _sel("3", 2.0, 0.55)]
    r = combine_system(sels, 2)
    assert r["system"]["cost"] == 3
    assert len(r["system"]["combos"]) == 3
    exp = sum(np.prod([sels[i].odd * sels[i].p_blend for i in c]) for c in itertools.combinations(range(3), 2))
    assert r["system"]["expected_return"] == pytest.approx(exp)
    assert r["ev"] == pytest.approx(exp / 3 - 1)
    assert r["prob"] == pytest.approx(_at_least([0.6, 0.65, 0.55], 2))
    assert r["mbs_ok"]
    assert not combine_system([_sel("1", 1.8, 0.6, mbs=3), _sel("2", 1.6, 0.65), _sel("3", 2.0, 0.55)], 2)["mbs_ok"]


def test_score_calibration_identity_and_effect():
    sm = score_matrix(1.4, 1.1, -0.05)
    assert np.allclose(calibrate_matrix(sm, 1.0), sm)
    assert np.allclose(score_matrix_cal(1.4, 1.1, -0.05, 1.0, 1.0), sm)
    flat = calibrate_matrix(sm, 0.8)
    assert flat.sum() == pytest.approx(1.0)
    assert flat.max() < sm.max()  # t<1 dağılımı yayar
    more_goals = score_matrix_cal(1.4, 1.1, -0.05, 1.0, 1.1)
    k = np.arange(11)
    assert (more_goals.sum(1) * k).sum() > (sm.sum(1) * k).sum()


def test_platt_and_player_calibration_keep_order():
    assert platt(0.3, 0.0, 1.0) == pytest.approx(0.3, abs=1e-9)
    sim = {"teams": {s: {"players": [{"p_sot_1": 0.5, "p_sot_2": 0.2, "p_shots_1": 0.7, "p_shots_2": 0.45, "p_shots_3": 0.25,
                                      "p_goal": 0.2, "p_goal_2": 0.05, "p_play": 0.9}],
                         "shots_on_target": {"at_least": {"3": 0.6, "4": 0.45, "5": 0.3}}} for s in ("home", "away")}}
    cal = {"p_goal": {"a": 1.5, "b": 1.0, "use": True}, "team_sot": {"a": 0.4, "b": 1.0, "use": True}}
    apply_player_calibration(sim, cal)
    pl = sim["teams"]["home"]["players"][0]
    assert pl["p_goal"] <= pl["p_sot_1"] <= pl["p_shots_1"]
    al = sim["teams"]["home"]["shots_on_target"]["at_least"]
    assert al["3"] >= al["4"] >= al["5"]


def test_clv_uses_last_odds_before_kickoff():
    import sqlite3

    from app.db import SCHEMA
    from app.tracking import clv

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    rows = [
        (9, "1:1:", 1, 2.10, "2026-10-10T10:00:00Z"), (9, "1:1:", 2, 3.30, "2026-10-10T10:00:00Z"), (9, "1:1:", 3, 3.60, "2026-10-10T10:00:00Z"),
        (9, "1:1:", 1, 1.90, "2026-10-11T17:00:00Z"),  # kapanışa doğru düştü
        (9, "1:1:", 1, 1.70, "2026-10-11T19:30:00Z"),  # maç başladıktan sonra: sayılmaz
    ]
    con.executemany("INSERT INTO odds_history VALUES(?,?,?,?,?)", rows)
    r = clv(con, 9, "1:1:", 1, 2.10, "2026-10-11T19:00:00Z")
    assert r is not None
    assert r["close_odd"] == pytest.approx(1.90)
    assert r["clv_odds"] == pytest.approx(2.10 / 1.90 - 1)
    inv = [1 / 1.90, 1 / 3.30, 1 / 3.60]
    assert r["ev_vs_close"] == pytest.approx(inv[0] / sum(inv) * 2.10 - 1)
    assert clv(con, 9, "oyuncu:1:sot1", 0, 1.5, "2026-10-11T19:00:00Z") is None
