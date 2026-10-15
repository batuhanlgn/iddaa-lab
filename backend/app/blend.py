"""Model-piyasa harman ağırlığının (w) ileriye dönük arşivden kalibrasyonu ve ayrı dilimde doğrulanması.

- Örnekler: başlama saatinden ÖNCE kaydedilmiş tahminler (model λ ve piyasa-ima λ aynı yükte, aynı anda).
- Doğrulanan olasılık, kuponda kullanılanın AYNISIDIR: p_safe = min(matris harmanı, gerçek iddaa olasılığıyla
  pazar içi harman). MS log-loss ile ölçülür (90 dk sonucu). p_safe her iki harmandan da küçük olduğundan, ayrı dilimde
  gerçek piyasayı yenebilmesi için iki harmanın da piyasayı yenmesi gerekir.
- Zaman sıralı ayrım: ilk %70 dilimde w seçilir, son %30 dilimde doğrulanır. Harman, ayrı dilimde piyasadan kötü
  değilse ve yeterli örnek varsa "doğrulandı" sayılır; değer kuponları yalnızca o zaman üretilir.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import numpy as np

from . import db
from .config import BLEND_MIN_SETTLED, BLEND_WEIGHT_DEFAULT
from .model import markets as mk
from .model.goals import score_matrix
from .model.market_fit import blend_matrix, ms_probs

GRID = np.round(np.linspace(0, 1, 21), 2)


def settled_samples(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        """SELECT m.id, m.date_utc, m.ft90_home, m.ft90_away FROM matches m
           WHERE m.completed=1 AND m.ft90_home IS NOT NULL
             AND EXISTS (SELECT 1 FROM iddaa_events e WHERE e.espn_match_id = m.id)
           ORDER BY m.date_utc"""
    ).fetchall()
    out = []
    for r in rows:
        pr = con.execute(
            "SELECT payload FROM predictions WHERE match_id=? AND created_at < ? ORDER BY created_at DESC LIMIT 1",
            (r["id"], r["date_utc"]),
        ).fetchone()
        if pr is None:
            continue
        p = json.loads(pr["payload"])
        mm = (p.get("iddaa") or {}).get("market_model")
        model = p.get("model")
        if not mm or not model or not mm.get("ms_market_actual"):
            continue
        sm_m = score_matrix(model["lambda_home"], model["lambda_away"], model["rho"])
        sm_q = score_matrix(mm["lambda_home"], mm["lambda_away"], model["rho"])
        y = 0 if r["ft90_home"] > r["ft90_away"] else 1 if r["ft90_home"] == r["ft90_away"] else 2
        out.append({"date": r["date_utc"], "sm_m": sm_m, "sm_q": sm_q, "q": mm["ms_market_actual"], "y": y})
    return out


def p_safe_ms(s: dict, w: float) -> list[float]:
    """Kuponla aynı muhafazakâr MS olasılığı (normalize edilmez; EV hesabında da edilmiyor)."""
    matrix = ms_probs(blend_matrix(s["sm_m"], s["sm_q"], w))
    local = mk.blend(ms_probs(s["sm_m"]), s["q"], w)
    return [min(a, b) for a, b in zip(matrix, local)]


def _ll(samples: list[dict], w: float) -> float:
    return float(-np.mean([np.log(max(p_safe_ms(s, w)[s["y"]], 1e-12)) for s in samples]))


def _ll_market(samples: list[dict]) -> float:
    """Gerçek iddaa MS olasılığı (marjı arındırılmış) — piyasanın kendisi, DC projeksiyonu değil."""
    return float(-np.mean([np.log(max(s["q"][s["y"]], 1e-12)) for s in samples]))


def calibrate_blend(con: sqlite3.Connection) -> dict:
    samples = settled_samples(con)
    n = len(samples)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res: dict = {"n": n, "required": BLEND_MIN_SETTLED, "default_weight": BLEND_WEIGHT_DEFAULT, "updated_at": now}
    if n < 20:
        res["status"] = "veri_yok" if n == 0 else "yetersiz_veri"
    else:
        cut = int(n * 0.7)
        fit_s, hold = samples[:cut], samples[cut:]
        curve = [{"w": float(w), "logloss": _ll(fit_s, float(w))} for w in GRID]
        best = min(curve, key=lambda c: c["logloss"])
        hold_blend = _ll(hold, best["w"])
        hold_market = _ll_market(hold)
        hold_model = _ll(hold, 1.0)
        res.update({
            "curve": curve, "best_w": best["w"], "n_fit": len(fit_s), "n_holdout": len(hold),
            "holdout_blend_logloss": hold_blend, "holdout_market_logloss": hold_market, "holdout_model_logloss": hold_model,
            "model_logloss": _ll(samples, 1.0), "market_logloss": _ll_market(samples),
        })
        # Harman, ayrı dilimde gerçek piyasadan DAHA İYİ olmalı (tolerans yok)
        validated = n >= BLEND_MIN_SETTLED and hold_blend < hold_market
        res["validated"] = validated
        if validated:
            res["status"] = "kalibre"
            res["weight"] = best["w"]
        else:
            res["status"] = "yetersiz_veri" if n < BLEND_MIN_SETTLED else "dogrulanamadi"
    with db.tx(con):
        db.meta_set(con, "blend_calibration", res)
    return {k: res[k] for k in ("status", "n") if k in res}
