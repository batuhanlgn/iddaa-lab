from __future__ import annotations

import itertools
import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pytest

from app import db
from app import sportoto_crowd as sc
from app.sources import totokazan as tk
from app.sportoto import OUTCOMES, hit_distribution, toto_view, update_coupon, winning_columns
from app.sportoto_crowd import (
    MASKS, Market, PrizeModel, check_week, common_columns, crowd_models, estimate_market, map_week, mask_of,
    optimize_crowd, sel_of, week_n_eff,
)


def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    db.migrate(con)
    return con


def _rnd3(rng: np.random.Generator) -> dict[str, float]:
    return dict(zip(OUTCOMES, map(float, rng.dirichlet([2.0, 2.0, 2.0]))))


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- beklenen ikramiye: kaba kuvvetle karşılaştırma

def _small_case(seed: int = 3, n_free: int = 4) -> tuple[list[dict[str, float]], list[dict[str, float]], list[int | None], Market]:
    """15 maçtan n_free'si belirsiz, kalanların sonucu kesin: tüm sonuçlar (3^n_free) sayılabilir."""
    rng = np.random.default_rng(seed)
    probs: list[dict[str, float]] = []
    fixed: list[int | None] = []
    for j in range(15):
        if j < 15 - n_free:
            o = j % 3
            probs.append({k: (1.0 if i == o else 0.0) for i, k in enumerate(OUTCOMES)})
            fixed.append(o)
        else:
            probs.append(_rnd3(rng))
            fixed.append(None)
    crowd = [_rnd3(rng) for _ in range(15)]
    market = Market(n_columns=2e6, pools={12: 3e7, 13: 2.4e7, 14: 2.4e7, 15: 4e7}, carry=0.0,
                    pb_floor={12: 1e-4, 13: 1e-6, 14: 1e-8, 15: 0.0})
    return probs, crowd, fixed, market


def _outcomes(fixed: list[int | None]) -> np.ndarray:
    free = [j for j, f in enumerate(fixed) if f is None]
    rows = []
    for combo in itertools.product(range(3), repeat=len(free)):
        y = [f if f is not None else 0 for f in fixed]
        for j, c in zip(free, combo):
            y[j] = c
        rows.append(y)
    return np.array(rows)


def _brute(masks: list[int], probs: list[dict[str, float]], crowd: list[dict[str, float]], market: Market,
           ys: np.ndarray) -> float:
    total = 0.0
    for y in ys:
        w = math.prod(probs[j][OUTCOMES[y[j]]] for j in range(15))
        if w == 0:
            continue
        won = winning_columns([sel_of(m) for m in masks], [OUTCOMES[v] for v in y])
        d = hit_distribution([crowd[j][OUTCOMES[y[j]]] / sum(crowd[j].values()) for j in range(15)])
        for k, n in won.items():
            lam = market.n_columns * max(d[k], market.pb_floor.get(k, 0.0))
            h = (1 - math.exp(-lam)) / lam if lam > 1e-12 else 1.0
            total += w * n * market.pools[k] * h
    return total


def _covering_masks(rng: np.random.Generator, fixed: list[int | None], max_cols: int = 300) -> list[int]:
    masks = [int(rng.choice(MASKS)) for _ in range(15)]
    for j, f in enumerate(fixed):
        if f is not None:
            masks[j] |= 1 << f
    while math.prod(bin(m).count("1") for m in masks) > max_cols:
        j = int(rng.integers(15))
        masks[j] = (1 << fixed[j]) if fixed[j] is not None else int(rng.choice([1, 2, 4]))  # type: ignore[operator]
    return masks


