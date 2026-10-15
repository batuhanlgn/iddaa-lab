"""Canlı takip için hafif taban veri: maç öncesi model girdileri (canlı modeli tarayıcı hesaplar).

Tarayıcı ESPN'den canlı skor/dakika/olayları ve iddaa'dan canlı oranları doğrudan çeker (ikisi de CORS'a açık);
bu dosya yalnızca maçların maç öncesi beklenen gollerini, kalibrasyonunu ve iddaa takım adlarını sağlar.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from .coupons import model_pick


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def live_base(con: sqlite3.Connection, hours_back: float = 14.0, hours_fwd: float = 30.0) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    rows = con.execute(
        """SELECT p.payload FROM predictions p JOIN matches m ON m.id = p.match_id
           WHERE m.date_utc >= ? AND m.date_utc <= ?
             AND p.created_at = (SELECT MAX(created_at) FROM predictions p2 WHERE p2.match_id = p.match_id)
           ORDER BY m.date_utc""",
        (_iso(now - timedelta(hours=hours_back)), _iso(now + timedelta(hours=hours_fwd))),
    ).fetchall()
    items = []
    for r in rows:
        p = json.loads(r["payload"])
        if not p.get("covered") or not p.get("model"):
            continue
        m = p["match"]
        mod = p["model"]
        ev = con.execute(
            "SELECT id, home_name, away_name FROM iddaa_events WHERE espn_match_id=? ORDER BY match_score DESC LIMIT 1",
            (m["id"],),
        ).fetchone()
        pk = model_pick(p)
        ms = next((x for x in p.get("markets", []) if x["key"] == "ms"), None)
        items.append({
            "id": m["id"], "league": m["league"], "league_name": m["league_name"], "country": m["country"],
            "date_utc": m["date_utc"],
            "home": {k: m["home"].get(k) for k in ("id", "name", "short_name", "logo")},
            "away": {k: m["away"].get(k) for k in ("id", "name", "short_name", "logo")},
            "model": {"lambda_home": mod["lambda_home"], "lambda_away": mod["lambda_away"], "p1": mod["p1"],
                      "cal_g": mod.get("cal_g", 1.0), "confidence": mod["confidence"]},
            "pre_ms": {o["name"]: o["p_model"] for o in ms["outcomes"]} if ms else None,
            "iddaa": {"event_id": ev["id"], "home_name": ev["home_name"], "away_name": ev["away_name"]} if ev else None,
            "pick": {"label": pk.label, "line": pk.line, "name": pk.outcome_name, "key": pk.key, "odd": pk.odd,
                     "p_model": pk.p_model} if pk else None,
        })
    return {"generated_at": _iso(now), "items": items}
