from __future__ import annotations

import asyncio
import sqlite3
from datetime import date

import pytest

from app import db, similar_odds as so
from app.model.markets import devig
from app.sources import footballdata as fd

# Gerçek dosyalardan kısaltılmış başlık/satır örnekleri
MAIN_2627 = (
    "﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,B365H,B365D,B365A,AvgH,AvgD,AvgA,"
    "B365CH,B365CD,B365CA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA\n"
    "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,2,0,H,1.2,7,13,1.19,6.77,14.19,1.18,7.5,13,1.23,7.4,18,1.2,6.72,14\n"
    "E0,12/10/2026,20:00,Coventry,Newcastle,4,1,H,1,0,H,3.3,3.7,2.1,3.25,3.58,2.08,3.6,3.75,1.95,3.85,3.85,2.04,3.54,3.72,1.97\n"
)
MAIN_1516 = (
    "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,HTHG,HTAG,HTR,Referee,B365H,B365D,B365A,PSH,PSD,PSA,"
    "Bb1X2,BbMxH,BbAvH,BbMxD,BbAvD,BbMxA,BbAvA,PSCH,PSCD,PSCA,,,\n"
    "E0,08/08/15,Bournemouth,Aston Villa,0,1,A,0,0,D,M Clattenburg,2,3.6,4,1.95,3.65,4.27,45,2.1,1.96,3.65,3.48,4.33,3.98,1.82,3.88,4.7,,,\n"
    "E0,09/08/15,Chelsea,Swansea,2,2,D,2,1,H,M Oliver,1.36,5,11,1.39,5.03,10.97,45,1.4,1.36,5.25,4.88,11.5,10.27,,,,,,\n"
    ",,,,,,,,,,,,,,,,,,,,,,,,,,,,\n"
)
EXTRA = (
    "﻿Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA,"
    "BFECH,BFECD,BFECA,B365CH,B365CD,B365CA\n"
    "Argentina,Liga Profesional ,2012/2013,03/08/2012,23:00,Arsenal Sarandi,Union de Santa Fe,1,0,H,1.9,3.39,5.03,1.9,3.5,5.68,1.76,3.3,4.74,,,,,,\n"
    "Argentina,Liga Profesional,2026,12/10/2026,22:30,Gimnasia Mendoza,Newells Old Boys,1,0,H,,,,2.45,3.2,3.25,2.39,3.05,3.04,2.58,3.15,3.25,2.45,3,3.25\n"
    "Argentina,Liga Profesional,2026,13/10/2026,22:30,Boca Juniors,River Plate,,,,,,,,,,,,,,,,,,\n"
)


def test_parse_main_modern_prefers_closing_avg():
    ms = fd.parse_csv(MAIN_2627, "eng.1")
    assert len(ms) == 2
    m = ms[1]
    assert (m.date, m.home, m.away, m.hg, m.ag, m.hthg, m.htag) == ("2026-10-12", "Coventry", "Newcastle", 4, 1, 1, 0)
    assert (m.odds_src, m.o1, m.ox, m.o2) == ("AvgC", 3.54, 3.72, 1.97)


def test_parse_main_old_falls_back_when_closing_missing():
    ms = fd.parse_csv(MAIN_1516, "eng.1")
    assert len(ms) == 2  # boş satır atlandı
    assert ms[0].date == "2015-08-08" and ms[0].odds_src == "PSC" and ms[0].o1 == 1.82
    # kapanış (PSC) boş -> açılış pazar ortalaması (BbAv)
    assert ms[1].odds_src == "BbAv" and (ms[1].o1, ms[1].ox, ms[1].o2) == (1.36, 4.88, 10.27)
    assert (ms[1].hthg, ms[1].htag) == (2, 1)


def test_parse_extra_league_format_and_min_date():
    ms = fd.parse_csv(EXTRA, "arg.1")
    assert len(ms) == 2  # skoru olmayan (oynanmamış) satır atlandı
    assert ms[0].odds_src == "AvgC" and ms[0].o1 == 1.76 and ms[0].hthg is None
    assert ms[1].odds_src == "AvgC" and ms[1].home == "Gimnasia Mendoza" and ms[1].date == "2026-10-12"
    assert [m.date for m in fd.parse_csv(EXTRA, "arg.1", min_date="2017-07-01")] == ["2026-10-12"]


def test_decode_and_dates_and_bad_odds():
    assert fd.decode_csv(b"\xef\xbb\xbfDiv,Date\n") == "Div,Date\n"
    assert fd.decode_csv("Deportivo Alavés".encode("cp1252")) == "Deportivo Alavés"
    assert fd.parse_date("08/08/15") == "2015-08-08"
    assert fd.parse_date("21/08/2026") == "2026-08-21"
    assert fd.parse_date("2024-08-16") == "2024-08-16"
    assert fd.parse_date("31/02/2026") is None
    # ters toplamı 1'in altında (Max gibi) ya da aşırı marjlı üçlü atlanır, sıradakine geçilir
    assert fd.pick_odds({"AvgCH": "3", "AvgCD": "4", "AvgCA": "4", "B365H": "2", "B365D": "3.4", "B365A": "3.8"}) == (
        "B365", 2.0, 3.4, 3.8)
    assert fd.pick_odds({"AvgCH": "1.0", "AvgCD": "3", "AvgCA": "3"}) is None


