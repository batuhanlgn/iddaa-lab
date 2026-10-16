from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

import pytest

from app import db
from app.model import markets as mk
from app.sportoto import _best_match, event_probs, split_event_name
from app.sportoto_backtest import (
    SCHEMA_SQL, calibration, column_price, coupon_prize, fetch_toto_history, live_probs, map_totokazan,
    scheduled_price, settle, summarize, tier_pools,
)


def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    con.executescript(SCHEMA_SQL)
    return con


# ---------------------------------------------------------------- olasılık önceliği canlıyla aynı

def _payload(covered: bool = True, with_market: bool = True, blend: bool = True) -> dict[str, Any]:
    p: dict[str, Any] = {"match": {"id": "m1", "league_name": "Süper Lig"}, "covered": covered}
    if covered:
        p["model"] = {"confidence": "orta"}
        p["markets"] = [{"key": "ms", "outcomes": [{"name": "1", "p_model": 0.5}, {"name": "0", "p_model": 0.3},
                                                   {"name": "2", "p_model": 0.2}]}]
        if with_market:
            outs = [{"name": n, "odd": o, "p_market": q, "p_blend": (b if blend else None)}
                    for n, o, q, b in (("1", 2.0, 0.47, 0.49), ("0", 3.3, 0.29, 0.30), ("2", 4.2, 0.24, 0.22))]
            p["iddaa"] = {"markets": [{"key": "ms", "outcomes": outs}]}
    return p


@pytest.mark.parametrize("covered,with_market,blend,expected", [
    (True, True, True, "harman"), (True, True, False, "model"), (True, False, True, "model"), (False, False, False, "yok"),
])
def test_live_probs_matches_event_probs(covered: bool, with_market: bool, blend: bool, expected: str):
    con = _mem_db()
    p = _payload(covered, with_market, blend)
    con.execute("INSERT INTO predictions VALUES('m1', '2026-01-01T00:00:00Z', 'v1', ?)", (json.dumps(p),))
    con.execute("INSERT INTO toto_events(cycle_no, event_no, event_name, espn_match_id) VALUES(1, 1, 'A - B', 'm1')")
    ev = con.execute("SELECT * FROM toto_events").fetchone()
    live = event_probs(con, ev)
    bt = live_probs(p, None)
    assert live["source"] == bt["source"] == expected
    for o in ("1", "0", "2"):
        assert bt["probs"][o] == pytest.approx(live["probs"][o])


def test_live_probs_market_fallback_matches_event_probs():
    """Model kapsamı yokken canlı iddaa oranını marjsız kullanır; backtest aynı yeri kapanış oranıyla doldurur."""
    con = _mem_db()
    odds = {"1": 1.8, "0": 3.6, "2": 4.5}
    con.execute("INSERT INTO iddaa_events(id, home_name, away_name, kickoff_utc, last_seen_at) VALUES(7,'A','B','x','x')")
    for i, (n, o) in enumerate(odds.items()):
        con.execute("INSERT INTO odds_current VALUES(7, '1:1:', ?, ?, ?, 1, 'x')", (i + 1, n, o))
    con.execute("INSERT INTO toto_events(cycle_no, event_no, event_name, iddaa_event_id) VALUES(1, 1, 'A - B', 7)")
    live = event_probs(con, con.execute("SELECT * FROM toto_events").fetchone())
    q = dict(zip(("1", "0", "2"), mk.devig(list(odds.values()))))
    bt = live_probs(_payload(covered=False), q)
    assert live["source"] == bt["source"] == "piyasa"
    assert bt["probs"] == pytest.approx(live["probs"])


# ---------------------------------------------------------------- kolon bedeli

def test_column_price_schedule_and_sources():
    assert scheduled_price(248) is None            # 2→4 TL geçiş haftası doğrulanamadı
    assert scheduled_price(249)[0] == 4.0 and scheduled_price(280)[0] == 4.0  # type: ignore[index]
    assert scheduled_price(281)[0] == 10.0 and scheduled_price(400)[0] == 10.0  # type: ignore[index]
    assert column_price(248, {}) == (None, "bilinmiyor")
    assert column_price(300, {}) == (10.0, "tarife")
    assert column_price(340, {"totokazan": 10.0}) == (10.0, "tarife+totokazan")
    price, why = column_price(340, {"totokazan": 5.0})
    assert price is None and why.startswith("çelişki")
    assert column_price(248, {"iddaa_appconfig": 4.0}) == (4.0, "iddaa_appconfig")  # canlı gözlem kesin


