from __future__ import annotations

import itertools
import math
import sqlite3

import pytest

from app import db
from app.league_info import head_to_head, match_standings
from app.sources import espn
from app.sources import sportoto as src
from app.sportoto import OUTCOMES, hit_distribution, optimize, split_event_name, winning_columns


# ---------------------------------------------------------------- Spor Toto

def _brute_best(probs: list[dict[str, float]], max_cols: int) -> float:
    ranked = [sorted(OUTCOMES, key=lambda o: -p[o]) for p in probs]
    best = -math.inf
    for sizes in itertools.product((1, 2, 3), repeat=len(probs)):
        if math.prod(sizes) > max_cols:
            continue
        v = sum(math.log(sum(p[o] for o in r[:s])) for p, r, s in zip(probs, ranked, sizes))
        best = max(best, v)
    return best


@pytest.mark.parametrize("max_cols", [1, 2, 6, 12, 30])
def test_optimize_matches_brute_force(max_cols: int):
    probs = [
        {"1": 0.5, "0": 0.3, "2": 0.2}, {"1": 0.36, "0": 0.30, "2": 0.34}, {"1": 0.7, "0": 0.2, "2": 0.1},
        {"1": 0.4, "0": 0.25, "2": 0.35}, {"1": 0.2, "0": 0.25, "2": 0.55}, {"1": 0.34, "0": 0.33, "2": 0.33},
    ]
    picks = optimize(probs, max_cols)
    assert math.prod(len(s) for s in picks) <= max_cols
    got = sum(math.log(sum(p[o] for o in s)) for p, s in zip(probs, picks))
    assert got == pytest.approx(_brute_best(probs, max_cols))
    # İşaretlenenler her zaman en olası sonuçlardır
    for p, s in zip(probs, picks):
        assert sorted(s, key=lambda o: -p[o]) == sorted(OUTCOMES, key=lambda o: -p[o])[: len(s)]


def test_optimize_budget_300_columns_15_matches():
    probs = [{"1": 0.45, "0": 0.28, "2": 0.27}] * 15
    picks = optimize(probs, 300)
    cols = math.prod(len(s) for s in picks)
    assert cols <= 300 and cols >= 216  # bütçenin anlamlı kısmı kullanılır


def test_hit_distribution_sums_to_one():
    d = hit_distribution([0.5, 0.8, 1.0])
    assert sum(d) == pytest.approx(1.0)
    assert d[0] == 0.0 and d[3] == pytest.approx(0.4)


def test_winning_columns_counts_by_enumeration():
    picks = [["1"], ["1", "0"], ["1", "0", "2"], ["2"]] + [["1"]] * 11
    winners = ["1", "2", "0", "2"] + ["1"] * 11
    counts = {k: 0 for k in (15, 14, 13, 12)}
    for col in itertools.product(*picks):
        k = sum(1 for c, w in zip(col, winners) if c == w)
        if k in counts:
            counts[k] += 1
    assert winning_columns(picks, winners) == {k: v for k, v in counts.items() if v}


def test_split_event_name_variants():
    assert split_event_name("Galatasaray A.Ş. - Kasımpaşa A.Ş.") == [("Galatasaray", "Kasımpaşa")]
    assert ("Fenerbahçe", "Alanyaspor") in split_event_name("Fenerbahçe A.Ş.-Alanyaspor")
    assert ("Paris Saint-Germain", "Lyon") in split_event_name("Paris Saint-Germain-Lyon")


def test_parse_week_and_turkish_numbers():
    payload = {"isSuccess": True, "data": {
        "payinBeginDate": "2026-10-04T10:00:00", "payinEndDate": "2026-10-09T19:55:00", "gameCycleNo": 361,
        "programName": "09-12 Ekim",
        "dividends": [{"ordinalNumber": 1, "winners": "29", "amount": "1.457.880,74"},
                      {"ordinalNumber": 4, "winners": "98.413", "amount": "306,85"}],
        "events": [{"eventNo": 2, "eventName": "B-C", "competitionName": "SÜPL", "eventDate": "2026-10-10T13:30:00",
                    "result": "2:2", "winner": "0"},
                   {"eventNo": 1, "eventName": "A-D", "competitionName": "SÜPL", "eventDate": "2026-10-09T20:00:00",
                    "result": None, "winner": None}]}}
    w = src.parse_week(payload)
    assert w is not None and w.cycle_no == 361
    assert w.payin_end_utc == "2026-10-09T16:55:00Z"  # TR yerel saat -> UTC
    assert [e.event_no for e in w.events] == [1, 2] and w.events[1].winner == "0" and w.events[0].winner is None
    assert w.dividends == [{"tier": 15, "winners": 29, "amount": 1457880.74}, {"tier": 12, "winners": 98413, "amount": 306.85}]
    assert src.parse_week({"isSuccess": False, "data": None}) is None