def test_expected_prize_matches_brute_force_and_incremental_moves():
    probs, crowd, fixed, market = _small_case()
    ys = _outcomes(fixed)
    model = PrizeModel.from_outcomes(ys, probs, crowd, market)
    rng = np.random.default_rng(11)
    for _ in range(4):
        masks = _covering_masks(rng, fixed)
        exact = _brute(masks, probs, crowd, market, ys)
        assert exact > 0
        assert model.value(masks) == pytest.approx(exact, rel=1e-9)
        assert sum(model.by_tier(masks).values()) == pytest.approx(exact, rel=1e-9)
        # tek maç ve iki maç değişikliği: polinom bölmesiyle hesaplanan değer = baştan hesap
        p = model.poly(masks)
        j, l = 12, 13
        rest = model.divide(p, j, masks[j])
        single = model.single_values(rest, j)
        pair = model.pair_values(model.divide(rest, l, masks[l]), j, l)
        for mi, m in enumerate(MASKS):
            alt = list(masks)
            alt[j] = m
            assert single[mi] == pytest.approx(_brute(alt, probs, crowd, market, ys), rel=1e-9, abs=1e-6)
        alt = list(masks)
        alt[j], alt[l] = 3, 6
        assert pair[MASKS.index(3), MASKS.index(6)] == pytest.approx(model.value(alt), rel=1e-9)


def test_importance_sampling_converges_to_exact():
    probs, crowd, fixed, market = _small_case(seed=5)
    ys = _outcomes(fixed)
    exact_model = PrizeModel.from_outcomes(ys, probs, crowd, market)
    masks = _covering_masks(np.random.default_rng(2), fixed)
    exact = exact_model.value(masks)
    mc = PrizeModel.from_samples(probs, crowd, market, samples=60000, seed=9)
    est, se = mc.estimate(masks)
    assert sum(est.values()) == pytest.approx(exact, rel=0.05)
    assert se > 0


def test_kupon3_has_no_common_columns_and_respects_budget(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sc, "EVAL_SAMPLES", 6000)
    rng = np.random.default_rng(21)
    probs = [_rnd3(rng) for _ in range(15)]
    crowd = [_rnd3(rng) for _ in range(15)]
    market = Market(n_columns=1.5e7, pools={12: 2.7e7, 13: 2.2e7, 14: 2.2e7, 15: 3.8e7}, carry=0.0,
                    pb_floor={12: 9e-6, 13: 5e-7, 14: 2e-8, 15: 3e-10})
    from app.sportoto import optimize

    base = optimize(probs, 300)
    searches, evaluator = crowd_models(probs, crowd, market, seed=1, samples=4000)
    s2, v2, s3, v3 = optimize_crowd(searches, evaluator, probs, crowd, base, 300)
    assert common_columns(s2, s3) == 0
    assert any(a & b == 0 for a, b in zip(s2, s3))
    for s in (s2, s3):
        assert math.prod(bin(m).count("1") for m in s) <= 300
    # Kupon 2, Kupon 1'den kötü olamaz (aynı bağımsız örneklemde)
    assert v2 >= evaluator.value([mask_of(s) for s in base]) - 1e-9
    assert v2 == pytest.approx(evaluator.value(s2)) and v3 == pytest.approx(evaluator.value(s3))


def test_common_columns_counts_shared_columns():
    a = [mask_of(["1", "0"])] + [mask_of(["1"])] * 14
    b = [mask_of(["0", "2"])] + [mask_of(["1"])] * 14
    c = [mask_of(["2"])] + [mask_of(["1"])] * 14
    assert common_columns(a, b) == 1 and common_columns(a, c) == 0


# ---------------------------------------------------------------- totokazan ayrıştırma ve eşleştirme

def _tk_payload(fixtures: list[tuple[str, str, str | None]], status: str = "settled") -> dict[str, Any]:
    return {"data": {"week": {"id": 39, "name": "2026/2027 9. Hafta", "status": status, "column_price": "10.00",
                              "created_at": "2026-10-06 00:15:45",
                              "stextra_json": {"sourceW": 1536, "kolonOynatildi": 1359420, "fetchedAt": "2026-10-12T20:45:17Z"}},
                     "fixtures": [{"position": i + 1, "home": h, "away": a, "result": r,
                                   "pct_json": {"1": 50, "X": 30, "2": 20}, "odds_json": {"1": 1.9, "X": 3.3, "2": 4.0}}
                                  for i, (h, a, r) in enumerate(fixtures)]}}


