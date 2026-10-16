from __future__ import annotations

import sqlite3

import pytest

from app import db
from app.league_info import standings_asof
from app.scout_backtest import AU25_KEY, MS_KEY, _find_fd, _market_rows, _summ
from app.sources import footballdata as fd


def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    for col in ("neutral", "extra_time", "ft90_home", "ft90_away"):
        con.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    return con


def _match(con: sqlite3.Connection, mid: str, date: str, h: str, a: str, hg: int | None, ag: int | None,
           league: str = "tur.1", season: int = 2026) -> None:
    con.execute(
        """INSERT INTO matches(id, league, season, date_utc, state, completed, home_id, away_id, home_goals, away_goals,
                               scoreboard_fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,'x')""",
        (mid, league, season, date, "post" if hg is not None else "pre", int(hg is not None), h, a, hg, ag),
    )


def test_standings_asof_uses_only_earlier_results():
    con = _mem_db()
    con.execute("INSERT INTO teams(id, name) VALUES('A','Alfa'),('B','Beta'),('C','Gama')")
    _match(con, "1", "2026-08-10T17:00:00Z", "A", "B", 2, 0)
    _match(con, "2", "2026-08-17T17:00:00Z", "B", "C", 1, 1)
    _match(con, "3", "2026-08-24T17:00:00Z", "C", "A", 3, 0)   # hedef tarihten sonra: sayılmaz
    _match(con, "4", "2025-05-01T17:00:00Z", "C", "B", 5, 0, season=2025)  # önceki sezon: sayılmaz
    t = standings_asof(con, "tur.1", "C", "A", "2026-08-24T17:00:00Z")
    assert t is not None
    rows = {e["team_id"]: e for e in t["entries"]}
    assert rows["A"]["points"] == 3 and rows["A"]["rank"] == 1
    assert rows["B"]["points"] == 1 and rows["B"]["played"] == 2 and rows["B"]["gd"] == -2
    assert rows["C"]["points"] == 1 and rows["C"]["played"] == 1
    assert [e["team_id"] for e in t["entries"]] == ["A", "C", "B"]  # eşit puanda averaj
    assert standings_asof(con, "uefa.champions", "A", "B", "2026-08-24T17:00:00Z") is None


def _fd_row(**kw: object) -> dict:
    base = {"league": "eng.1", "date": "2026-03-01", "home": "Man United", "away": "Chelsea", "hg": 2, "ag": 1,
            "o1": 2.1, "ox": 3.4, "o2": 3.5, "o_over25": 1.8, "o_under25": 2.05}
    base.update(kw)
    return base


def test_find_fd_requires_same_score_and_similar_names():
    m = {"league": "eng.1", "date_utc": "2026-03-01T15:00:00Z", "hn": "Manchester United", "an": "Chelsea", "hg": 2, "ag": 1}
    good = _fd_row()
    idx = {("eng.1", "2026-03-01"): [_fd_row(hg=0, ag=0), good]}
    assert _find_fd(m, idx) is good  # type: ignore[arg-type]
    idx_next_day = {("eng.1", "2026-03-02"): [good]}
    assert _find_fd(m, idx_next_day) is good  # type: ignore[arg-type]
    assert _find_fd(m, {("eng.1", "2026-03-01"): [_fd_row(home="Arsenal", away="Fulham")]}) is None  # type: ignore[arg-type]


def test_market_rows_ms_and_optional_au():
    rows = _market_rows(_fd_row(), "2026-03-01T15:00:00Z")  # type: ignore[arg-type]
    assert [(r["market_key"], r["outcome_name"]) for r in rows] == [
        (MS_KEY, "1"), (MS_KEY, "0"), (MS_KEY, "2"), (AU25_KEY, "Alt"), (AU25_KEY, "Üst")]
    assert len(_market_rows(_fd_row(o_over25=None, o_under25=None), "x")) == 3  # type: ignore[arg-type]


def test_summ_roi_and_edge():
    recs = [{"won": True, "odd": 2.0, "odd_iddaa": 1.8, "p_model": 0.55, "p_market": 0.48, "profit": 1.0, "profit_iddaa": 0.8},
            {"won": False, "odd": 2.0, "odd_iddaa": 1.8, "p_model": 0.55, "p_market": 0.48, "profit": -1.0, "profit_iddaa": -1.0}]
    s = _summ(recs)
    assert s["n"] == 2 and s["hit_rate"] == 0.5
    assert s["roi_close"] == pytest.approx(0.0) and s["roi_iddaa"] == pytest.approx(-0.1)
    assert s["edge_vs_market"] == pytest.approx(0.02)
    lo, hi = s["roi_iddaa_ci95"]
    assert lo <= s["roi_iddaa"] <= hi
    assert _summ([]) == {"n": 0}


def test_football_data_ou25_parsing_prefers_closing():
    header = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA,Avg>2.5,Avg<2.5,AvgC>2.5,AvgC<2.5"
    text = f"{header}\nE0,01/03/2026,Man United,Chelsea,2,1,2.10,3.40,3.50,1.90,1.95,1.80,2.05\n"
    m = fd.parse_csv(text, "eng.1")[0]
    assert (m.o_over25, m.o_under25) == (1.80, 2.05)
    text2 = "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,AvgCH,AvgCD,AvgCA\nE0,01/03/2026,A,B,0,0,2.1,3.4,3.5\n"
    assert fd.parse_csv(text2, "eng.1")[0].o_over25 is None
