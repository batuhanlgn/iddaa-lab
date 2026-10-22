"""Korner / kart: pazar ayrıştırma, olasılık tutarlılığı, iddaa kart sayımı, sonuçlandırma ve kupon kuralı (ağsız)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import coupons, db
from app.coupons import Selection, aux_coupon
from app.ingest import details_due, is_detail_key
from app.model import aux_markets as ax
from app.model import markets as mk
from app.model.goals import score_matrix
from app.model.pipeline import markets_from_rows, market_validated
from app.sources.espn import card_counts
from app.sources.iddaa import parse_event_detail, parse_events

KICK = int((datetime.now(timezone.utc) + timedelta(hours=10)).timestamp())


def _mkt(st: int, sov: str | None, outs: list[tuple[int, str, float]], t: int = 2) -> dict:
    return {"t": t, "st": st, "sov": sov, "mbc": 1, "o": [{"no": n, "n": nm, "odd": o} for n, nm, o in outs]}


def _detail_payload(eid: int = 3235174) -> dict:
    return {"isSuccess": True, "data": {
        "i": eid, "sid": 1, "hn": "Como 1907", "an": "Sassuolo", "d": KICK, "mbc": 1, "ci": 143,
        "m": [
            _mkt(1, None, [(1, "1", 1.5), (2, "0", 4.0), (3, "2", 6.0)], t=1),       # MS: detaydan alınmaz
            _mkt(48, "9.5", [(1, "Alt", 1.72), (2, "Üst", 1.68)]),
            _mkt(49, "4.5", [(1, "Alt", 1.65), (2, "Üst", 1.75)]),                   # İY korner: kapsam dışı
            _mkt(67, None, [(1, "0-8", 2.22), (2, "9-11", 2.51), (3, "12+", 2.8)]),
            _mkt(822, "6.5", [(1, "Alt", 1.57), (2, "Üst", 1.87)]),
            _mkt(52, None, [(1, "1", 1.16), (2, "0", 7.22), (3, "2", 4.76)]),
            _mkt(863, "-2.5", [(1, "1", 1.55), (2, "2", 1.89)]),
            _mkt(658, "3.5", [(1, "Alt", 1.83), (2, "Üst", 1.6)]),
            _mkt(17, None, [(1, "Evet", 4.91), (2, "Hayır", 1.0)]),                  # Hayır kapalı (1.00)
            _mkt(824, None, [(1, "1", 3.0), (2, "0", 3.73), (3, "2", 1.75)]),
        ],
    }}


# ---------------------------------------------------------------- iddaa ayrıştırma

def test_detail_parse_keeps_only_corner_card_markets():
    ev = parse_event_detail(_detail_payload(), 3235174)
    assert ev is not None and not ev.is_live
    keys = {m.market_key for m in ev.markets}
    assert keys == {"2:48:9.5", "2:67:", "2:822:6.5", "2:52:", "2:863:-2.5", "2:658:3.5", "2:17:", "2:824:"}
    red = next(m for m in ev.markets if m.st == 17)
    assert [o.name for o in red.outcomes] == ["Evet"]          # 1.00 oranlı sonuç kapalı sayılır
    assert all(is_detail_key(k) for k in keys)
    assert not is_detail_key("1:1:") and not is_detail_key("2:101:2.5") and not is_detail_key("bozuk")


def test_detail_parse_rejects_other_event_and_failure():
    assert parse_event_detail(_detail_payload(1), 2) is None
    with pytest.raises(ValueError):
        parse_event_detail({"isSuccess": False}, 1)


def test_bulk_parser_also_maps_new_markets():
    payload = {"isSuccess": True, "data": {"events": [{**_detail_payload()["data"]}]}}
    ev = parse_events(payload)[0]
    keys = {m.market_key for m in ev.markets}
    assert "1:1:" in keys and "2:48:9.5" in keys and "2:49:4.5" not in keys


# ---------------------------------------------------------------- olasılıklar

@pytest.fixture
def cj() -> ax.CountJoint:
    return ax.count_joint(5.6, 4.3, ax.CountDist(30.0, 11.0), ax.CORNER_NMAX)


def test_joint_is_distribution_with_model_means(cj):
    assert cj.P.sum() == pytest.approx(1.0, abs=1e-6)
    assert (cj.P * cj.H).sum() == pytest.approx(5.6, rel=0.01)
    assert (cj.P * cj.A).sum() == pytest.approx(4.3, rel=0.01)
    assert (cj.P * (cj.H + cj.A)).sum() == pytest.approx(9.9, rel=0.01)


def test_total_team_range_kdc_handicap_consistency(cj):
    p = lambda key, sov, name: ax.outcome_prob(key, sov, name, cj)  # noqa: E731
    for L in ("7.5", "9.5", "11.5"):
        assert p("korner_au", L, "Alt") + p("korner_au", L, "Üst") == pytest.approx(1.0, abs=1e-9)
    # Çizgi yükseldikçe Üst olasılığı azalır
    ups = [p("korner_au", str(L), "Üst") for L in (7.5, 8.5, 9.5, 10.5, 11.5)]
    assert all(a > b for a, b in zip(ups, ups[1:]))
    # Aralık = toplam çizgilerinin farkı ve toplamı 1
    r = [p("korner_ar", None, n) for n in ("0-8", "9-11", "12+")]
    assert sum(r) == pytest.approx(1.0, abs=1e-9)
    assert r[0] == pytest.approx(p("korner_au", "8.5", "Alt"), abs=1e-12)
    assert r[2] == pytest.approx(p("korner_au", "11.5", "Üst"), abs=1e-12)
    # Kim daha çok: 3 sonuç toplamı 1; handikap ±0.5 ile özdeş
    k = {n: p("korner_kdc", None, n) for n in ("1", "0", "2")}
    assert sum(k.values()) == pytest.approx(1.0, abs=1e-9)
    assert p("korner_hnd", "-0.5", "1") == pytest.approx(k["1"], abs=1e-12)
    assert p("korner_hnd", "0.5", "1") == pytest.approx(k["1"] + k["0"], abs=1e-12)
    assert p("korner_hnd", "-2.5", "1") + p("korner_hnd", "-2.5", "2") == pytest.approx(1.0, abs=1e-9)
    assert p("korner_hnd", "-2.5", "1") < p("korner_hnd", "-1.5", "1") < k["1"]
    # Takım A/Ü marjinalle tutarlı; ev sahibi ortalaması yüksek -> 4.5 Üst ev > deplasman
    assert p("ev_korner_au", "4.5", "Üst") > p("dep_korner_au", "4.5", "Üst")
    assert p("ev_korner_au", "4.5", "Üst") == pytest.approx(cj.P[cj.H > 4.5].sum(), abs=1e-12)
    # Tanınmayan ad / çizgisiz A/Ü fiyatlanmaz
    assert p("korner_au", None, "Üst") is None and p("korner_ar", None, "13-15+") is None


def test_share_model_gives_negative_within_match_correlation():
    j = ax.count_joint(5.0, 5.0, ax.CountDist(60.0, 11.0), ax.CORNER_NMAX)
    eh, ea = (j.P * j.H).sum(), (j.P * j.A).sum()
    cov = (j.P * (j.H - eh) * (j.A - ea)).sum()
    assert cov < 0     # sabit toplamda bir takımın payı artınca diğerininki azalır


def test_shrink_moves_total_toward_league_and_keeps_share():
    mh, ma = ax.shrink_means(6.0, 6.0, 10.0, 0.5)
    assert mh + ma == pytest.approx(10.0 * (12.0 / 10.0) ** 0.5)
    assert mh / (mh + ma) == pytest.approx(0.5)
    assert ax.shrink_means(6.0, 4.0, None, 0.5) == (6.0, 4.0)
    assert ax.shrink_means(6.0, 4.0, 9.0, 1.0) == (6.0, 4.0)


def test_card_markets_first_half_and_red():
    j = ax.count_joint(2.3, 2.1, ax.CountDist(15.0, 1000.0), ax.CARD_NMAX, ht_share=0.33, p_red=ax.red_prob(0.11, 0.12))
    ht = j.ht_total_pmf()
    assert ht is not None and ht.sum() == pytest.approx(1.0, abs=1e-6)
    assert (ht * np.arange(ht.size)).sum() == pytest.approx(0.33 * (j.P * (j.H + j.A)).sum(), rel=1e-6)
    assert ax.outcome_prob("iy_kart_au", "1.5", "Alt", j) + ax.outcome_prob("iy_kart_au", "1.5", "Üst", j) == pytest.approx(1.0)
    assert ax.outcome_prob("kart_au", "4.5", "Üst", j) > ax.outcome_prob("iy_kart_au", "4.5", "Üst", j)
    pr = ax.outcome_prob("kirmizi", None, "Evet", j)
    assert pr == pytest.approx(1 - np.exp(-0.23)) and ax.outcome_prob("kirmizi", None, "Hayır", j) == pytest.approx(1 - pr)
    no_ht = ax.count_joint(2.3, 2.1, ax.CountDist(15.0, 1000.0), ax.CARD_NMAX)
    assert ax.outcome_prob("iy_kart_au", "1.5", "Alt", no_ht) is None and ax.outcome_prob("kirmizi", None, "Evet", no_ht) is None


def test_fit_total_and_phi_recover_simulated_parameters():
    rng = np.random.default_rng(3)
    n = 4000
    mu = rng.uniform(8, 12, n)
    k = 30.0
    T = rng.negative_binomial(k, k / (k + mu))
    beta, k_hat, _ = ax.fit_total(mu, np.full(n, 10.0), T, (7.5, 8.5, 9.5, 10.5, 11.5))
    assert beta >= 0.8 and 15.0 <= k_hat <= 100.0
    pi = rng.uniform(0.35, 0.65, n)
    h = rng.binomial(T, rng.beta(pi * 12, (1 - pi) * 12))
    assert 6.0 < ax.fit_phi(pi, h, T) < 25.0


# ---------------------------------------------------------------- iddaa kart sayımı (ESPN keyEvents)

def _card(t: str, team: str, ath: str, period: int, text: str = "") -> dict:
    return {"type": {"type": t}, "team": {"id": team}, "participants": [{"athlete": {"id": ath}}],
            "period": {"number": period}, "text": text}


def test_card_counts_follow_iddaa_rule():
    payload = {"keyEvents": [
        {"type": {"type": "kickoff"}, "period": {"number": 1}},
        _card("yellow-card", "10", "a", 1),                                # A: sarı (ilk yarı)
        _card("red-card", "10", "a", 2, "Second yellow card to A"),        # A: ikinci sarıdan kırmızı -> 1 + 2
        _card("red-card", "10", "b", 2, "B is shown the red card"),        # B: doğrudan kırmızı -> 2
        _card("yellow-card", "20", "c", 1),
        _card("yellow-card", "20", "c", 2),                                # C: kırmızısız ikinci sarı = mükerrer -> 1
        _card("yellow-card", "20", "d", 3),                                # uzatma devresi: sayılmaz
    ]}
    cc = card_counts(payload, ["10", "20", "30"])
    assert (cc["10"].points, cc["10"].points_ht, cc["10"].reds) == (5, 1, 2)
    assert (cc["20"].points, cc["20"].points_ht, cc["20"].reds) == (1, 1, 0)
    assert (cc["30"].points, cc["30"].reds) == (0, 0)                     # kart olayı olmayan takım 0
    assert card_counts({"keyEvents": []}, ["10"]) == {}                   # olay listesi yok: bilinmiyor


# ---------------------------------------------------------------- sonuçlandırma

def test_aux_settle_rules():
    r = ax.AuxResult(6, 4, ht_total=1, reds=0)
    assert ax.settle("korner_au", "9.5", "Üst", r) == "won"
    assert ax.settle("korner_au", "10", "Üst", r) == "void"                 # tam sayı çizgide eşitlik: iade
    assert ax.settle("ev_korner_au", "5.5", "Alt", r) == "lost"
    assert ax.settle("dep_korner_au", "4.5", "Alt", r) == "won"
    assert ax.settle("korner_ar", None, "9-11", r) == "won"
    assert ax.settle("korner_kdc", None, "1", r) == "won"
    assert ax.settle("korner_hnd", "-2.5", "1", r) is not None and ax.settle("korner_hnd", "-2.5", "1", r) == "lost"
    assert ax.settle("korner_hnd", "-2", "1", r) == "void"
    assert ax.settle("kart_au", "3.5", "Alt", ax.AuxResult(2, 1, 0, 0)) == "won"
    assert ax.settle("iy_kart_au", "0.5", "Üst", r) == "won"
    assert ax.settle("iy_kart_au", "0.5", "Üst", ax.AuxResult(2, 1)) is None   # ilk yarı verisi yok
    assert ax.settle("kirmizi", None, "Hayır", r) == "won"
    assert ax.settle("kirmizi", None, "Evet", ax.AuxResult(3, 2, 1, 1)) == "won"
    assert ax.settle("kart_kdc", None, "X", r) is None


def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    db.migrate(con)
    return con


def _add_match(con: sqlite3.Connection, mid: str, extra_time: int, stats: list[tuple]) -> None:
    con.execute(
        """INSERT INTO matches(id, league, date_utc, state, completed, home_id, away_id, home_goals, away_goals,
               scoreboard_fetched_at, extra_time, ft90_home, ft90_away) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, "eng.1", "2026-10-18T14:00:00Z", "post", 1, "h", "a", 1, 1, "x", extra_time, 1, 1))
    for is_home, corners, pts, pts_ht, reds in stats:
        con.execute(
            """INSERT INTO team_match_stats(match_id, team_id, is_home, corners, card_points, card_points_ht, red_cards_90)
               VALUES(?,?,?,?,?,?,?)""", (mid, "h" if is_home else "a", is_home, corners, pts, pts_ht, reds))