NAMES = [("Galatasaray", "Kasımpaşa"), ("Gençlerbirliği", "Amed Sportif Faaliyetler"), ("Corendon Alanyaspor", "Erzurumspor FK"),
         ("Samsunspor", "Trabzonspor"), ("Çaykur Rizespor", "Fenerbahçe"), ("Tümosan Konyaspor", "İstanbul Başakşehir"),
         ("Gaziantep FK", "Arca Çorum FK"), ("Beşiktaş", "Kocaelispor"), ("Eyüpspor", "Göztepe"), ("Augsburg", "Bayern Münih"),
         ("RB Leipzig", "Eintracht Frankfurt"), ("Manchester Utd.", "T. Hotspur"), ("Liverpool", "M. City"),
         ("Real Madrid", "Villarreal"), ("Como", "Roma")]
OURS = ["Galatasaray A.Ş. - Kasımpaşa A.Ş.", "Gençlerbirliği - Amed Sportif Faaliyetler", "Alanyaspor - Erzurumspor FK",
        "Samsunspor - Trabzonspor A.Ş.", "Çaykur Rizespor A.Ş. - Fenerbahçe A.Ş.", "Konyaspor - Başakşehir FK",
        "Gaziantep FK - Çorum FK", "Beşiktaş A.Ş. - Kocaelispor", "Eyüpspor - Göztepe", "Augsburg - Bayern Münih",
        "RB Leipzig - Eintracht Frankfurt", "Manchester United - Tottenham", "Liverpool - Manchester City",
        "Real Madrid - Villarreal", "Como - Roma"]
WINNERS = ["1", "0", "0", "2", "2", "0", "2", "1", "2", "0", "1", "0", "2", "1", "0"]


def _events(names: list[str], winners: list[str | None]) -> list[dict[str, Any]]:
    return [{"event_no": i + 1, "event_name": n, "winner": w} for i, (n, w) in enumerate(zip(names, winners))]


def test_totokazan_parse_week():
    p = _tk_payload([(h, a, {"1": "1", "0": "X", "2": "2"}[w]) for (h, a), w in zip(NAMES, WINNERS)])
    p["data"]["fixtures"][1]["home"] = "Borussia M&#x27;gladbach"
    w = tk.parse_week(p)
    assert w is not None and w.id == 39 and w.source_w == 1536 and w.platform_columns == 1359420
    assert w.fixtures[1].home == "Borussia M'gladbach"
    assert w.fixtures[1].result == "0"                           # "X" -> "0"
    assert w.fixtures[0].pct == pytest.approx({"1": 0.5, "0": 0.3, "2": 0.2})
    assert w.fixtures[0].odds == {"1": 1.9, "0": 3.3, "2": 4.0}
    assert tk.parse_week({"data": {}}) is None
    assert [it["id"] for it in tk.parse_list({"data": {"items": [{"id": 40}, {"x": 1}]}})] == [40]


def test_check_week_accepts_abbreviations_and_rejects_misalignment():
    tkw = tk.parse_week(_tk_payload([(h, a, {"1": "1", "0": "X", "2": "2"}[w]) for (h, a), w in zip(NAMES, WINNERS)]))
    assert tkw is not None
    ok = check_week(tkw, _events(OURS, WINNERS))
    assert ok.ok and ok.n_names == 15
    assert check_week(tkw, _events(OURS, [None] * 15)).ok     # açık hafta: sonuç yok
    shifted = OURS[1:] + OURS[:1]                               # sıra kaydı
    assert not check_week(tkw, _events(shifted, WINNERS)).ok
    clash = list(WINNERS)
    clash[0] = "2"
    bad = check_week(tkw, _events(OURS, clash))
    assert not bad.ok and "sonuç" in (bad.reason or "")
    no_pct = _tk_payload([(h, a, None) for h, a in NAMES])
    no_pct["data"]["fixtures"][3]["pct_json"] = None
    tkw2 = tk.parse_week(no_pct)
    assert tkw2 is not None and not check_week(tkw2, _events(OURS, [None] * 15)).ok


