"""Maç bağlamı: form, puan durumu, karşılıklı geçmiş, benzer oranlı geçmiş maçlar ve bunlardan kurulan scout raporu.

API (maç sayfası, bülten) ve kupon üretimi aynı bağlamı kullanır; scout hükmü her yerde aynı çıkar.
"""
from __future__ import annotations

import time
from typing import Any


def _form(c: Any, m: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Son karşılaşmalar ve form (iki takımın maç öncesi son 6 maçı)."""
    form = {}
    for side in ("home", "away"):
        tid = m[side]["id"]
        rows = c.execute(
            """SELECT m.id, m.date_utc, m.league, m.home_id, m.away_id, m.home_goals, m.away_goals, th.name hn, ta.name an
               FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
               WHERE m.completed=1 AND (m.home_id=? OR m.away_id=?) AND m.date_utc < ? ORDER BY m.date_utc DESC LIMIT 6""",
            (tid, tid, m["date_utc"]),
        ).fetchall()
        form[side] = [{**dict(x), "is_home": x["home_id"] == tid} for x in rows]
    return form


_CTX_TTL_S = 600
_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def cached_context(c: Any, p: dict[str, Any]) -> dict[str, Any]:
    """Bülten her maç için bağlam kurar (~10 ms/maç); aynı tahmin için 10 dakika bellekte tutulur."""
    key = (p["match"]["id"], str(p.get("created_at")))
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _CTX_TTL_S:
        return hit[1]
    ctx = match_context(c, p)
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[key] = (now, ctx)
    return ctx


def match_context(c: Any, p: dict[str, Any], *, asof: bool = False) -> dict[str, Any]:
    """Maç sayfası bağlamı: form, puan durumu, karşılıklı geçmiş, benzer oranlı geçmiş maçlar ve scout raporu.

    asof=True (scout backtest'i): her şey maç tarihi itibarıyla — puan durumu o güne kadarki sonuçlardan kurulur
    (ESPN anlık tablosu geçmişi bilmez), benzer oranlar yalnız maç gününden önceki maçlardan aranır."""
    # Geç içe aktarma: scout -> coupons -> context döngüsü
    from .league_info import head_to_head, match_standings, standings_asof
    from .scout import build_scout
    from .similar_odds import similar_for_payload

    m = p["match"]
    form = _form(c, m)
    if asof:
        standings = standings_asof(c, m["league"], m["home"]["id"], m["away"]["id"], m["date_utc"])
    else:
        standings = match_standings(c, m["league"], m["home"]["id"], m["away"]["id"])
    h2h = head_to_head(c, m["home"]["id"], m["away"]["id"], m["date_utc"])
    similar = (similar_for_payload(c, p, before=m["date_utc"][:10] if asof else None)
               if p.get("covered") else None)
    scout = (build_scout({**p, "form": form}, form=form, standings=standings, h2h=h2h, similar=similar)
             if p.get("covered") else None)
    return {"form": form, "standings": standings, "h2h": h2h, "similar": similar, "scout": scout}


def scout_brief(scout: dict[str, Any] | None) -> dict[str, Any] | None:
    """Bülten satırı için scout hükmünün özeti."""
    if scout is None:
        return None
    v = scout["verdict"]
    pick = v.get("pick")
    return {"verdict": v["verdict"], "headline": v["headline"], "reason": v["reason"], "confidence": v.get("confidence"),
            "selection_text": pick["selection_text"] if pick else None, "odd": pick["odd"] if pick else None,
            "p_model": pick["p_model"] if pick else None}
