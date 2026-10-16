"""xG (Understat) ayrıştırma, ESPN eşleştirme, toplama ve modele etkisi: ağsız birim testleri."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any

import numpy as np
import pytest

from app import db
from app.backtest import match_goal_losses, paired_bootstrap, Pred
from app.model.goals import fit_goal_model, load_matches, result_cutoff, sot_composite, xg_composite
from app.model.pipeline import load_params
from app.sources import understat as us
from app.xg import EspnMatch, ingest_xg, match_rows, window_seasons


def _us_row(mid: str, dt: str, h: str, a: str, hg: Any, ag: Any, xh: Any, xa: Any, done: bool = True) -> dict[str, Any]:
    return {"id": mid, "isResult": done, "h": {"id": "1", "title": h, "short_title": h[:3].upper()},
            "a": {"id": "2", "title": a, "short_title": a[:3].upper()}, "goals": {"h": hg, "a": ag},
            "xG": {"h": xh, "a": xa}, "datetime": dt}


# ------------------------------------------------------------------ ayrıştırma

def test_parse_league_data_keeps_only_finished_matches_with_xg():
    payload = {"teams": {}, "players": [], "dates": [
        _us_row("1", "2025-08-15 19:00:00", "Liverpool", "Bournemouth", "4", "2", "2.42", "0.83"),
        _us_row("2", "2025-08-16 11:30:00", "Aston Villa", "Newcastle United", None, None, None, None, done=False),
        _us_row("3", "2025-08-16 14:00:00", "Brighton", "Fulham", "1", "1", None, "0.5"),   # xG eksik
        _us_row("4", "2025-08-16 14:00:00", "Sunderland", "West Ham", "3", "0", "1.1", "abc"),  # bozuk sayı
    ]}
    rows = us.parse_league_data(payload)
    assert len(rows) == 1
    r = rows[0]
    assert (r.us_id, r.home, r.away, r.hg, r.ag) == ("1", "Liverpool", "Bournemouth", 4, 2)
    assert r.xg_home == pytest.approx(2.42) and r.xg_away == pytest.approx(0.83)


def test_parse_league_data_rejects_unexpected_shape():
    with pytest.raises(ValueError):
        us.parse_league_data({"teams": {}})
    with pytest.raises(ValueError):
        us.parse_league_data([1, 2])


def test_parse_league_html_decodes_hex_escaped_json_and_utf8_names():
    data = [_us_row("9", "2024-08-18 17:30:00", "Atlético Madrid", "Villarreal", "2", "2", "1.9", "1.2")]
    js = json.dumps(data, ensure_ascii=False).encode("utf-8")
    escaped = "".join(f"\\x{b:02X}" if (b < 0x30 or b > 0x7A or chr(b) in "\"'[]{}:,") else chr(b) for b in js)
    html = f"<script>\n var datesData \t= JSON.parse('{escaped}');\n</script>"
    rows = us.parse_league_html(html)
    assert len(rows) == 1 and rows[0].home == "Atlético Madrid" and rows[0].xg_home == pytest.approx(1.9)
    with pytest.raises(ValueError):
        us.parse_league_html("<html>yeni site, veri yok</html>")


def test_league_urls_and_seasons():
    assert us.league_data_url("La liga", 2025) == "https://understat.com/getLeagueData/La%20liga/2025"
    assert us.season_start_year(date(2026, 6, 30)) == 2025 and us.season_start_year(date(2026, 7, 1)) == 2026
    assert us.season_finished(2025, date(2026, 7, 1)) and not us.season_finished(2026, date(2026, 10, 16))
    assert window_seasons(date(2026, 10, 16)) == [2024, 2025, 2026]  # 27 aylık pencere: 2024-07'den beri


# ------------------------------------------------------------------ eşleştirme

def _em(mid: str, dt: str, h: str, a: str, hg: int, ag: int) -> EspnMatch:
    return EspnMatch(mid, datetime.fromisoformat(dt).replace(tzinfo=timezone.utc), h, a, hg, ag)


def _um(dt: str, h: str, a: str, hg: int, ag: int, xh: float = 1.0, xa: float = 1.0, uid: str = "u") -> us.UsMatch:
    return us.UsMatch(uid, dt, h, a, hg, ag, xh, xa)


def test_match_rows_uses_league_date_names_and_score():
    espn = [
        _em("e1", "2025-01-11T14:30:00", "RB Leipzig", "Borussia Mönchengladbach", 2, 0),
        _em("e2", "2025-01-11T14:30:00", "1. FC Union Berlin", "VfL Bochum", 0, 2),   # skor uyuşmuyor (hükmen)
        _em("e3", "2025-01-12T23:30:00", "Bayern Munich", "VfL Wolfsburg", 3, 1),     # Understat'te ertesi gün
        _em("e4", "2025-01-11T14:30:00", "Werder Bremen", "Mainz", 1, 1),
    ]
    rows = [
        _um("2025-01-11 14:30:00", "RasenBallsport Leipzig", "Borussia M.Gladbach", 2, 0, 1.8, 0.4, "a"),
        _um("2025-01-11 14:30:00", "Union Berlin", "Bochum", 1, 1, 1.2, 0.9, "b"),
        _um("2025-01-13 00:30:00", "Bayern Munich", "Wolfsburg", 3, 1, 2.9, 0.7, "c"),
        _um("2025-01-11 14:30:00", "Freiburg", "Hoffenheim", 1, 1, 1.0, 1.0, "d"),     # aynı skor, başka takımlar
    ]
    got = match_rows(espn, rows)
    assert set(got) == {"e1", "e3"}
    assert got["e1"][0].us_id == "a" and got["e3"][0].us_id == "c"


def test_match_rows_assigns_each_row_once():
    espn = [_em("e1", "2025-03-01T15:00:00", "Lens", "Lille", 1, 0),
            _em("e2", "2025-03-02T15:00:00", "Lens", "Lille", 1, 0)]  # (yapay) aynı eşleşme iki gün
    rows = [_um("2025-03-01 15:00:00", "Lens", "Lille", 1, 0, uid="x")]
    got = match_rows(espn, rows)
    assert list(got) == ["e1"]  # aynı gün tercih edilir, satır ikinci kez kullanılmaz


# ------------------------------------------------------------------ toplama (sahte getirici)

def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    for col in ("neutral", "extra_time"):
        con.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    for col in ("ft90_home", "ft90_away"):
        con.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER")
    return con


def _add_match(con: sqlite3.Connection, mid: str, league: str, dt: str, h: str, a: str, hg: int, ag: int) -> None:
    con.execute(
        """INSERT INTO matches(id, league, season, date_utc, state, completed, home_id, away_id, home_goals, away_goals,
                               scoreboard_fetched_at, ft90_home, ft90_away) VALUES(?,?,?,?,'post',1,?,?,?,?,'x',?,?)""",
        (mid, league, 2025, dt, h, a, hg, ag, hg, ag),
    )


def test_ingest_xg_matches_stores_and_skips_finished_seasons():
    con = _mem_db()
    con.execute("INSERT INTO teams(id, name) VALUES('t1','Arsenal'),('t2','Chelsea'),('t3','Real Madrid'),('t4','Sevilla')")
    _add_match(con, "m1", "eng.1", "2025-09-20T14:00:00Z", "t1", "t2", 2, 1)
    _add_match(con, "m2", "esp.1", "2026-09-19T19:00:00Z", "t3", "t4", 0, 0)
    calls: list[str] = []

    async def fake(url: str, referer: str) -> Any | None:
        calls.append(url)
        assert referer.startswith("https://understat.com/league/")
        if "/EPL/2025" in url:
            return {"dates": [_us_row("10", "2025-09-20 14:00:00", "Arsenal", "Chelsea", "2", "1", "1.7", "0.6")]}
        if "/La_liga/" in url:
            return None  # eski ad yoksa yeni (boşluklu) ad denenir
        if "/La%20liga/2026" in url:
            return {"dates": [_us_row("20", "2026-09-19 19:00:00", "Real Madrid", "Sevilla", "0", "0", "2.1", "0.3")]}
        return {"dates": []}

    logs: list[str] = []
    res = asyncio.run(ingest_xg(con, logs.append, fetch=fake, today=date(2026, 10, 16)))
    assert res["errors"] == 0 and res["total"] == 2
    rows = {r["match_id"]: (r["xg_home"], r["xg_away"], r["source"]) for r in con.execute("SELECT * FROM match_xg")}
    assert rows == {"m1": (1.7, 0.6, "understat"), "m2": (2.1, 0.3, "understat")}
    assert db.meta_get(con, "xg:understat:eng.1:2025")["final"] is True
    assert db.meta_get(con, "xg:understat:eng.1:2026")["final"] is False
    # İkinci çalıştırma (12 saat dolmadan): hiçbir istek yok; dolunca yalnız güncel sezon (6 lig)
    calls.clear()
    asyncio.run(ingest_xg(con, logs.append, fetch=fake, today=date(2026, 10, 16)))
    assert calls == []
    asyncio.run(ingest_xg(con, logs.append, fetch=fake, today=date(2026, 10, 16), refresh_hours=0.0))
    assert all(u.endswith("/2026") for u in calls) and len({u.split("/")[4] for u in calls}) >= 6


def test_ingest_xg_raises_when_every_request_fails():
    con = _mem_db()

    async def broken(url: str, referer: str) -> Any | None:
        raise RuntimeError("bağlantı sıfırlandı")

    with pytest.raises(RuntimeError):
        asyncio.run(ingest_xg(con, lambda m: None, fetch=broken, today=date(2026, 10, 16)))


# ------------------------------------------------------------------ model

def _synthetic_db(with_xg: bool) -> sqlite3.Connection:
    con = _mem_db()
    rng = np.random.default_rng(3)
    teams = [f"T{i}" for i in range(8)]
    strength = {t: s for t, s in zip(teams, np.linspace(-0.4, 0.4, len(teams)))}
    d0 = datetime(2025, 8, 1, 15, 0, tzinfo=timezone.utc)
    k = 0
    for rnd in range(30):
        order = rng.permutation(teams)
        for i in range(0, len(order), 2):
            h, a = str(order[i]), str(order[i + 1])
            lh, la = np.exp(0.25 + strength[h] - strength[a]), np.exp(strength[a] - strength[h])
            hg, ag = int(rng.poisson(lh)), int(rng.poisson(la))
            mid = f"m{k}"
            dt = (d0 + timedelta(days=7 * rnd)).strftime("%Y-%m-%dT%H:%M:%SZ")
            _add_match(con, mid, "eng.1", dt, h, a, hg, ag)
            for side, team, g in ((1, h, hg), (0, a, ag)):
                con.execute("INSERT INTO team_match_stats(match_id, team_id, is_home, shots, shots_on_target) VALUES(?,?,?,?,?)",
                            (mid, team, side, 10, g + int(rng.integers(0, 4))))
            xh, xa = float(lh * rng.uniform(0.8, 1.2)), float(la * rng.uniform(0.8, 1.2))  # iki durumda da aynı RNG akışı
            if with_xg and k % 2 == 0:
                con.execute("INSERT INTO match_xg VALUES(?,?,?,?,?,?)", (mid, xh, xa, "understat", mid, "x"))
            k += 1
    return con


AS_OF = datetime(2026, 3, 10, tzinfo=timezone.utc)


def test_xg_weight_zero_is_bit_identical_to_model_without_xg():
    a, _, _ = fit_goal_model(_synthetic_db(with_xg=True), AS_OF, 0.0025, 0.5, 0.4, 0.3)
    b, _, _ = fit_goal_model(_synthetic_db(with_xg=False), AS_OF, 0.0025, 0.5, 0.4, 0.3, 1.0, 1.0, 0.0)
    assert np.array_equal(a.counts.att, b.counts.att) and np.array_equal(a.counts.defn, b.counts.defn)
    assert a.rho == b.rho and a.counts.mu == b.counts.mu and a.xg_weight == 0.0
    # xG verisi olan veritabanında da w=0 bileşik hedef sot_composite'in kendisidir
    con = _synthetic_db(with_xg=True)
    before = result_cutoff(AS_OF)
    ms = load_matches(con, before)
    assert xg_composite(con, ms, before, 0.3, 0.0) == sot_composite(con, ms, before, 0.3)


def test_xg_weight_changes_targets_only_for_matches_with_xg():
    con = _synthetic_db(with_xg=True)
    before = result_cutoff(AS_OF)
    ms = load_matches(con, before)
    base = sot_composite(con, ms, before, 0.3)
    full = xg_composite(con, ms, before, 0.3, 1.0)
    assert base is not None and full is not None
    xg = {r["match_id"]: (r["xg_home"], r["xg_away"]) for r in con.execute("SELECT * FROM match_xg")}
    for m in ms:
        if m.id in xg:
            # w=1: hedef = lig ölçeği x xG (ölçek iki taraf için aynı)
            r_h, r_a = full[m.id][0] / xg[m.id][0], full[m.id][1] / xg[m.id][1]
            assert r_h == pytest.approx(r_a) and 0.5 < r_h < 2.0
        else:
            assert full[m.id] == base[m.id]
    g1, _, _ = fit_goal_model(con, AS_OF, 0.0025, 0.5, 0.4, 0.3, xg_weight=0.5)
    g0, _, _ = fit_goal_model(con, AS_OF, 0.0025, 0.5, 0.4, 0.3)
    assert g1.xg_weight == 0.5 and not np.array_equal(g1.counts.att, g0.counts.att)


def test_load_params_adds_xg_weight_only_when_validated():
    con = _mem_db()
    db.meta_set(con, "model_params", {"xi": 0.004, "sigma": 0.5, "tau": 0.4, "alpha": 0.3, "cal_t": 1.0, "cal_g": 1.0})
    assert "xg_weight" not in load_params(con)
    db.meta_set(con, "model_params", {"xi": 0.004, "sigma": 0.5, "tau": 0.4, "alpha": 0.3, "xg_weight": 0.5})
    assert load_params(con)["xg_weight"] == 0.5
    db.meta_set(con, "model_params", {"xi": 0.004, "xg_weight": 0.0})
    assert "xg_weight" not in load_params(con)


def test_paired_bootstrap_detects_consistent_gain():
    preds_a = [Pred(f"m{i}", "eng.1", "ms", [0.4, 0.3, 0.3], 0, [1 / 3] * 3, None) for i in range(200)]
    preds_b = [Pred(f"m{i}", "eng.1", "ms", [0.5, 0.25, 0.25], 0, [1 / 3] * 3, None) for i in range(200)]
    la, lb = match_goal_losses(preds_a), match_goal_losses(preds_b)
    res = paired_bootstrap(la, lb)
    assert res["n"] == 200 and res["mean_gain"] == pytest.approx(np.log(0.5) - np.log(0.4))
    assert res["p_better"] == 1.0 and res["ci90"][0] > 0
    same = paired_bootstrap(la, la)
    assert same["mean_gain"] == 0.0 and same["p_better"] == 0.0