def test_season_codes():
    assert fd.season_code(2026) == "2627" and fd.season_code(2009) == "0910"
    assert fd.season_start_year(date(2026, 10, 16)) == 2026
    assert fd.season_start_year(date(2027, 3, 1)) == 2026


@pytest.fixture()
def con() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    c.executescript(so.SCHEMA_SQL)
    for table, column, ddl in db.MIGRATIONS:  # db.init_db ile aynı sıra: şema, sonra eksik sütunlar
        if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
            c.execute(ddl)
    return c


def _add(c: sqlite3.Connection, key: str, odds: tuple[float, float, float], hg: int, ag: int, *,
         source: str = so.SOURCE_FD, league: str = "eng.1", d: str = "2024-01-01",
         ht: tuple[int, int] | None = None) -> None:
    f = devig(list(odds))
    c.execute(so._INSERT, (source, key, league, d, f"H{key}", f"A{key}", hg, ag, ht[0] if ht else None,
                           ht[1] if ht else None, *odds, *f, "AvgC"))


def _scaled(target: tuple[float, float, float], k1: float) -> tuple[float, float, float]:
    """Adil 1 olasılığını k1 katına çekip X/2'yi orantılı ayarla (marjsız oranlar)."""
    t = devig(list(target))
    p1 = t[0] * k1
    rest = (1 - p1) / (t[1] + t[2])
    return (1 / p1, 1 / (t[1] * rest), 1 / (t[2] * rest))


def test_empty_pool(con):
    r = so.find_similar(con, (1.80, 3.60, 4.20))
    assert r["n"] == 0 and r["pool_size"] == 0 and r["low_sample"] is True
    assert r["outcomes"] is None and r["closest"] == [] and r["top_scores"] == []
    assert r["target"]["basis"] == "iddaa" and r["target"]["odds"] == {"1": 1.8, "0": 3.6, "2": 4.2}


def test_similarity_boundaries(con):
    tgt = (2.00, 3.40, 3.80)
    _add(con, "same", tgt, 2, 1, ht=(1, 0))
    _add(con, "in", _scaled(tgt, 1.04), 1, 1)       # 1'de %4 sapma (X/2 küçük kayar) -> içeride
    _add(con, "out", _scaled(tgt, 1.07), 0, 2)      # %7 sapma -> dışarıda
    _add(con, "far", (1.20, 7.0, 15.0), 3, 0)
    r = so.find_similar(con, tgt)
    assert r["n"] == 2 and r["pool_size"] == 4 and r["low_sample"] is True
    keys = {e["home"] for e in r["closest"]}
    assert keys == {"Hsame", "Hin"}
    assert r["closest"][0]["home"] == "Hsame" and r["closest"][0]["similarity"] == pytest.approx(1.0)
    assert 0.95 <= r["closest"][1]["similarity"] < 0.97
    assert r["outcomes"] == {"1": 0.5, "0": 0.5, "2": 0.0}
    assert r["ht"] == {"n": 1, "outcomes": {"1": 1.0, "0": 0.0, "2": 0.0}}
    # eşik düşürülünce %7 sapmalı maç da girer
    assert so.find_similar(con, tgt, min_similarity=0.92)["n"] == 3


def test_symmetric_definition(con):
    t = (0.20, 0.25, 0.55)
    # adil 1 olasılığı 0.95x ve 1/0.95x (X sabit, 2 telafi eder ve daha az sapar): ikisi de sınırda içeride;
    # 0.95x'in biraz altı dışarıda
    for k, key in ((0.95 + 1e-6, "lo"), (1 / 0.95 - 1e-6, "hi"), (0.95 - 1e-4, "out")):
        p1 = t[0] * k
        _add(con, key, (1 / p1, 1 / t[1], 1 / (1 - p1 - t[1])), 1, 0)
    r = so.find_similar_probs(con, t)
    assert r["n"] == 2 and {e["home"] for e in r["closest"]} == {"Hlo", "Hhi"}
    assert all(e["similarity"] == pytest.approx(0.95, abs=1e-4) for e in r["closest"])
    assert r["target"]["basis"] == "model" and r["target"]["odds"] is None