def test_settle_selection_uses_90_minute_values():
    con = _mem_db()
    _add_match(con, "m1", 0, [(1, 7, 3, 1, 0), (0, 3, 2, 0, 1)])
    _add_match(con, "m2", 1, [(1, 9, 2, 1, 0), (0, 5, 1, 0, 0)])   # uzatmalı: korner bilinmiyor, kart (olaylardan) biliniyor
    sel = lambda mid, key, line, name: {"match_id": mid, "key": key, "line": line, "outcome_name": name,  # noqa: E731
                                        "family": "korner" if "korner" in key else "kart", "market_key": "2:0:"}
    assert coupons.settle_selection(con, sel("m1", "korner_au", "9.5", "Üst")) == "won"
    assert coupons.settle_selection(con, sel("m1", "kart_au", "4.5", "Üst")) == "won"
    assert coupons.settle_selection(con, sel("m1", "kirmizi", None, "Evet")) == "won"
    assert coupons.settle_selection(con, sel("m1", "kart_kdc", None, "1")) == "won"
    assert coupons.settle_selection(con, sel("m2", "korner_au", "9.5", "Üst")) is None
    assert coupons.settle_selection(con, sel("m2", "kart_au", "2.5", "Üst")) == "won"


# ---------------------------------------------------------------- pazarlar (model / piyasa / harman)

