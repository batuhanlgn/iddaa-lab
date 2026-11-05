from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app import db
from app.ingest import is_detail_key
from app.model import markets as mk
from app.model.goals import score_matrix
from app.model.pipeline import markets_from_rows
from app.sources import iddaa
from app.surprise import _p_over, surprise_candidates


def test_detail_parse_keeps_55_line_only():
    payload = {"isSuccess": True, "data": {"i": 7, "sid": 1, "d": 4102444800, "hn": "A", "an": "B", "m": [
        {"t": 2, "st": 101, "sov": "5.5", "o": [{"no": 1, "n": "Alt", "odd": 1.0}, {"no": 2, "n": "Üst", "odd": 6.13}]},
        {"t": 2, "st": 101, "sov": "2.5", "o": [{"no": 1, "n": "Alt", "odd": 2.5}, {"no": 2, "n": "Üst", "odd": 1.5}]},
        {"t": 2, "st": 48, "sov": "9.5", "o": [{"no": 1, "n": "Alt", "odd": 1.7}, {"no": 2, "n": "Üst", "odd": 1.7}]},
    ]}}
    ev = iddaa.parse_event_detail(payload, 7)
    assert ev is not None
    keys = {m.market_key for m in ev.markets}
    assert keys == {"2:101:5.5", "2:48:9.5"}  # 2.5 toplu bültenden gelir, detaydan alınmaz
    m55 = next(m for m in ev.markets if m.market_key == "2:101:5.5")
    assert [o.name for o in m55.outcomes] == ["Üst"]  # 1.00 "Alt" kapalı sayılır
    assert is_detail_key("2:101:5.5") and not is_detail_key("2:101:2.5") and is_detail_key("2:48:9.5")


def test_one_sided_55_over_market_built_from_score_matrix():
    sm = score_matrix(2.2, 1.9, -0.05)
    j = mk.build_joint(sm, 0.45)
    rows = [{"market_key": "2:101:5.5", "outcome_no": 2, "outcome_name": "Üst", "odd": 6.0, "mbs": 1,
             "fetched_at": "2026-11-06T00:00:00Z"}]
    out, _ = markets_from_rows(rows, sm, j, 0.45, -0.05, None, 0.5, {}, (2.2, 1.9))
    assert len(out) == 1 and out[0]["margin"] is None and len(out[0]["outcomes"]) == 1
    o = out[0]["outcomes"][0]
    tot = np.add.outer(np.arange(sm.shape[0]), np.arange(sm.shape[1]))
    assert o["p_model"] == pytest.approx(float(sm[tot > 5.5].sum()), abs=1e-6)
    assert o["p_market"] == pytest.approx(1 / 6.0)
    assert o["ev_model"] == pytest.approx(o["p_model"] * 6.0 - 1)


def test_p_over_includes_truncated_tail():
    p = {"score_matrix": {"p": [[0.1, 0.1], [0.1, 0.1]], "other": 0.2}}
    assert _p_over(p, 1.5) == pytest.approx(0.1 + 0.2)


def _payload(mid: str, kick: str, p12: float, odd12: float, p55: float | None, odd55: float | None) -> dict:
    markets = [{"key": "iyms", "line": None, "margin": 0.27, "outcomes": [
        {"name": "1/2", "odd": odd12, "p_model": p12, "p_market": 1 / odd12 / 1.27},
        {"name": "2/1", "odd": 30.0, "p_model": 0.02, "p_market": 0.026},
    ]}]
    if odd55 is not None and p55 is not None:
        markets.append({"key": "au", "line": "5.5", "margin": None, "outcomes": [
            {"name": "Üst", "odd": odd55, "p_model": p55, "p_market": 1 / odd55}]})
    return {"covered": True, "created_at": "2026-11-06T00:00:00Z",
            "match": {"id": mid, "date_utc": kick, "league_name": "L", "country": "C",
                      "home": {"name": f"H{mid}"}, "away": {"name": f"A{mid}"}},
            "model": {"confidence": "yüksek", "lambda_home": 2.0, "lambda_away": 1.5, "blend_weight": 0.5},
            "score_matrix": {"p": [[0.5, 0.1], [0.1, 0.1]], "other": 0.2},
            "iddaa": {"event_id": int(mid), "markets": markets}}


def test_surprise_candidates_rankings():
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.row_factory = sqlite3.Row
    con.executescript(db.SCHEMA)
    kick = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    specs = [("1", 0.05, 15.0, 0.25, 4.0), ("2", 0.03, 40.0, None, None), ("3", 0.04, 20.0, 0.12, 9.0)]
    for mid, p12, o12, p55, o55 in specs:
        con.execute("""INSERT INTO matches(id, league, date_utc, state, completed, home_id, away_id, scoreboard_fetched_at)
                       VALUES(?, 'eng.1', ?, 'pre', 0, 'h', 'a', 'x')""", (mid, kick))
        con.execute("INSERT INTO predictions VALUES(?,?,?,?)",
                    (mid, "2026-11-06T00:00:00Z", "v", json.dumps(_payload(mid, kick, p12, o12, p55, o55))))
    r = surprise_candidates(con)
    rv = r["reversal"]
    assert rv["n"] == 6
    assert rv["by_value"][0]["match_id"] == "2" and rv["by_value"][0]["selection"] == "1/2"  # 0.03*40 = 1.2
    assert rv["by_prob"][0]["match_id"] == "1"
    ov = r["over55"]
    assert ov["n"] == 3 and ov["n_offered"] == 2
    assert [x["match_id"] for x in ov["by_value"]] == ["3", "1"]  # 0.12*9=1.08 > 0.25*4=1.0
    no_odd = next(x for x in ov["by_prob"] if x["match_id"] == "2")
    assert no_odd["odd"] is None and no_odd["p_model"] == pytest.approx(0.2)  # skor dağılımından: yalnız kesilen kuyruk 5.5 üstü
