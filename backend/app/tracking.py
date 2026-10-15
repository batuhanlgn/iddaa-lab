"""İleriye dönük takip: model önerileri ve kupon seçimlerinin kapanış oranına karşı performansı (CLV) ve isabeti.

CLV (closing line value): seçimin alındığı oran, maç başlamadan önceki son (kapanış) orandan yüksekse piyasa sonradan
modelin tarafına kaymış demektir. Gerçek avantajın en hızlı göstergesidir; sonuç beklemeden günler içinde ölçülür.
  - clv_odds    = alınan_oran / kapanış_oranı - 1
  - ev_vs_close = kapanışın marjı arındırılmış olasılığı × alınan_oran - 1  (kapanış çizgisine göre beklenen değer)
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from . import db
from .coupons import settle_selection
from .model import markets as mk

FAMILY_LABEL = {"ms": "Maç sonucu", "au": "Gol (A/Ü)", "kg": "Karşılıklı gol", "iy": "İlk yarı", "korner": "Korner"}


def closing_odds(con: sqlite3.Connection, event_id: int, market_key: str, kickoff: str) -> dict[int, float]:
    rows = con.execute(
        """SELECT h.outcome_no, h.odd FROM odds_history h
           JOIN (SELECT outcome_no, MAX(fetched_at) f FROM odds_history
                 WHERE event_id=? AND market_key=? AND fetched_at < ? GROUP BY outcome_no) last
             ON last.outcome_no=h.outcome_no AND last.f=h.fetched_at
           WHERE h.event_id=? AND h.market_key=?""",
        (event_id, market_key, kickoff, event_id, market_key),
    ).fetchall()
    return {int(r["outcome_no"]): float(r["odd"]) for r in rows}


def clv(con: sqlite3.Connection, event_id: int | None, market_key: str, outcome_no: int, taken: float, kickoff: str) -> dict | None:
    if not event_id or market_key.startswith("oyuncu:"):
        return None
    close = closing_odds(con, int(event_id), market_key, kickoff)
    if outcome_no not in close or len(close) < 2:
        return None
    nos = sorted(close)
    q = mk.devig([close[n] for n in nos])
    q_close = q[nos.index(outcome_no)]
    return {"close_odd": close[outcome_no], "clv_odds": taken / close[outcome_no] - 1.0, "ev_vs_close": q_close * taken - 1.0}


def _empty() -> dict[str, float]:
    return {"n": 0, "n_clv": 0, "clv_sum": 0.0, "ev_close_sum": 0.0, "beat": 0, "settled": 0, "won": 0, "void": 0,
            "staked": 0.0, "returned": 0.0, "expected": 0.0}


def _add(g: dict[str, float], c: dict | None, result: str | None, odd: float, p: float) -> None:
    g["n"] += 1
    if c:
        g["n_clv"] += 1
        g["clv_sum"] += c["clv_odds"]
        g["ev_close_sum"] += c["ev_vs_close"]
        g["beat"] += int(c["clv_odds"] > 0)
    if result in ("won", "lost"):
        g["settled"] += 1
        g["staked"] += 1.0
        g["expected"] += p
        if result == "won":
            g["won"] += 1
            g["returned"] += odd
    elif result == "void":
        g["void"] += 1


def _finish(g: dict[str, float]) -> dict[str, Any]:
    return {
        "n": int(g["n"]), "n_clv": int(g["n_clv"]),
        "clv_mean": g["clv_sum"] / g["n_clv"] if g["n_clv"] else None,
        "ev_vs_close_mean": g["ev_close_sum"] / g["n_clv"] if g["n_clv"] else None,
        "beat_close_pct": g["beat"] / g["n_clv"] if g["n_clv"] else None,
        "settled": int(g["settled"]), "won": int(g["won"]), "void": int(g["void"]),
        "hit_rate": g["won"] / g["settled"] if g["settled"] else None,
        "expected_hit_rate": g["expected"] / g["settled"] if g["settled"] else None,
        "roi": (g["returned"] - g["staked"]) / g["staked"] if g["staked"] else None,
    }


def update_tracking(con: sqlite3.Connection) -> dict[str, Any]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    groups: dict[str, dict[str, float]] = defaultdict(_empty)
    recent: list[dict[str, Any]] = []

    # 1) Model önerileri: maç başına ilk yayınlanan öneri (en erken günlük kaydı), başlama saati geçmiş maçlar
    rows = con.execute(
        """SELECT l.match_id, l.created_at, l.pick, l.iddaa_event_id, m.date_utc, th.name hn, ta.name an, m.league
           FROM prediction_log l
           JOIN matches m ON m.id = l.match_id
           JOIN teams th ON th.id = m.home_id JOIN teams ta ON ta.id = m.away_id
           WHERE l.pick IS NOT NULL AND m.date_utc < ? AND l.created_at < m.date_utc
             AND l.created_at = (SELECT MIN(l2.created_at) FROM prediction_log l2
                                 WHERE l2.match_id = l.match_id AND l2.pick IS NOT NULL)
           ORDER BY m.date_utc DESC""",
        (now,),
    ).fetchall()
    for r in rows:
        pk = json.loads(r["pick"])
        sel = {"match_id": r["match_id"], "key": pk["key"], "line": pk["line"], "outcome_name": pk["name"],
               "family": pk.get("family", ""), "market_key": pk["market_key"]}
        res = settle_selection(con, sel)
        c = clv(con, r["iddaa_event_id"], pk["market_key"], int(pk["outcome_no"]), float(pk["odd"]), r["date_utc"])
        p = float(pk.get("p_model") or 0)
        for g in ("oneri", f"oneri:{pk.get('family', '')}"):
            _add(groups[g], c, res, float(pk["odd"]), p)
        if len(recent) < 60:
            recent.append({"match_id": r["match_id"], "date_utc": r["date_utc"], "home": r["hn"], "away": r["an"],
                           "label": pk["label"], "line": pk["line"], "name": pk["name"], "odd": pk["odd"], "p_model": p,
                           "close_odd": c["close_odd"] if c else None, "clv_odds": c["clv_odds"] if c else None,
                           "result": res})

    # 2) Kupon seçimleri: arşivdeki her kuponun seçimleri (kupon türüne göre)
    for r in con.execute("SELECT kind, payload FROM coupons"):
        payload = json.loads(r["payload"])
        for s in payload.get("selections", []):
            m = con.execute("SELECT date_utc FROM matches WHERE id=?", (s["match_id"],)).fetchone()
            if m is None or m["date_utc"] >= now:
                continue
            res = settle_selection(con, s)
            c = clv(con, s.get("iddaa_event_id"), s["market_key"], int(s["outcome_no"]), float(s["odd"]), m["date_utc"]) \
                if s.get("has_market", True) else None
            _add(groups[f"kupon:{r['kind']}"], c, res, float(s["odd"]), float(s.get("p_blend") or 0))

    out = {"updated_at": now, "groups": {k: _finish(v) for k, v in groups.items()}, "recent_picks": recent,
           "family_labels": FAMILY_LABEL}
    with db.tx(con):
        db.meta_set(con, "tracking", out)
    g = out["groups"].get("oneri", {})
    return {"oneri": g.get("n", 0), "clv": g.get("n_clv", 0), "sonuclanan": g.get("settled", 0)}