def test_markets_from_rows_aux_and_one_sided_red():
    sm = score_matrix(1.5, 1.1, -0.05)
    j = mk.build_joint(sm, 0.44)
    cj = ax.count_joint(5.6, 4.3, ax.CountDist(30.0, 11.0), ax.CORNER_NMAX)
    kj = ax.count_joint(2.3, 2.1, ax.CountDist(15.0, 1000.0), ax.CARD_NMAX, ht_share=0.33, p_red=0.2)
    f = "2026-10-22T10:00:00Z"
    rows = [
        {"market_key": "2:48:9.5", "outcome_no": 1, "outcome_name": "Alt", "odd": 1.72, "mbs": 1, "fetched_at": f},
        {"market_key": "2:48:9.5", "outcome_no": 2, "outcome_name": "Üst", "odd": 1.68, "mbs": 1, "fetched_at": f},
        {"market_key": "2:48:7.5", "outcome_no": 1, "outcome_name": "Alt", "odd": 3.05, "mbs": 1, "fetched_at": f},
        {"market_key": "2:48:7.5", "outcome_no": 2, "outcome_name": "Üst", "odd": 1.18, "mbs": 1, "fetched_at": f},
        {"market_key": "2:17:", "outcome_no": 1, "outcome_name": "Evet", "odd": 4.91, "mbs": 1, "fetched_at": f},
    ]
    validated = {"korner": True, "kart": False}
    market_ok = {"korner_au": True, "korner_au 7.5": False}
    out, _ = markets_from_rows(rows, sm, j, 0.44, -0.05, {"korner": cj, "kart": kj}, 0.5, validated, (1.5, 1.1), market_ok)
    by = {m["market_key"]: m for m in out}
    k95 = by["2:48:9.5"]
    assert k95["family"] == "korner" and k95["family_validated"] is True
    assert sum(o["p_model"] for o in k95["outcomes"]) == pytest.approx(1.0)
    assert k95["outcomes"][1]["p_model"] == pytest.approx(ax.outcome_prob("korner_au", "9.5", "Üst", cj))
    assert sum(o["p_market"] for o in k95["outcomes"]) == pytest.approx(1.0)
    assert by["2:48:7.5"]["family_validated"] is False                        # çizgi bayrağı (7.5 taban orandan kötü)
    red = by["2:17:"]
    assert red["margin"] is None and len(red["outcomes"]) == 1
    o = red["outcomes"][0]
    assert o["p_model"] == pytest.approx(0.2) and o["p_market"] == pytest.approx(1 / 4.91)
    assert o["ev"] == pytest.approx(o["p_safe"] * 4.91 - 1)
    # aux yoksa korner/kart pazarı fiyatlanmaz
    out2, _ = markets_from_rows(rows, sm, j, 0.44, -0.05, None, 0.5, validated, (1.5, 1.1))
    assert not [m for m in out2 if m["family"] in ("korner", "kart")]