def test_summary_stats_and_dedupe(con):
    tgt = (1.80, 3.60, 4.20)
    scores = [(2, 0)] * 20 + [(1, 1)] * 8 + [(0, 1)] * 6 + [(3, 2)] * 6
    for i, (h, a) in enumerate(scores):
        _add(con, f"m{i}", tgt, h, a, d=f"2023-0{1 + i % 9}-1{i % 10}")
    # aynı maç iddaa arşivinde de var (aynı lig, 1 gün fark, aynı skor) -> sayılmaz
    _add(con, "dup", tgt, 2, 0, source=so.SOURCE_IDDAA, d="2023-01-11")
    _add(con, "own", tgt, 0, 0, source=so.SOURCE_IDDAA, league="tur.1", d="2026-10-10")
    r = so.find_similar(con, tgt, limit_examples=5)
    assert r["n"] == 41 and r["low_sample"] is False
    assert r["sources"] == {"football-data": 40, "iddaa": 1}
    assert r["outcomes"]["1"] == pytest.approx(26 / 41)
    assert r["top_scores"][0] == {"score": "2-0", "hg": 2, "ag": 0, "count": 20, "share": pytest.approx(20 / 41)}
    assert r["over25"] == pytest.approx(6 / 41)
    assert r["btts"] == pytest.approx(14 / 41)
    assert len(r["closest"]) == 5 and r["recent"][0]["date"] == "2026-10-10"
    assert r["recent"][0]["league_name"] == "Süper Lig"
    lo, hi = r["outcomes_ci95"]["1"]
    assert lo < r["outcomes"]["1"] < hi
    assert sum(r["pool_implied"].values()) == pytest.approx(1.0)
    assert r["date_range"] == {"from": "2023-01-10", "to": "2026-10-10"}


def test_invalid_inputs(con):
    with pytest.raises(ValueError):
        so.find_similar(con, (1.0, 3.0, 4.0))
    with pytest.raises(ValueError):
        so.find_similar_probs(con, (0.5, 0.5, 0.0))


def test_payload_target_prefers_iddaa_then_model():
    model_ms = {"key": "ms", "line": None, "outcomes": [{"name": n, "p_model": p} for n, p in (("1", .5), ("0", .3), ("2", .2))]}
    p = {"markets": [model_ms], "iddaa": None}
    assert so.payload_target(p) == ("model", (0.5, 0.3, 0.2))
    p["iddaa"] = {"markets": [{"key": "ms", "line": None, "outcomes": [
        {"name": "1", "odd": 1.8}, {"name": "0", "odd": 3.6}, {"name": "2", "odd": 4.2}]}]}
    assert so.payload_target(p) == ("iddaa", (1.8, 3.6, 4.2))
    assert so.payload_target({"markets": []}) is None


def test_ingest_history_with_local_fetcher_and_iddaa_closing(con):
    # iddaa arşivi: bitmiş, eşleşmiş maç; başlama öncesi son oranlar kapanış sayılır, sonrası yok sayılır
    con.execute("INSERT INTO teams(id, name) VALUES('1','Galatasaray'),('2','Fenerbahçe')")
    con.execute("""INSERT INTO matches(id, league, season, date_utc, state, completed, home_id, away_id, home_goals,
                   away_goals, home_ht, away_ht, scoreboard_fetched_at, ft90_home, ft90_away)
                   VALUES('900','tur.1',2026,'2026-10-15T17:00:00Z','post',1,'1','2',2,1,1,1,'x',2,1)""")
    con.execute("""INSERT INTO iddaa_events(id, home_name, away_name, kickoff_utc, espn_match_id, last_seen_at)
                   VALUES(55,'GS','FB','2026-10-15T17:00:00Z','900','x')""")
    hist = [(1, 2.10, "2026-10-15T10:00:00Z"), (2, 3.30, "2026-10-15T10:00:00Z"), (3, 3.20, "2026-10-15T10:00:00Z"),
            (1, 1.95, "2026-10-15T16:00:00Z"), (1, 1.50, "2026-10-15T17:30:00Z")]
    for no, odd, at in hist:
        con.execute("INSERT INTO odds_history VALUES(55,'1:1:',?,?,?)", (no, odd, at))

    calls: list[str] = []

    async def fetch(url: str) -> bytes | None:
        calls.append(url)
        if url.endswith("/2627/E0.csv"):
            return MAIN_2627.encode("utf-8")
        if url.endswith("/new/ARG.csv"):
            return EXTRA.encode("utf-8")
        return None

    logs: list[str] = []
    r = asyncio.run(so.ingest_history(con, logs.append, fetch=fetch, today=date(2026, 10, 16), seasons=2))
    assert len(calls) == 2 * len(fd.FD_MAIN) + len(fd.FD_EXTRA)
    assert r["fd_rows"] == 3 and r["iddaa_rows"] == 1 and r["pool"] == 4 and r["errors"] == 0
    row = con.execute("SELECT * FROM hist_odds_matches WHERE source='iddaa'").fetchone()
    assert (row["o1"], row["ox"], row["o2"], row["hg"], row["ag"], row["league"]) == (1.95, 3.30, 3.20, 2, 1, "tur.1")
    # ikinci çalıştırma: geçmiş sezon final, güncel dosyalar taze -> hiç istek yok
    calls.clear()
    r2 = asyncio.run(so.ingest_history(con, logs.append, fetch=fetch, today=date(2026, 10, 16), seasons=2))
    assert calls == [] and r2["files_due"] == 0 and r2["pool"] == 4


def test_ingest_history_all_failed_raises(con):
    async def fetch(url: str) -> bytes | None:
        raise RuntimeError("bağlantı sıfırlandı")

    with pytest.raises(RuntimeError, match="hiçbiri alınamadı"):
        asyncio.run(so.ingest_history(con, lambda _m: None, fetch=fetch, today=date(2026, 10, 16), seasons=1))