# ---------------------------------------------------------------- puan durumu ve karşılıklı geçmiş

def _standings_payload() -> dict:
    def entry(tid: str, rank: int, pts: int, note: dict | None = None) -> dict:
        stats = [{"name": "rank", "value": rank}, {"name": "points", "value": pts}, {"name": "gamesPlayed", "value": 7},
                 {"name": "pointDifferential", "value": 3}, {"name": "deductions", "value": 0}]
        return {"team": {"id": tid, "displayName": f"T{tid}", "logos": [{"href": "x.png"}]}, "stats": stats, "note": note}

    return {"season": {"displayName": "2026-27", "year": 2026}, "children": [
        {"name": "Doğu", "standings": {"entries": [entry("2", 2, 10), entry("1", 1, 12, {"color": "#0f0", "description": "Promotion"})]}},
        {"name": "Batı", "standings": {"entries": [entry("3", 1, 14)]}},
    ]}


def test_parse_standings_sorted_groups():
    t = espn.parse_standings(_standings_payload())
    assert t is not None and t["season"] == "2026-27"
    assert [g["name"] for g in t["groups"]] == ["Doğu", "Batı"]
    assert [e["team_id"] for e in t["groups"][0]["entries"]] == ["1", "2"]
    assert t["groups"][0]["entries"][0]["note"] == {"color": "#0f0", "description": "Promotion"}
    assert espn.parse_standings({"children": []}) is None


def _mem_db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    for col in ("neutral", "extra_time", "ft90_home", "ft90_away"):
        con.execute(f"ALTER TABLE matches ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    return con


def test_match_standings_picks_group_with_teams():
    con = _mem_db()
    t = espn.parse_standings(_standings_payload())
    db.meta_set(con, "standings:usa.1", {**t, "fetched_at": "2026-10-16T00:00:00Z"})
    ms = match_standings(con, "usa.1", "3", "9")
    assert ms is not None and ms["group"] == "Batı"
    assert match_standings(con, "usa.1", "7", "8") is None
    assert match_standings(con, "eng.fa", "1", "2") is None


def test_head_to_head_merges_db_and_history_without_duplicates():
    con = _mem_db()
    con.execute("INSERT INTO teams(id, name) VALUES('1','Ev'),('2','Dep')")
    con.execute(
        """INSERT INTO matches(id, league, date_utc, state, completed, home_id, away_id, home_goals, away_goals,
                               scoreboard_fetched_at) VALUES('m1','tur.1','2026-03-01T17:00:00Z','post',1,'2','1',1,1,'x')""")
    rows = [
        ("m1", "2026-03-01T17:00:00Z", "tur.1", "2", "1", 1, 1),  # ana tabloda da var -> tek sayılır
        ("h1", "2023-09-01T17:00:00Z", "tur.1", "1", "2", 2, 0),
        ("h2", "2023-07-01T17:00:00Z", "club.friendly", "1", "2", 5, 0),  # hazırlık maçı sayılmaz
        ("h3", "2027-01-01T17:00:00Z", "tur.1", "1", "2", 0, 3),  # maç tarihinden sonra
    ]
    for r in rows:
        con.execute(
            """INSERT INTO h2h_history(id, date_utc, league, home_id, away_id, home_goals, away_goals, home_name, away_name)
               VALUES(?,?,?,?,?,?,?,'Ev','Dep')""", r)
    h = head_to_head(con, "1", "2", "2026-10-18T17:00:00Z")
    assert [x["id"] for x in h] == ["m1", "h1"]
    assert h[0]["league_name"] == "Türkiye · Süper Lig"