def test_market_validated_flags():
    v = {"korner": True}
    ok = {"korner_au": True, "korner_au 7.5": False, "korner_kdc": False}
    assert market_validated(v, ok, "korner", "korner_au", "9.5") is True
    assert market_validated(v, ok, "korner", "korner_au", "7.5") is False
    assert market_validated(v, ok, "korner", "korner_kdc", None) is False
    assert market_validated(v, ok, "korner", "korner_ar", None) is True       # değerlendirilmemiş -> aile bayrağı
    assert market_validated({"korner": False}, ok, "korner", "korner_au", "9.5") is False


# ---------------------------------------------------------------- kupon kuralı

def _sel(mid: str, key: str, fam: str, name: str, odd: float, pm: float, pq: float, mbs: int = 1, ok: bool = True,
         mkey: str = "2:48:9.5", no: int = 2) -> Selection:
    return Selection(match_id=mid, iddaa_event_id=int(mid[1:]), home="H", away="A", league_name="L", date_utc="2026-10-23T18:00:00Z",
                     market_key=mkey, key=key, label=key, family=fam, line="9.5", outcome_no=no, outcome_name=name, odd=odd,
                     p_model=pm, p_market=pq, p_blend=pm, ev=pm * odd - 1, mbs=mbs, confidence="yüksek",
                     family_validated=ok)