def test_map_totokazan_by_sale_window():
    weeks = [(330, "2026-03-01T07:00:00Z", "2026-03-06T19:40:00Z"), (331, "2026-03-08T07:00:00Z", "2026-03-13T19:40:00Z")]
    items = [{"created_at": "2026-03-03 21:46:36", "column_price": "10.00"},   # 330'un satış penceresi
             {"created_at": "2026-03-07 12:00:00", "column_price": "10.00"},   # 331 açılmadan 2 gün içinde
             {"created_at": "2026-05-01 12:00:00", "column_price": "10.00"},   # hiçbir pencereye düşmüyor
             {"created_at": "2026-03-09 12:00:00", "column_price": "bozuk"}]
    assert map_totokazan(items, weeks) == {330: 10.0, 331: 10.0}


# ---------------------------------------------------------------- havuz, ikramiye, maliyet

def _result_payload(divs: list[tuple[int, str, str]], carry: list[tuple[str, float]] | None = None) -> dict[str, Any]:
    return {"isSuccess": True, "data": {
        "dividends": [{"ordinalNumber": o, "winners": w, "amount": a} for o, w, a in divs],
        "nextDrawExpectedWins": [{"winClass": c, "amount": a} for c, a in (carry or [])]}}


def test_tier_pools_turkish_numbers_and_carry():
    pools = tier_pools(_result_payload(
        [(1, "0", "0,00"), (2, "0", "1.250.000,50"), (3, "12", "1.074.061,00"), (4, "0", "0,00")], carry=[("1", 22555274.48)]))
    by = {p["tier"]: p for p in pools or []}
    assert by[15]["pool"] == pytest.approx(22555274.48) and by[15]["pool_known"]   # devreden
    assert by[14]["pool"] == pytest.approx(1250000.50)                               # kazanansız: ilan edilen tutar
    assert by[13]["pool"] == pytest.approx(12 * 1074061.0) and by[13]["winners"] == 12
    assert by[12]["pool"] == 0.0 and not by[12]["pool_known"]
    assert tier_pools({"isSuccess": True, "data": {"dividends": None}}) is None


def test_coupon_prize_shares_pool_with_official_winners():
    pools = [{"tier": 15, "winners": 0, "amount": 0.0, "pool": 1_000_000.0, "pool_known": True},
             {"tier": 14, "winners": 9, "amount": 1000.0, "pool": 9000.0, "pool_known": True},
             {"tier": 12, "winners": 0, "amount": 0.0, "pool": 0.0, "pool_known": False}]
    prize, unknown = coupon_prize({15: 1, 14: 3}, pools)
    assert prize == pytest.approx(1_000_000.0 + 9000.0 * 3 / 12) and not unknown
    prize, unknown = coupon_prize({12: 2}, pools)
    assert prize == 0.0 and unknown


def test_settle_cost_hits_and_prize():
    # 2 çift + 1 üçlü + 12 banko = 12 kolon; maç 1 kaçtı, maç 2 çiftten tuttu -> en iyi kolon 14, ikinci kademe kolonları
    picks = [["1", "0"], ["1", "2"], ["1", "0", "2"]] + [["1"]] * 12
    winners = ["2", "2", "0"] + ["1"] * 12
    pools = [{"tier": t, "winners": 100, "amount": a, "pool": 100 * a, "pool_known": True}
             for t, a in ((15, 1e6), (14, 1e4), (13, 100.0), (12, 10.0))]
    res = settle(picks, winners, pools, 4.0)
    assert res["columns"] == 12 and res["cost"] == 48.0 and res["hits"] == 14
    assert res["winning_columns"] == {"14": 2, "13": 6, "12": 4}   # 2·(1+x)(2+x)·x^12 = 2x^14 + 6x^13 + 4x^12
    exp = 2 * 1e4 * 100 / 102 + 6 * 100 * 100 / 106 + 4 * 10 * 100 / 104
    assert res["prize"] == pytest.approx(exp)