def _add_hist_week(con: sqlite3.Connection, c: int, end: datetime, names: list[str], winners: list[str],
                   dividends: list[dict[str, Any]] | None = None) -> None:
    con.execute("INSERT INTO toto_hist_weeks VALUES(?,?,?,?,?,'settled',?)",
                (c, f"hafta {c}", _iso(end - timedelta(days=5)), _iso(end), json.dumps(dividends or []), _iso(end)))
    for i, (n, w) in enumerate(zip(names, winners)):
        con.execute("INSERT INTO toto_hist_events VALUES(?,?,?,?,?,?,?)",
                    (c, i + 1, n, "SÜPL", _iso(end + timedelta(hours=1 + i)), "1:0", w))


def test_map_week_picks_the_consistent_cycle_in_date_window():
    con = _mem_db()
    end = datetime(2026, 10, 9, 16, 55, tzinfo=timezone.utc)
    _add_hist_week(con, 361, end, OURS, WINNERS)
    _add_hist_week(con, 360, end - timedelta(days=7), OURS[::-1], WINNERS)
    tkw = tk.parse_week(_tk_payload([(h, a, {"1": "1", "0": "X", "2": "2"}[w]) for (h, a), w in zip(NAMES, WINNERS)]))
    assert tkw is not None
    cands = sc._candidates(con, tkw.created_at)
    assert 361 in cands
    cycle, chk = map_week(con, tkw, [360, 361])
    assert cycle == 361 and chk.ok
    cycle, chk = map_week(con, tkw, [360])
    assert cycle is None and not chk.ok


# ---------------------------------------------------------------- N / havuz tahmini: sızıntısız

def _divs(w15: int, pool15: float, w12: int = 20000) -> list[dict[str, Any]]:
    return [{"tier": 15, "winners": w15, "amount": pool15 / w15 if w15 else 0.0, "pool": pool15, "pool_known": True},
            {"tier": 14, "winners": 500, "amount": 40000.0, "pool": 2e7, "pool_known": True},
            {"tier": 13, "winners": 5000, "amount": 4000.0, "pool": 2e7, "pool_known": True},
            {"tier": 12, "winners": w12, "amount": 2.5e7 / w12, "pool": 2.5e7, "pool_known": True}]


def _crowd_week(con: sqlite3.Connection, c: int, pct: tuple[float, float, float] = (0.5, 0.3, 0.2)) -> None:
    for e in range(1, 16):
        con.execute("INSERT INTO toto_crowd VALUES(?,?,?,?,?,NULL,NULL,NULL,'x')", (c, e, *pct))
    con.execute("INSERT INTO toto_crowd_weeks VALUES(?,?,?,'settled',NULL,15,NULL,'x')", (c, c, f"tk {c}"))


def _history(con: sqlite3.Connection) -> datetime:
    base = datetime(2026, 9, 4, 16, 55, tzinfo=timezone.utc)
    for i, c in enumerate(range(350, 356)):
        end = base + timedelta(days=7 * i)
        # 355: 15 bilen yok -> 356'ya devir
        _add_hist_week(con, c, end, OURS, WINNERS, _divs(0 if c == 355 else 3, 3.5e7))
        _crowd_week(con, c)
    return base + timedelta(days=7 * 6)


