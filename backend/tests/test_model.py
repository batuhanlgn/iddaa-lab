from __future__ import annotations

import numpy as np
import pytest

from app.matching import norm, similarity
from app.model import markets as mk
from app.model.count_model import CountData, fit_count_model
from app.model.goals import rho_bounds, score_matrix
from app.model.players import LineupEntry, PlayerRates, TeamPlayerContext
from app.model.simulate import TeamSimInput, sample_shots, simulate_match
from app.sources.espn import norm_iso, parse_clock_minute, pos_group
from app.sources.iddaa import parse_events


def test_score_matrix_sums_to_one_and_respects_rho_bounds():
    for lh, la, rho in [(1.4, 1.1, -0.1), (3.5, 0.4, 0.3), (0.2, 0.2, -5.0)]:
        m = score_matrix(lh, la, rho)
        assert m.shape == (11, 11)
        assert np.all(m >= 0)
        assert abs(m.sum() - 1) < 1e-9
    lo, hi = rho_bounds(2.0, 1.5)
    assert lo == pytest.approx(-0.5)
    assert hi == pytest.approx(1 / 3)


def test_market_masks_partition_and_consistency():
    j = mk.build_joint(score_matrix(1.6, 1.0, -0.05), 0.44)
    assert abs(j.P.sum() - 1) < 1e-9
    for key, sov, names in mk.STANDARD_MARKETS:
        total = sum(mk.prob(j, mk.outcome_mask(key, sov, n, j)) for n in names)
        if key == "cs":
            assert total == pytest.approx(2.0, abs=1e-9)  # çifte şans sonuçları örtüşür
        else:
            assert total == pytest.approx(1.0, abs=1e-9), key
    p_ms = [mk.prob(j, mk.outcome_mask("ms", None, n, j)) for n in ("1", "0", "2")]
    p_iyms_ft1 = sum(mk.prob(j, mk.outcome_mask("iyms", None, f"{h}/1", j)) for h in ("1", "0", "2"))
    assert p_iyms_ft1 == pytest.approx(p_ms[0], abs=1e-9)
    # handikap 0 = maç sonucu
    p_h0 = mk.prob(j, mk.outcome_mask("hnd", "0", "1", j))
    assert p_h0 == pytest.approx(p_ms[0], abs=1e-9)
    # binom inceltme FT dağılımını korur
    ft_marg = j.P.sum(axis=(2, 3))
    assert np.allclose(ft_marg, score_matrix(1.6, 1.0, -0.05))


def test_unknown_outcome_name_is_not_priced():
    j = mk.build_joint(score_matrix(1.2, 1.2, 0.0), 0.45)
    assert mk.outcome_mask("ms", None, "X", j) is None
    assert mk.outcome_mask("au", None, "Üst", j) is None  # çizgi yoksa fiyatlanmaz


def test_devig_and_blend_normalize():
    q = mk.devig([1.21, 5.39, 8.54])
    assert sum(q) == pytest.approx(1.0)
    assert mk.margin([2.0, 2.0]) == pytest.approx(0.0)
    b = mk.blend([0.5, 0.3, 0.2], q, 0.5)
    assert sum(b) == pytest.approx(1.0)
    assert mk.blend([0.5, 0.3, 0.2], q, 1.0) == pytest.approx([0.5, 0.3, 0.2])


def test_corner_probs_complement_on_half_line():
    alt, ust = mk.corner_over_prob(5.2, 4.4, 20.0, 9.5)
    assert alt + ust == pytest.approx(1.0, abs=1e-6)


def test_count_model_recovers_strength_order():
    rng = np.random.default_rng(0)
    teams = [f"t{i}" for i in range(6)]
    att_true = np.array([0.5, 0.3, 0.1, -0.1, -0.3, -0.5])
    hi, ai, yh, ya = [], [], [], []
    for _ in range(40):
        for h in range(6):
            for a in range(6):
                if h == a:
                    continue
                hi.append(h); ai.append(a)
                yh.append(rng.poisson(np.exp(0.3 + 0.25 + att_true[h] + att_true[a] * 0.0)))
                ya.append(rng.poisson(np.exp(0.3 + att_true[a])))
    n = len(hi)
    data = CountData(np.array(hi), np.array(ai), np.zeros(n, dtype=np.int64), np.zeros(n), np.array(yh, float),
                     np.array(ya, float), np.ones(n), teams, ["L"] * 6, ["L"], [False])
    m = fit_count_model(data, "L", sigma=1.0, tau=1.0)
    assert m.converged
    assert list(np.argsort(-m.att)) == [0, 1, 2, 3, 4, 5]
    # Dengeli fikstürde ev avantajı MLE'si = ampirik log(ev ort. / dep ort.)
    emp = float(np.log(np.mean(yh) / np.mean(ya)))
    assert m.home[0] == pytest.approx(emp, abs=0.02)


