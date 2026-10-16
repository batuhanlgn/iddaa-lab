"""Scout raporu: gerçek örnek yükler (web/static-data) ve sentetik durumlarla. Ağ yok."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.coupons import model_pick
from app.scout import SCOUT_VERSION, SIDES, build_scout

STATIC = Path(__file__).resolve().parents[2] / "web" / "static-data" / "matches"
SECTION_ORDER = ["guc", "form", "lig", "h2h", "profil", "piyasa", "risk"]
HOME, AWAY = "100", "200"
MARGIN = 1.07
KICKOFF = "2026-10-18T17:00:00Z"


# ---------------------------------------------------------------- sentetik yük

def _odd(q: float) -> float:
    return round(1.0 / (q * MARGIN), 2)


def _iddaa_market(key: str, label: str, family: str, line: str | None, names: list[str], p: list[float],
                  q: list[float]) -> dict[str, Any]:
    outs = []
    for i, (n, pm, qm) in enumerate(zip(names, p, q)):
        pb = (pm + qm) / 2
        o = _odd(qm)
        outs.append({"no": i + 1, "name": n, "odd": o, "p_model": pm, "p_market": qm, "p_blend": pb, "p_safe": pb,
                     "ev": pb * o - 1, "ev_model": pm * o - 1})
    sov = line or ""
    return {"market_key": f"x:{key}:{sov}", "key": key, "label": label, "family": family, "line": line, "mbs": 1,
            "margin": MARGIN - 1, "family_validated": True, "fetched_at": "2026-10-16T10:00:00Z", "outcomes": outs}


def _payload(p1: float = 0.62, p0: float = 0.22, p2: float = 0.16, lh: float = 2.0, la: float = 0.8, conf: str = "yüksek",
             over: float = 0.5, kg: float = 0.5, q: tuple[float, float, float] | None = None, q_over: float | None = None,
             hnd1: float | None = None, with_iddaa: bool = True, league: str = "eng.1", neutral: bool = False,
             sot: tuple[float, float] = (6.0, 3.0)) -> dict[str, Any]:
    q = q or (p1, p0, p2)
    q_over = over if q_over is None else q_over
    hnd1 = p1 * 0.55 if hnd1 is None else hnd1
    std = [
        {"key": "ms", "label": "Maç Sonucu", "family": "ms", "line": None,
         "outcomes": [{"name": "1", "p_model": p1}, {"name": "0", "p_model": p0}, {"name": "2", "p_model": p2}]},
        {"key": "cs", "label": "Çifte Şans", "family": "ms", "line": None,
         "outcomes": [{"name": "1 ve 0", "p_model": p1 + p0}, {"name": "1 ve 2", "p_model": p1 + p2},
                      {"name": "0 ve 2", "p_model": p0 + p2}]},
        {"key": "kg", "label": "Karşılıklı Gol", "family": "kg", "line": None,
         "outcomes": [{"name": "Var", "p_model": kg}, {"name": "Yok", "p_model": 1 - kg}]},
        {"key": "au", "label": "Alt/Üst", "family": "au", "line": "2.5",
         "outcomes": [{"name": "Alt", "p_model": 1 - over}, {"name": "Üst", "p_model": over}]},
    ]
    iddaa = None
    if with_iddaa:
        iddaa = {"event_id": 1, "mbs": 1, "market_model": None, "markets": [
            _iddaa_market("ms", "Maç Sonucu", "ms", None, ["1", "0", "2"], [p1, p0, p2], list(q)),
            _iddaa_market("cs", "Çifte Şans", "ms", None, ["1 ve 0", "1 ve 2", "0 ve 2"],
                          [p1 + p0, p1 + p2, p0 + p2], [q[0] + q[1], q[0] + q[2], q[1] + q[2]]),
            _iddaa_market("kg", "Karşılıklı Gol", "kg", None, ["Var", "Yok"], [kg, 1 - kg], [kg, 1 - kg]),
            _iddaa_market("au", "Alt/Üst", "au", "2.5", ["Alt", "Üst"], [1 - over, over], [1 - q_over, q_over]),
            _iddaa_market("hnd", "Handikaplı Maç Sonucu", "ms", "-1", ["1", "0", "2"], [hnd1, p1 - hnd1, 1 - p1],
                          [hnd1, p1 - hnd1, 1 - p1]),
        ]}

    def team(tid: str, s: float) -> dict[str, Any]:
        return {"team_id": tid, "shots": {"mean": s * 3}, "shots_on_target": {"mean": s}, "players_available": True,
                "players": [{"player_id": f"{tid}9", "name": f"Forvet {tid}", "pos_group": "F", "p_start": 0.9,
                             "exp_sot": 1.1, "p_sot_1": 0.55, "p_goal": 0.3, "rate_shots_p90": 3.0, "rate_acc": 0.4,
                             "rate_conv": 0.3, "minutes_seen": 1500, "confirmed_starter": None, "flags": []}]}

    return {
        "match": {"id": "999", "league": league, "league_name": "Premier League", "country": "İngiltere",
                  "date_utc": KICKOFF, "venue": None, "neutral": neutral, "state": "pre",
                  "home": {"id": HOME, "name": "Kartal SK"}, "away": {"id": AWAY, "name": "Martı FK"},
                  "lineup_confirmed": False},
        "model_version": "test", "created_at": "2026-10-16T10:00:00Z", "covered": True,
        "model": {"lambda_home": lh, "lambda_away": la, "rho": -0.03, "p1": 0.45, "confidence": conf,
                  "confidence_notes": [] if conf == "yüksek" else ["Takımın yakın dönem maç verisi çok az"],
                  "lineup_adj": {"beta": 0.0, "home": 1.0, "away": 1.0, "home_ratio": None, "away_ratio": None}},
        "markets": std, "top_scores": [{"home": 2, "away": 0, "p": 0.11}], "iddaa": iddaa,
        "sim": {"teams": {"home": team(HOME, sot[0]), "away": team(AWAY, sot[1])},
                "notes": {"home": [], "away": [], "lineup_source": {"home": "tahmini", "away": "tahmini"}}},
        "odds_history_ms": [],
    }


def _form(team: str, results: list[tuple[int, int, bool]], start_day: int = 10) -> list[dict[str, Any]]:
    """results: (atılan, yenen, iç saha mı) yeniden eskiye."""
    rows = []
    for i, (gf, ga, home) in enumerate(results):
        opp = f"o{i}"
        rows.append({"id": f"{team}-{i}", "date_utc": f"2026-10-{start_day - i:02d}T18:00:00Z", "league": "eng.1",
                     "home_id": team if home else opp, "away_id": opp if home else team,
                     "home_goals": gf if home else ga, "away_goals": ga if home else gf,
                     "hn": "x", "an": "y", "is_home": home})
    return rows


GOOD = [(2, 0, True), (3, 1, False), (2, 1, True), (1, 0, False), (2, 2, True), (3, 0, True)]
BAD = [(0, 2, False), (1, 1, True), (0, 1, False), (1, 3, True), (0, 2, False), (1, 2, False)]


def _standings(home_rank: int, home_pts: int, away_rank: int, away_pts: int, played: int = 10) -> dict[str, Any]:
    entries = []
    for r in range(1, 19):
        tid, pts = (HOME, home_pts) if r == home_rank else ((AWAY, away_pts) if r == away_rank else (f"t{r}", 30 - r))
        gf, ga = (25, 8) if pts >= 20 else (9, 20)
        entries.append({"team_id": tid, "name": tid, "abbreviation": None, "logo": None, "played": played, "won": 0,
                        "drawn": 0, "lost": 0, "gf": gf, "ga": ga, "gd": gf - ga, "points": pts, "deductions": 0, "rank": r,
                        "note": {"color": "#f00", "description": "Relegation"} if r >= 16 else None})
    return {"season": "2026-27", "group": "Lig", "entries": entries}


def _h2h(results: list[tuple[str, str, int, int]], extra: list[bool] | None = None) -> list[dict[str, Any]]:
    out = []
    for i, (h, a, hg, ag) in enumerate(results):
        out.append({"id": f"h{i}", "date_utc": f"{2026 - i // 2}-03-0{1 + i % 2}T18:00:00Z", "league": "eng.1",
                    "league_name": "Premier League", "home_id": h, "away_id": a, "home_name": h, "away_name": a,
                    "home_goals": hg, "away_goals": ag, "extra_time": bool(extra[i]) if extra else False})
    return out


def _check_shape(r: dict[str, Any]) -> None:
    json.dumps(r, ensure_ascii=False)
    assert r["version"] == SCOUT_VERSION
    assert [s["key"] for s in r["sections"]] == SECTION_ORDER
    texts = []
    for s in r["sections"]:
        assert s["title"]
        if not s["available"]:
            assert s["note"]
        for it in s["items"]:
            assert it["side"] in SIDES
            assert 0.0 <= it["weight"] <= 1.0
            assert it["text"] and it["text"] == it["text"].strip()
            texts.append(it["text"])
    assert len(texts) == len(set(texts)), "aynı cümle raporda iki kez geçmemeli"
    v = r["verdict"]
    assert v["verdict"] in ("oneri", "pas") and v["headline"] and v["reason"]
    if v["verdict"] == "pas":
        assert v["pick"] is None and v["confidence"] is None and v["headline"].startswith("Pas")
    else:
        assert v["confidence"] in ("yüksek", "orta")
        pk = v["pick"]
        assert pk["odd"] > 1 and 0 < pk["p_model"] < 1 and 0 < pk["p_market"] < 1
        assert pk["selection_text"] in v["headline"]


DIRECTION = {("ms", "1"): "home", ("ms", "2"): "away", ("hnd", "1"): "home", ("hnd", "2"): "away",
             ("cs", "1 ve 0"): "home", ("cs", "0 ve 2"): "away", ("au", "Üst"): "over", ("au", "Alt"): "under",
             ("kg", "Var"): "over", ("kg", "Yok"): "under"}


# ---------------------------------------------------------------- gerçek örnekler

def _static_files() -> list[Path]:
    return sorted(STATIC.glob("*.json")) if STATIC.exists() else []


@pytest.mark.skipif(not _static_files(), reason="web/static-data örnekleri yok")
def test_real_payloads_shape_and_model_pick_consistency():
    n_pick = n_pas = 0
    for f in _static_files():
        p = json.loads(f.read_text(encoding="utf-8"))
        r = build_scout(p, form=p.get("form") or {}, standings=None, h2h=[])
        _check_shape(r)
        v = r["verdict"]
        if p.get("covered") and p["model"]["confidence"] in ("düşük", "yok"):
            assert v["verdict"] == "pas", f.name
        if not p.get("iddaa"):
            assert v["verdict"] == "pas", f.name
        if v["verdict"] == "oneri":
            n_pick += 1
            mp = model_pick(p)
            assert mp is not None, f.name
            pk = v["pick"]
            mine = DIRECTION[(pk["key"], pk["selection"])]
            theirs = DIRECTION[(mp.key, mp.outcome_name)]
            if pk["same_as_model_pick"]:
                assert (pk["market_key"], pk["selection"]) == (mp.market_key, mp.outcome_name)
            elif mine in ("over", "under"):
                # gol alternatifi yalnızca model önerisi sonuç ekseninde ise; model önerisiyle aynı eksende çelişemez
                assert theirs in ("home", "away"), f.name
            else:
                assert mine == theirs, f.name  # temkinli karşılık: aynı yön
            # Standings/h2h yokken bağımsız kanıt tek bölümle (form) sınırlı: "yüksek" güven verilmez
            assert v["confidence"] == "orta", f.name
        else:
            n_pas += 1
    assert n_pick > 0 and n_pas > 0


@pytest.mark.skipif(not (STATIC / "401878769.json").exists(), reason="örnek maç yok")
def test_real_payload_with_full_context_gives_high_confidence():
    p = json.loads((STATIC / "401878769.json").read_text(encoding="utf-8"))   # Nottingham Forest – Arsenal
    h, a = p["match"]["home"]["id"], p["match"]["away"]["id"]
    st = _standings(1, 25, 17, 6)
    for e in st["entries"]:
        if e["team_id"] == HOME:
            e["team_id"] = a
        elif e["team_id"] == AWAY:
            e["team_id"] = h
    h2h = _h2h([(a, h, 3, 0), (h, a, 0, 0), (a, h, 2, 1), (h, a, 0, 2)])
    r = build_scout(p, form=p["form"], standings=st, h2h=h2h)
    _check_shape(r)
    v = r["verdict"]
    assert v["verdict"] == "oneri" and v["confidence"] == "yüksek"
    assert v["pick"]["key"] == "ms" and v["pick"]["selection"] == "2"
    assert {"form", "lig", "h2h"} <= set(r["signals"]["result"]["agree"])
    assert "Arsenal" in v["reason"]


@pytest.mark.skipif(not (STATIC / "401874978.json").exists(), reason="örnek maç yok")
def test_real_balanced_match_is_pass():
    p = json.loads((STATIC / "401874978.json").read_text(encoding="utf-8"))   # AC Milan – Atalanta, dengeli
    r = build_scout(p, form=p["form"], standings=None, h2h=[])
    assert r["verdict"]["verdict"] == "pas"
    assert "AC Milan" in r["summary"] and "dengeli" in r["summary"]


# ---------------------------------------------------------------- sentetik durumlar

def test_clear_favourite_with_aligned_signals_recommends():
    p = _payload()
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=_standings(2, 24, 15, 9),
                    h2h=_h2h([(HOME, AWAY, 2, 0), (AWAY, HOME, 0, 1), (HOME, AWAY, 3, 1)]))
    _check_shape(r)
    v = r["verdict"]
    assert v["verdict"] == "oneri" and v["confidence"] == "yüksek"
    pk = v["pick"]
    assert (pk["key"], pk["selection"]) == ("ms", "1")
    assert pk["same_as_model_pick"] is True
    assert pk["p_model"] == pytest.approx(0.62) and pk["odd"] == _odd(0.62)
    assert "Kartal SK" in v["headline"]
    assert r["signals"]["result"]["disagree"] == []


def test_conflicting_signals_pass():
    # Model ev sahibini öne çıkarıyor; form, tablo ve eşleşme geçmişi deplasmanı gösteriyor
    p = _payload()
    r = build_scout(p, form={"home": _form(HOME, BAD), "away": _form(AWAY, GOOD)}, standings=_standings(15, 9, 2, 24),
                    h2h=_h2h([(AWAY, HOME, 2, 0), (HOME, AWAY, 0, 1), (AWAY, HOME, 3, 1)]))
    _check_shape(r)
    v = r["verdict"]
    assert v["verdict"] == "pas"
    assert "çelişiyor" in v["reason"]
    assert {"form", "lig", "h2h"} <= set(r["signals"]["result"]["disagree"])


def test_empty_standings_and_h2h():
    p = _payload()
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=None, h2h=[])
    _check_shape(r)
    secs = {s["key"]: s for s in r["sections"]}
    assert not secs["lig"]["available"] and "Puan durumu yok" in secs["lig"]["note"]
    assert not secs["h2h"]["available"] and secs["h2h"]["items"] == []
    # Bağımsız kanıt yalnızca form: öneri olsa bile "yüksek" güven verilmez
    assert r["verdict"]["confidence"] != "yüksek"
    r2 = build_scout(p, form={}, standings={"season": None, "group": "Lig", "entries": []}, h2h=[])
    _check_shape(r2)
    assert r2["verdict"]["verdict"] == "pas"


def test_teams_missing_from_table_marked_unavailable():
    p = _payload()
    st = _standings(2, 24, 15, 9)
    st["entries"] = [e for e in st["entries"] if e["team_id"] != AWAY]
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=st, h2h=[])
    lig = next(s for s in r["sections"] if s["key"] == "lig")
    assert not lig["available"] and "Martı FK" in lig["note"]


def test_low_confidence_passes_even_with_aligned_signals():
    p = _payload(conf="düşük")
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=_standings(2, 24, 15, 9),
                    h2h=_h2h([(HOME, AWAY, 2, 0), (AWAY, HOME, 0, 1), (HOME, AWAY, 3, 1)]))
    _check_shape(r)
    assert r["verdict"]["verdict"] == "pas" and "veri zayıf" in r["verdict"]["headline"]
    risk = next(s for s in r["sections"] if s["key"] == "risk")
    assert any(it["weight"] >= 1.0 for it in risk["items"])


def test_no_odds_and_not_covered_pass():
    r = build_scout(_payload(with_iddaa=False), form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)},
                    standings=_standings(2, 24, 15, 9), h2h=[])
    assert r["verdict"]["verdict"] == "pas" and "oran" in r["verdict"]["headline"]
    piyasa = next(s for s in r["sections"] if s["key"] == "piyasa")
    assert not piyasa["available"]

    unc = {"match": _payload()["match"], "covered": False, "coverage_note": "Takımlardan en az biri için geçmiş maç verisi yok",
           "model_version": "t", "created_at": "t"}
    r2 = build_scout(unc, form={}, standings=None, h2h=[])
    _check_shape(r2)
    assert r2["verdict"]["verdict"] == "pas" and "kapsam" in r2["verdict"]["headline"]


def test_heavy_favourite_handicap_downgraded_to_match_result_on_medium_evidence():
    # MS oranı < 1.25 -> model_pick handikap seçer; bağımsız kanıt tek bölümse güven orta -> düz maç sonucu
    p = _payload(p1=0.80, p0=0.13, p2=0.07, lh=2.6, la=0.5, hnd1=0.58, sot=(8.0, 2.0))
    mp = model_pick(p)
    assert mp is not None and mp.key == "hnd"
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=None, h2h=[])
    v = r["verdict"]
    assert v["verdict"] == "oneri" and v["confidence"] == "orta"
    assert (v["pick"]["key"], v["pick"]["selection"]) == ("ms", "1")
    assert v["pick"]["same_as_model_pick"] is False
    assert "handikap yerine" in v["reason"]


def test_goals_market_when_result_axis_conflicts():
    p = _payload(over=0.68, kg=0.62, q_over=0.66)
    hot_home = [(3, 2, True), (2, 2, False), (4, 1, True), (1, 3, False), (2, 2, True), (1, 2, False)]
    hot_away = [(3, 1, False), (2, 2, True), (3, 2, False), (2, 1, True), (4, 2, False), (2, 3, True)]
    h2h = _h2h([(AWAY, HOME, 3, 2), (HOME, AWAY, 2, 2), (AWAY, HOME, 4, 1)])
    r = build_scout(p, form={"home": _form(HOME, hot_home), "away": _form(AWAY, hot_away)}, standings=None, h2h=h2h)
    _check_shape(r)
    v = r["verdict"]
    assert v["verdict"] == "oneri" and v["confidence"] == "orta"
    assert v["pick"]["key"] in ("au", "kg") and v["pick"]["selection"] in ("Üst", "Var")
    assert v["pick"]["same_as_model_pick"] is False
    assert "Sonuç tarafında uyum yok" in v["reason"]


def test_extra_time_h2h_counted_as_draw_and_goals_excluded():
    p = _payload()
    h2h = _h2h([(HOME, AWAY, 3, 2), (AWAY, HOME, 1, 1), (HOME, AWAY, 0, 1)], extra=[True, False, False])
    r = build_scout(p, form={"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}, standings=None, h2h=h2h)
    sec = next(s for s in r["sections"] if s["key"] == "h2h")
    rec = sec["items"][0]["text"]
    assert "Kartal SK 0" in rec and "Martı FK 1" in rec and "2 maç berabere" in rec
    goals = next(it for it in sec["items"] if "maç başına" in it["text"])
    assert "1.5 gol" in goals["text"]   # uzatmalı maçın 5 golü ortalamaya girmez: (2 + 1) / 2
    assert "uzatmalı" in sec["items"][1]["text"]


def test_similar_odds_used_and_low_sample_ignored():
    p = _payload()
    form = {"home": _form(HOME, GOOD), "away": _form(AWAY, BAD)}
    sim_ok = {"n": 140, "low_sample": False, "outcomes": {"1": 0.72, "0": 0.18, "2": 0.10}, "over25": 0.61, "btts": 0.4}
    piy = next(s for s in build_scout(p, form=form, standings=None, h2h=[], similar=sim_ok)["sections"] if s["key"] == "piyasa")
    assert any("Benzer oranlı 140" in it["text"] and it["side"] == "home" for it in piy["items"])
    assert any("2.5 Üst oranı %61" in it["text"] and it["side"] == "goals_over" for it in piy["items"])
    sim_low = {"n": 12, "low_sample": True, "outcomes": {"1": 0.9, "0": 0.05, "2": 0.05}}
    piy2 = next(s for s in build_scout(p, form=form, standings=None, h2h=[], similar=sim_low)["sections"] if s["key"] == "piyasa")
    sim_items = [it for it in piy2["items"] if "Benzer oranlı" in it["text"]]
    assert sim_items and all(it["side"] == "neutral" for it in sim_items)
    # Eşleşen maçlarda piyasa zaten bunu bekliyorduysa (pool_implied) ya da güven aralığı tutmuyorsa yön sinyali yok
    sim_pool = {**sim_ok, "pool_implied": {"1": 0.70, "0": 0.19, "2": 0.11}}
    piy_pool = next(s for s in build_scout(p, form=form, standings=None, h2h=[], similar=sim_pool)["sections"] if s["key"] == "piyasa")
    assert all(it["side"] == "neutral" for it in piy_pool["items"] if "Benzer oranlı" in it["text"])
    sim_ci = {**sim_ok, "outcomes_ci95": {"1": [0.60, 0.80], "0": [0.1, 0.25], "2": [0.05, 0.15]}}
    piy_ci = next(s for s in build_scout(p, form=form, standings=None, h2h=[], similar=sim_ci)["sections"] if s["key"] == "piyasa")
    assert all(it["side"] == "neutral" for it in piy_ci["items"] if "Benzer oranlı" in it["text"])
    piy3 = next(s for s in build_scout(p, form=form, standings=None, h2h=[], similar={"foo": 1})["sections"] if s["key"] == "piyasa")
    assert not any("Benzer" in it["text"] for it in piy3["items"])


def test_cup_and_congestion_risks():
    p = _payload(league="uefa.champions")
    home_form = _form(HOME, GOOD, start_day=16)   # son maç 16 Ekim, başlama 18 Ekim -> 2 gün
    r = build_scout(p, form={"home": home_form, "away": _form(AWAY, BAD)}, standings=None, h2h=[])
    risk = next(s for s in r["sections"] if s["key"] == "risk")
    texts = " ".join(it["text"] for it in risk["items"])
    assert "Premier League maçı" in texts and "yorgunluk" in texts
    assert r["risk_total"] == pytest.approx(0.55)
    assert r["verdict"]["confidence"] != "yüksek"