def test_summarize_and_calibration():
    weeks = [{"hits": 12, "cost": 3000.0, "prize": 500.0}, {"hits": 15, "cost": 3000.0, "prize": 1e6},
             {"hits": 9, "cost": 1200.0, "prize": 0.0}]
    s = summarize(weeks)
    assert s["n_weeks"] == 3 and s["cost"] == 7200.0 and s["roi"] == pytest.approx((1e6 + 500) / 7200 - 1)
    assert (s["weeks_12plus"], s["weeks_13plus"], s["weeks_14plus"], s["weeks_15"]) == (2, 1, 1, 1)
    assert s["hit_distribution"] == {"9": 1, "12": 1, "15": 1} and s["prize_weeks"] == 2
    assert summarize([]) == {"n_weeks": 0}
    ev = [{"cover": 0.95, "picks": ["1", "0", "2"], "winner": "1", "source": "yok", "probs": {"1": 1 / 3, "0": 1 / 3, "2": 1 / 3}},
          {"cover": 0.55, "picks": ["1"], "winner": "2", "source": "harman", "probs": {"1": 0.55, "0": 0.25, "2": 0.2},
           "model": {"1": 0.6, "0": 0.2, "2": 0.2}, "market": {"1": 0.5, "0": 0.3, "2": 0.2}}]
    cal = calibration([{"events": ev, "hits": 1, "expected_hits": 1.5, "p_at_least": {"12": 0.1, "13": 0.0, "14": 0.0, "15": 0.0}}])
    assert cal["expected_hits"] == 1.5 and cal["actual_hits"] == 1
    assert [(b["n"], b["obs"]) for b in cal["cover_bins"]] == [(1, 0.0), (1, 1.0)]
    assert set(cal["same_matches"]) == {"model", "piyasa", "harman"}
    assert cal["by_source"]["harman"]["top_hit"] == 0.0


# ---------------------------------------------------------------- eşleştirme

def test_toto_event_matches_espn_by_time_and_name():
    rows = [{"id": "e1", "date_utc": "2025-08-08T18:30:00Z", "hn": "Gaziantep FK", "an": "Galatasaray"},
            {"id": "e2", "date_utc": "2025-08-08T18:30:00Z", "hn": "Samsunspor", "an": "Gençlerbirliği"},
            {"id": "e3", "date_utc": "2025-08-09T18:30:00Z", "hn": "Gaziantep FK", "an": "Galatasaray"}]
    cands = split_event_name("Gaziantep F.K. A.Ş. - Galatasaray A.Ş.")
    m, h, a = _best_match(cands, "2025-08-08T19:30:00Z", rows, "date_utc", "hn", "an")  # type: ignore[arg-type]
    assert m is not None and m["id"] == "e1" and a == "Galatasaray"
    m, _, _ = _best_match(cands, "2025-08-08T21:00:00Z", rows[2:], "date_utc", "hn", "an")  # type: ignore[arg-type]
    assert m is None                                                    # ±100 dk dışında
    m, _, _ = _best_match(split_event_name("Bandırmaspor-Sakaryaspor"), "2025-08-08T18:30:00Z", rows,  # type: ignore[arg-type]
                          "date_utc", "hn", "an")
    assert m is None                                                    # ESPN'de yok -> veri yok


# ---------------------------------------------------------------- indirme (ağsız)