def test_aux_coupon_picks_most_confident_distinct_matches():
    cands = [
        _sel("m1", "korner_au", "korner", "Üst", 1.30, 0.80, 0.74),
        _sel("m1", "korner_kdc", "korner", "1", 1.25, 0.82, 0.78, mkey="2:52:", no=1),   # aynı maç: daha emin olan
        _sel("m2", "korner_au", "korner", "Alt", 1.40, 0.72, 0.70),
        _sel("m3", "korner_au", "korner", "Üst", 1.22, 0.79, 0.80),                      # model piyasadan az emin: elenir
        _sel("m4", "korner_au", "korner", "Üst", 1.15, 0.90, 0.85),                      # oran < 1.20: elenir
        _sel("m5", "korner_au", "korner", "Alt", 1.50, 0.65, 0.62),
        _sel("m6", "korner_au", "korner", "Alt", 1.60, 0.66, 0.60),                      # bültende oranı değişti
        _sel("m7", "kart_au", "kart", "Üst", 1.30, 0.95, 0.70, mkey="2:658:3.5"),         # başka aile
    ]
    live = {(c.iddaa_event_id, c.market_key, c.outcome_no): c.odd for c in cands}
    live[(6, "2:48:9.5", 2)] = 1.55
    c = aux_coupon("korner", cands, live)
    picked = [(s["match_id"], s["key"]) for s in c["selections"]]
    assert picked == [("m1", "korner_kdc"), ("m2", "korner_au"), ("m5", "korner_au")]
    assert c["experimental"] is False and c["scout_gated"] is False and c["mbs_ok"]
    assert c["total_odds"] == pytest.approx(1.25 * 1.40 * 1.50)