def test_shot_sampler_is_consistent_with_auxiliary_model():
    """Skor yardımcı modelin kendi marjinalinden gelirse, koşullu örnekleme koşulsuz NB şut ortalamasını geri vermeli."""
    rng = np.random.default_rng(3)
    n, mu, k, u, v, om = 200_000, 13.0, 12.0, 0.34, 0.31, 0.04
    lam = rng.gamma(k, mu / k, size=n)
    f = rng.poisson(lam * u * v)
    c = np.minimum(f + rng.poisson(om, size=n), 10)
    S, T, F = sample_shots(c, mu, k, np.full(n, u), np.full(n, v), om, rng)
    assert np.all(F <= c) and np.all(F <= T) and np.all(T <= S)
    assert S.mean() == pytest.approx(mu, rel=0.02)
    assert T.mean() == pytest.approx(mu * u, rel=0.03)
    # yüksek skorlu senaryolarda şut sayısı artar (skora koşullama çalışıyor)
    S3, _, _ = sample_shots(np.full(20000, 3), mu, k, np.full(20000, u), np.full(20000, v), om, rng)
    S0, _, _ = sample_shots(np.full(20000, 0), mu, k, np.full(20000, u), np.full(20000, v), om, rng)
    assert S3.mean() > S0.mean() + 2


def _ctx(team: str, n: int = 16) -> TeamPlayerContext:
    lineup, rates = [], {}
    for i in range(n):
        g = "G" if i == 0 else ("D" if i < 6 else ("M" if i < 11 else "F"))
        pid = f"{team}{i}"
        lineup.append(LineupEntry(pid, pid, g, g, 0.9 if i < 11 else 0.2, 0.6, [90, 75, 80] if g == "F" else [], [70, 60, 75]))
        rates[pid] = PlayerRates(pid, pid, g, g, {"G": 0.01, "D": 0.6, "M": 1.2, "F": 2.4}[g], 0.35, 0.3, 900, 30)
    return TeamPlayerContext(team, lineup, rates, 10, False, True, [])


def test_simulation_invariants():
    sm = score_matrix(1.5, 1.1, -0.05)
    out = simulate_match(sm, TeamSimInput("home", "h", 14.0, 12.0, 0.04, _ctx("h")),
                         TeamSimInput("away", "a", 11.0, 12.0, 0.04, _ctx("a")), 4000, 5, 42)
    for side in ("home", "away"):
        t = out["teams"][side]
        assert t["players_available"]
        assert t["shots"]["mean"] >= t["shots_on_target"]["mean"]
        for p in t["players"]:
            assert 0 <= p["p_goal"] <= p["p_sot_1"] + 1e-9 <= p["p_shots_1"] + 2e-9
            assert p["exp_minutes"] <= 90
        starters = sum(p["p_start"] for p in t["players"])
        assert starters == pytest.approx(11, abs=0.05)
        # her senaryoda sahada tam 11 kişi: ortalama oynanan dakika toplamı 11*90
        assert sum(p["exp_minutes"] for p in t["players"]) == pytest.approx(990, abs=1.0)
    for sc in out["scenarios"]:
        goals_h = sum(1 for e in sc["events"] if e["side"] == "home" and e["type"] in ("goal", "own_goal_for"))
        goals_a = sum(1 for e in sc["events"] if e["side"] == "away" and e["type"] in ("goal", "own_goal_for"))
        assert [goals_h, goals_a] == sc["score"]
        assert sc["stats"]["home"]["sot"] <= sc["stats"]["home"]["shots"]
    # Skor dağılımı korunur: simüle edilen ev golü ortalaması DC beklentisine yakın
    exp_h = float((sm.sum(axis=1) * np.arange(11)).sum())
    sim_h = np.mean([s["score"][0] for s in out["scenarios"]])
    assert abs(sim_h - exp_h) < 3  # yalnızca 5 senaryo: kaba kontrol


def test_parsers():
    assert parse_clock_minute("45'+7'") == 45
    assert parse_clock_minute("68'") == 68
    assert parse_clock_minute(None) is None
    assert norm_iso("2026-10-17T11:30Z") == "2026-10-17T11:30:00Z"
    assert pos_group("G") == "G" and pos_group("CD-L") == "D" and pos_group("AM") == "M" and pos_group("CF-R") == "F"
    payload = {"isSuccess": True, "data": {"events": [{
        "i": 1, "sid": 1, "d": 1792252800, "hn": "Fenerbahçe", "an": "Alanyaspor", "ci": 584, "mbc": 1, "il": False,
        "m": [{"t": 1, "st": 1, "mbc": 1, "o": [{"no": 1, "odd": 1.21, "n": "1"}, {"no": 2, "odd": 5.39, "n": "0"}, {"no": 3, "odd": 8.54, "n": "2"}]},
              {"t": 2, "st": 999, "o": [{"no": 1, "odd": 2.0, "n": "x"}]}],
    }]}}
    ev = parse_events(payload)
    assert len(ev) == 1 and len(ev[0].markets) == 1
    assert ev[0].markets[0].market_key == "1:1:"
    assert ev[0].kickoff_utc.endswith(":00Z")


def test_team_name_matching():
    assert norm("Fenerbahçe") == "fenerbahce"
    assert similarity("Fenerbahçe", "Fenerbahce") == 1.0
    assert similarity("Başakşehir", "Istanbul Basaksehir") >= 0.8
    assert similarity("Galatasaray", "Galatasaray SK") >= 0.85
    assert similarity("Kızıl Yıldız", "Crvena Zvezda") >= 0.5
    assert similarity("Arsenal", "Chelsea") < 0.5
