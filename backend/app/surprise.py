"""Sürpriz adayları: yüksek oranlı, nadir sonuçlar — İY/MS dönüşü (1/2, 2/1) ve 5.5 gol Üst (6+ gol).

Kupon değil, liste: her aday için modelin olasılığı, iddaa oranı, adil oran ve modelin beklenen getirisi. İki sıralama:
"değer" (model olasılığı × oran en yüksek: oran modelin beklediğinden cömert) ve "olasılık" (en sık tutacak olanlar).
İY/MS marjı ~%27, gol çizgileri ~%17 olduğu için beklenen getiri çoğunlukla negatiftir; sayfa bunu açıkça söyler.
5.5 Üst'te iddaa "Alt"ı çoğunlukla kapatır: piyasa olasılığı marjlı 1/oran'dır (pipeline._one_sided_goal).
"""
from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timezone
from typing import Any

from .coupons import latest_predictions

SURPRISE_DAYS = 4.0
SURPRISE_MIN_LEAD_MIN = 10
SURPRISE_LIST_LEN = 15
REVERSALS = ("1/2", "2/1")
OVER_LINE = "5.5"


def _p_over(p: dict[str, Any], line: float) -> float:
    """Skor dağılımından P(toplam gol > çizgi); kesilen kuyruk ("other") hep çizginin üstündedir (≥ 7 gol)."""
    sm = p["score_matrix"]
    grid = sm["p"]
    return float(sum(grid[i][j] for i in range(len(grid)) for j in range(len(grid[i])) if i + j > line) + sm["other"])


def _row(p: dict[str, Any], selection: str, p_model: float, odd: float | None, p_market: float | None) -> dict[str, Any]:
    m = p["match"]
    return {
        "match_id": m["id"], "date_utc": m["date_utc"], "league_name": m["league_name"], "country": m.get("country", ""),
        "home": m["home"]["name"], "away": m["away"]["name"], "home_logo": m["home"].get("logo"),
        "away_logo": m["away"].get("logo"), "selection": selection, "p_model": p_model, "odd": odd,
        "p_market": p_market, "fair_odd": 1.0 / p_model if p_model > 0 else None,
        "ev_model": p_model * odd - 1.0 if odd else None, "confidence": p["model"]["confidence"],
        "goals_expected": p["model"]["lambda_home"] + p["model"]["lambda_away"],
    }


def surprise_candidates(con: sqlite3.Connection) -> dict[str, Any]:
    preds = latest_predictions(con, SURPRISE_DAYS, min_lead_minutes=SURPRISE_MIN_LEAD_MIN)
    reversals: list[dict[str, Any]] = []
    overs: list[dict[str, Any]] = []
    margins: dict[str, list[float]] = {"iyms": []}
    for p in preds:
        if not p.get("covered"):
            continue
        offered_over: dict[str, Any] | None = None
        for mkt in (p.get("iddaa") or {}).get("markets", []):
            if mkt["key"] == "iyms":
                if mkt.get("margin") is not None:
                    margins["iyms"].append(float(mkt["margin"]))
                for o in mkt["outcomes"]:
                    if o["name"] in REVERSALS:
                        reversals.append(_row(p, o["name"], float(o["p_model"]), float(o["odd"]), float(o["p_market"])))
            elif mkt["key"] == "au" and mkt.get("line") == OVER_LINE:
                offered_over = next((o for o in mkt["outcomes"] if o["name"] == "Üst"), None)
        if offered_over is not None:
            overs.append(_row(p, f"{OVER_LINE} Üst", float(offered_over["p_model"]), float(offered_over["odd"]),
                              float(offered_over["p_market"])))
        else:  # iddaa bu maçta 5.5 sunmuyor: yalnız model olasılığı (oran yok)
            overs.append(_row(p, f"{OVER_LINE} Üst", _p_over(p, float(OVER_LINE)), None, None))

    def by_value(xs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted([x for x in xs if x["odd"]], key=lambda x: -x["ev_model"])[:SURPRISE_LIST_LEN]

    def by_prob(xs: list[dict[str, Any]], offered_only: bool) -> list[dict[str, Any]]:
        ys = [x for x in xs if x["odd"]] if offered_only else xs
        return sorted(ys, key=lambda x: -x["p_model"])[:SURPRISE_LIST_LEN]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": SURPRISE_DAYS,
        "reversal": {"by_value": by_value(reversals), "by_prob": by_prob(reversals, True), "n": len(reversals),
                     "median_margin": statistics.median(margins["iyms"]) if margins["iyms"] else None},
        "over55": {"by_value": by_value(overs), "by_prob": by_prob(overs, False), "n": len(overs),
                   "n_offered": sum(1 for x in overs if x["odd"])},
    }
