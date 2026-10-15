from __future__ import annotations

import numpy as np
import pytest

from app.coupons import Selection, _fit_mbs
from app.model import markets as mk
from app.model.goals import score_matrix
from app.model.market_fit import MarketTarget, blend_matrix, fit_market_matrix, ms_probs
from app.sources.espn import parse_summary


def _targets_from(lh: float, la: float, rho: float) -> list[MarketTarget]:
    j = mk.build_joint(score_matrix(lh, la, rho), 0.45)
    out = []
    for key, line, names in [("ms", None, ["1", "0", "2"]), ("au", "2.5", ["Alt", "Üst"]), ("kg", None, ["Var", "Yok"])]:
        q = [mk.prob(j, mk.outcome_mask(key, line, n, j)) for n in names]
        out.append(MarketTarget(key, line, names, q))
    return out


def test_market_matrix_recovers_rates():
    fit = fit_market_matrix(_targets_from(1.9, 0.8, -0.05), -0.05, (1.2, 1.2))
    assert fit is not None
    assert fit[0] == pytest.approx(1.9, abs=0.02)
    assert fit[1] == pytest.approx(0.8, abs=0.02)
    assert fit_market_matrix([MarketTarget("au", "2.5", ["Alt", "Üst"], [0.5, 0.5])], 0.0, (1, 1)) is None


def test_matrix_blend_is_coherent_across_markets():
    sm = blend_matrix(score_matrix(1.5, 1.0, -0.05), score_matrix(1.9, 0.8, -0.05), 0.5)
    j = mk.build_joint(sm, 0.44)
    p1 = mk.prob(j, mk.outcome_mask("ms", None, "1", j))
    p1_kg = mk.prob(j, mk.outcome_mask("ms_kg", None, "1 ve Var", j)) + mk.prob(j, mk.outcome_mask("ms_kg", None, "1 ve Yok", j))
    assert p1 == pytest.approx(p1_kg, abs=1e-12)
    assert ms_probs(sm)[0] == pytest.approx(p1, abs=1e-12)
    # w=1 -> model, w=0 -> piyasa
    assert np.allclose(blend_matrix(score_matrix(1.5, 1.0, 0), score_matrix(2, 1, 0), 1.0), score_matrix(1.5, 1.0, 0))


def _summary(status: str, detail: str, home_ls: list[int], away_ls: list[int], final: tuple[int, int], events: list[dict]) -> dict:
    return {
        "header": {"competitions": [{
            "status": {"type": {"name": status, "state": "post", "completed": True, "detail": detail}},
            "competitors": [
                {"id": "1", "homeAway": "home", "score": str(final[0]), "linescores": [{"displayValue": str(v)} for v in home_ls]},
                {"id": "2", "homeAway": "away", "score": str(final[1]), "linescores": [{"displayValue": str(v)} for v in away_ls]},
            ],
        }]},
        "keyEvents": events,
        "boxscore": {"teams": []},
        "rosters": [],
    }


def test_extra_time_uses_90_minute_score():
    s = parse_summary("x", _summary("STATUS_FINAL_AET", "AET", [1, 0, 0, 1], [1, 0, 0, 0], (2, 1), []))
    assert s.extra_time
    assert (s.home_ft90, s.away_ft90) == (1, 1)
    assert (s.home_ht, s.away_ht) == (1, 1)


def test_missing_goal_events_do_not_become_0_0():
    s = parse_summary("x", _summary("STATUS_FULL_TIME", "FT", [], [], (1, 0), []))
    assert s.home_ht is None and s.away_ht is None
    assert (s.home_ft90, s.away_ft90) == (1, 0)  # uzatma yoksa nihai skor = 90 dk


def _sel(mid: str, mbs: int) -> Selection:
    return Selection(mid, 1, "a", "b", "L", "2026-01-01T00:00:00Z", "1:1:", "ms", "Maç Sonucu", "ms", None, 1, "1",
                     1.5, 0.7, 0.66, 0.68, 0.02, mbs, "yüksek")


def test_mbs_never_returns_partial_coupon():
    assert _fit_mbs([_sel("1", 3)], 3) == []
    assert len(_fit_mbs([_sel("1", 1), _sel("2", 3), _sel("3", 2)], 3)) == 3
    assert _fit_mbs([_sel("1", 3), _sel("2", 3)], 2) == []


def test_blend_validation_uses_coupon_probability():
    from app.blend import p_safe_ms

    s = {"sm_m": score_matrix(1.6, 1.0, -0.05), "sm_q": score_matrix(1.3, 1.1, -0.05), "q": [0.42, 0.28, 0.30], "y": 0}
    for w in (0.0, 0.3, 1.0):
        ps = p_safe_ms(s, w)
        matrix = ms_probs(blend_matrix(s["sm_m"], s["sm_q"], w))
        local = mk.blend(ms_probs(s["sm_m"]), s["q"], w)
        assert all(p <= min(a, b) + 1e-12 for p, a, b in zip(ps, matrix, local))
    # w=0: kupon olasılığı gerçek piyasayı aşamaz -> sahte değer yok
    assert all(p <= q + 1e-12 for p, q in zip(p_safe_ms(s, 0.0), s["q"]))