def test_aux_coupon_experimental_and_mbs_and_empty():
    cands = [_sel("m1", "kart_au", "kart", "Üst", 1.3, 0.8, 0.7, ok=False, mkey="2:658:3.5"),
             _sel("m2", "kart_au", "kart", "Üst", 1.3, 0.75, 0.7, mkey="2:658:3.5"),
             _sel("m3", "kart_au", "kart", "Üst", 1.3, 0.70, 0.7, mbs=3, mkey="2:658:3.5")]
    live = {(c.iddaa_event_id, c.market_key, c.outcome_no): c.odd for c in cands}
    c = aux_coupon("kart", cands, live)
    assert len(c["selections"]) == 3 and c["experimental"] is True and "Deneysel" in c["description"]
    c2 = aux_coupon("kart", cands[:1], live)
    assert c2["selections"] == [] and c2["empty_reason"]
    # MBS 3'lük seçim 2'li kupona sığmaz: m3 dışarıda kalınca 2'li kupon
    c3 = aux_coupon("kart", [cands[0], cands[2]], live)
    assert c3["selections"] == []


# ---------------------------------------------------------------- detay çekim zamanlaması

def test_details_due_schedule():
    con = _mem_db()
    now = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    con.execute("""INSERT INTO matches(id, league, date_utc, state, home_id, away_id, scoreboard_fetched_at)
                   VALUES('e', 'eng.1', '2026-10-23T12:00:00Z', 'pre', 'h', 'a', 'x')""")
    rows = [
        (1, now + timedelta(hours=30), None, "e"),                          # hiç çekilmedi -> çek
        (2, now + timedelta(hours=30), now - timedelta(hours=1), "e"),      # 1 saat önce -> bekle
        (3, now + timedelta(hours=30), now - timedelta(hours=3, minutes=5), "e"),  # 3 saat geçti -> çek
        (4, now + timedelta(hours=4), now - timedelta(minutes=40), "e"),    # 6 saatten az kaldı, 30 dk geçti -> çek
        (5, now + timedelta(hours=4), now - timedelta(minutes=10), "e"),    # 10 dk önce -> bekle
        (6, now + timedelta(hours=80), None, "e"),                          # 72 saatten uzak -> yok
        (7, now + timedelta(hours=5), None, None),                          # ESPN maçıyla eşleşmemiş -> yok
        (8, now - timedelta(hours=1), None, "e"),                           # başlamış -> yok
    ]
    for eid, kick, fetched, espn in rows:
        con.execute(
            """INSERT INTO iddaa_events(id, home_name, away_name, kickoff_utc, is_live, espn_match_id, last_seen_at, active,
                   detail_fetched_at) VALUES(?,?,?,?,?,?,?,?,?)""",
            (eid, "H", "A", iso(kick), 0, espn, iso(now), 1, iso(fetched) if fetched else None))
    due = [r["id"] for r in details_due(con, now)]
    assert due == [4, 1, 3]                                                  # en yakın maç önce