def test_estimate_market_uses_only_previous_finished_weeks_and_carry():
    con = _mem_db()
    end356 = _history(con)
    as_of = end356 - timedelta(minutes=60)
    m, why = estimate_market(con, 356, as_of, 10.0)
    assert why is None and m is not None
    assert [b["cycle_no"] for b in m.basis] == [355, 354, 353, 352, 351, 350]
    assert m.carry == pytest.approx(3.5e7)                       # 355'te 15 bilen yok: havuzun tamamı devreder
    assert m.pools[15] == pytest.approx(3.5e7 + 3.5e7)           # taban medyanı (devirsiz) + devir
    assert m.pools[12] == pytest.approx(2.5e7)
    # her hafta aynı kalabalık + sonuç -> N_t aynı: Σ kazanan / Σ PB
    winners_by = [{"1": 0.5, "0": 0.3, "2": 0.2}[w] for w in WINNERS]
    d = hit_distribution(winners_by)
    assert m.n_columns == pytest.approx((3 + 500 + 5000 + 20000) / sum(d[k] for k in (12, 13, 14, 15)))
    assert m.blend_a == sc.BLEND_PRIOR and m.blend_weeks == 0    # PIT için geçmiş olasılık yok
    # sonradan eklenen haftalar (356 ve sonrası) tahmini değiştirmez
    _add_hist_week(con, 356, end356, OURS, WINNERS, _divs(1, 9e9, w12=1))
    _crowd_week(con, 356, (0.9, 0.05, 0.05))
    m2, _ = estimate_market(con, 356, as_of, 10.0)
    assert m2 is not None and m2.n_columns == pytest.approx(m.n_columns) and m2.pools == pytest.approx(m.pools)
    # kilit anında sonucu belli olmayan önceki hafta kullanılmaz
    m3, _ = estimate_market(con, 356, datetime(2026, 10, 2, 17, 30, tzinfo=timezone.utc), 10.0)
    assert m3 is not None and 355 not in [b["cycle_no"] for b in m3.basis]
    assert m3.carry == 0.0 and any("devir 0" in n for n in m3.notes)
    # geçmiş yetersizse kalabalık kuponu yok
    m4, why4 = estimate_market(con, 352, datetime(2026, 9, 18, 15, 55, tzinfo=timezone.utc), 10.0)
    assert m4 is None and why4 is not None and "en az" in why4


def test_week_n_eff():
    q = [1.0] * 15
    assert week_n_eff(q, {15: 7, 14: 0, 13: 0, 12: 0}) == pytest.approx(7.0)
    assert week_n_eff([0.0] * 15, {15: 1}) is None


# ---------------------------------------------------------------- canlı kupon kurulumu ve göç

def _open_week(con: sqlite3.Connection, hours_to_close: float = 30.0) -> None:
    end = datetime.now(timezone.utc) + timedelta(hours=hours_to_close)
    con.execute("INSERT INTO toto_weeks(cycle_no, program_name, payin_begin_utc, payin_end_utc, fetched_at) VALUES(356,'p',?,?,?)",
                (_iso(end - timedelta(days=5)), _iso(end), _iso(end)))
    for i, n in enumerate(OURS):
        con.execute("INSERT INTO toto_events(cycle_no, event_no, event_name, competition, kickoff_utc) VALUES(356,?,?,?,?)",
                    (i + 1, n, "SÜPL", _iso(end + timedelta(hours=1 + i))))


def test_update_coupon_without_crowd_builds_only_kupon1():
    con = _mem_db()
    _open_week(con)
    with db.tx(con):
        msg = update_coupon(con, 356)
    assert "kalabalık kuponu yok" in msg
    v = toto_view(con)
    kinds = {s["kind"]: s for s in v["coupons"]}
    assert kinds["olasilik"]["coupon"] is not None
    assert kinds["kalabalik"]["coupon"] is None and "kalabalık" in (kinds["kalabalik"]["reason"] or "").lower()
    assert kinds["kalabalik_2"]["coupon"] is None
    assert v["crowd"]["available"] is False
    assert v["weekly_cost"] == kinds["olasilik"]["coupon"]["cost"]