class _FakeClient:
    def __init__(self, weeks: dict[int, dict[str, Any]]) -> None:
        self.weeks = weeks
        self.calls: list[str] = []
        self.requests = 0

    async def get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        self.requests += 1
        self.calls.append(url + (f"?{params['gameCycleNo']}" if params else ""))
        if url.endswith("/dateFilter"):
            return {"isSuccess": True, "data": [{"gameCycleNo": c, "payinEndDate": w.get("_end", "2026-01-10T19:55:00")}
                                                for c, w in self.weeks.items()]}
        if url.endswith("/SporToto/result"):
            w = self.weeks[int(params["gameCycleNo"])]  # type: ignore[index]
            return w if w.get("isSuccess") else {"isSuccess": False, "data": None}
        if "appconfig" in url:
            return {"data": {"globalConfig": {"soccerPool": {"columnPrice": 10, "maxColumn": 2500}}}}
        if url.endswith("/SporToto"):
            return _week_payload(9, "2026-10-11T10:00:00", "2026-10-16T19:55:00", winners=False)
        if "totokazan" in url:
            return {"data": {"items": [{"created_at": "2026-01-06 10:00:00", "column_price": "10.00"}]}}
        raise AssertionError(url)


def _week_payload(cycle: int, begin: str, end: str, winners: bool = True) -> dict[str, Any]:
    evs = [{"eventNo": i, "eventName": f"Ev{i} - Dep{i}", "competitionName": "SÜPL", "eventDate": end,
            "result": "1:0" if winners else None, "winner": "1" if winners else None} for i in range(1, 16)]
    divs = [{"ordinalNumber": o, "winners": "2", "amount": "1.000,00"} for o in (1, 2, 3, 4)] if winners else None
    return {"isSuccess": True, "data": {"gameCycleNo": cycle, "programName": "x", "payinBeginDate": begin,
                                        "payinEndDate": end, "events": evs, "dividends": divs}, "_end": end}


def test_fetch_toto_history_offline_and_idempotent():
    con = _mem_db()
    weeks = {1: _week_payload(1, "2026-01-04T10:00:00", "2026-01-09T19:55:00"),
             2: {"isSuccess": False, "_end": "2026-01-16T19:55:00"}}
    cl = _FakeClient(weeks)
    out = asyncio.run(fetch_toto_history(con, lambda s: None, since="2025-12-01", client=cl))
    assert out["settled"] == 1 and out["missing"] == 1      # biteli 14 günden eski, bülteni yok
    w = con.execute("SELECT * FROM toto_hist_weeks WHERE cycle_no=1").fetchone()
    assert w["status"] == "settled" and w["payin_end_utc"] == "2026-01-09T16:55:00Z"
    assert json.loads(w["dividends"])[0] == {"tier": 15, "winners": 2, "amount": 1000.0, "pool": 2000.0, "pool_known": True}
    assert con.execute("SELECT COUNT(*) FROM toto_hist_events WHERE cycle_no=1").fetchone()[0] == 15
    prices = {(r["cycle_no"], r["source"]): r["price"] for r in con.execute("SELECT * FROM toto_hist_prices")}
    assert prices == {(9, "iddaa_appconfig"): 10.0, (1, "totokazan"): 10.0}
    cl2 = _FakeClient(weeks)
    asyncio.run(fetch_toto_history(con, lambda s: None, since="2025-12-01", client=cl2))
    assert not any("/result" in c for c in cl2.calls)       # biten haftalar yeniden istenmez


def test_fd_alias_lets_basaksehir_match_football_data():
    from app.scout_backtest import _find_fd
    from app.sportoto_backtest import _fd_alias

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE t(league, date, home, away, hg, ag, o1, ox, o2)")
    con.execute("INSERT INTO t VALUES('tur.1', '2025-03-01', 'Buyuksehyr', 'Konyaspor', 2, 1, 1.9, 3.5, 4.0)")
    rows = con.execute("SELECT * FROM t").fetchall()
    m = {"league": "tur.1", "date_utc": "2025-03-01T16:00:00Z", "hn": "Istanbul Basaksehir", "an": "Konyaspor", "hg": 2, "ag": 1}
    # _find_fd football-data ad düzeltmesini (footballdata.TEAM_ALIASES) kendisi uygular: ham satırla da eşleşir
    hit_raw = _find_fd(m, {("tur.1", "2025-03-01"): rows})  # type: ignore[arg-type]
    assert hit_raw is not None and hit_raw["o1"] == 1.9
    hit = _find_fd(m, {("tur.1", "2025-03-01"): [_fd_alias(r) for r in rows]})  # type: ignore[arg-type]
    assert hit is not None and hit["o1"] == 1.9