def test_update_coupon_with_crowd_builds_three_disjoint_coupons(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sc, "EVAL_SAMPLES", 4000)
    monkeypatch.setattr(sc, "MC_SAMPLES", 3000)
    con = _mem_db()
    _history(con)
    _open_week(con, hours_to_close=30.0)
    rng = np.random.default_rng(4)
    for e in range(1, 16):
        r = _rnd3(rng)
        con.execute("INSERT INTO toto_crowd VALUES(356,?,?,?,?,NULL,NULL,NULL,'2026-10-16T10:00:00Z')", (e, r["1"], r["0"], r["2"]))
    con.execute("INSERT INTO toto_crowd_weeks VALUES(356, 40, 'tk', 'open', NULL, 15, NULL, 'x')")
    # geçmiş haftaların sonuçları kilitten önce belli olsun diye kilit anı = şimdi + 30 sa − 60 dk (tarihler geçmişte)
    with db.tx(con):
        update_coupon(con, 356)
    v = toto_view(con)
    cs = {s["kind"]: s["coupon"] for s in v["coupons"]}
    assert all(cs[k] is not None for k in ("olasilik", "kalabalik", "kalabalik_2"))
    s2 = [mask_of(e["picks"]) for e in cs["kalabalik"]["events"]]
    s3 = [mask_of(e["picks"]) for e in cs["kalabalik_2"]["events"]]
    assert common_columns(s2, s3) == 0 and cs["kalabalik_2"]["common_columns_with_kalabalik"] == 0
    assert all(c["cost"] <= 3000 for c in cs.values())
    assert v["weekly_cost"] <= 9000
    assert cs["kalabalik"]["expected_prize"] is not None and cs["kalabalik"]["events"][0]["crowd"] is not None
    assert cs["olasilik"]["crowd_status"] == {"available": True, "reason": None}


def test_migration_moves_old_single_coupon_as_olasilik():
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    # Eski şema: yalnız tek kupon tablosu
    con.executescript("""
        CREATE TABLE toto_weeks (cycle_no INTEGER PRIMARY KEY, program_name TEXT, payin_begin_utc TEXT,
            payin_end_utc TEXT NOT NULL, dividends TEXT, status TEXT NOT NULL DEFAULT 'open', fetched_at TEXT NOT NULL);
        CREATE TABLE toto_coupons (cycle_no INTEGER PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            locked INTEGER NOT NULL DEFAULT 0, budget REAL NOT NULL, column_price REAL NOT NULL, columns INTEGER NOT NULL,
            cost REAL NOT NULL, p15 REAL NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', hits INTEGER,
            winning_columns TEXT, prize REAL, settled_at TEXT);
    """)
    events = [{"event_no": i + 1, "event_name": n, "home": None, "away": None, "competition": "SÜPL", "kickoff_utc": None,
               "picks": ["1"], "cover": 0.5, "kind": "banko", "source": "yok", "probs": {o: 1 / 3 for o in OUTCOMES},
               "confidence": None, "match_id": None, "league_name": None, "odds": None, "model": None, "market": None}
              for i, n in enumerate(OURS)]
    payload = {"cycle_no": 350, "budget": 3000.0, "column_price": 10.0, "max_column": 2500, "pool_source": "iddaa",
               "columns": 1, "cost": 10.0, "p15": 0.0, "p_at_least": {}, "expected_hits": 7.5, "events": events, "n_no_data": 15}
    con.execute("INSERT INTO toto_weeks VALUES(350,'eski',NULL,'2026-09-04T16:55:00Z',NULL,'open','x')")
    con.execute("INSERT INTO toto_coupons VALUES(350,'a','b',1,3000,10,1,10,0,?,'settled',9,'{}',0.0,'c')", (json.dumps(payload),))
    db.migrate(con)
    db.migrate(con)   # idempotent
    rows = con.execute("SELECT kind, status, hits FROM toto_coupon_sets WHERE cycle_no=350").fetchall()
    assert [tuple(r) for r in rows] == [("olasilik", "settled", 9)]
    v = toto_view(con)
    slots = {s["kind"]: s for s in v["coupons"]}
    c1 = slots["olasilik"]["coupon"]
    assert c1 is not None and c1["kind"] == "olasilik" and c1["hits"] == 9 and c1["events"][0]["crowd"] is None
    assert slots["kalabalik"]["coupon"] is None and slots["kalabalik"]["reason"] == sc_legacy_reason()
    assert v["history"]["by_kind"]["olasilik"]["settled"] == 1


def sc_legacy_reason() -> str:
    from app.sportoto import _NO_CROWD_LEGACY

    return _NO_CROWD_LEGACY
