"""Scout raporunun geçmiş maçlarda sınanması (walk-forward, geleceği görmeden).

Her hafta model yalnız o haftadan önceki sonuçlarla yeniden eğitilir; haftanın maçları için tahmin yükü, maç tarihi
itibarıyla form / puan durumu / karşılıklı geçmiş / benzer oranlar ve scout hükmü üretilir. Piyasa: football-data
kapanış oranları (MS ve 2.5 gol Alt/Üst) — iddaa oran arşivi geçmişe gitmediği için.

Ölçülenler: scout önerilerinin isabeti ve getirisi; aynı maçlarda modelin kendi önerisi (coupons.model_pick) ve
scout'un "pas" dediği maçlarda modelin önerisi (filtre gerçekten kötü seçimleri mi eliyor?).
Getiri iki oranla raporlanır: kapanış ortalaması (marj ~%5) ve iddaa marjına çevrilmiş oran (aynı adil olasılık,
iddaa'nın güncel ortalama marjı) — iddaa'da oynansaydı.

Sınırlar: bu pazarlar dışında (çifte şans, KG, handikap) geçmiş oran yok, bu yüzden scout yalnız MS ve 2.5 Alt/Üst
arasından seçebilir; simülasyon (oyuncu profili) ve ESPN bölge notları geçmişte yok; model parametreleri bugünkü
ayardır (ayar dilimiyle kısmen örtüşür).
"""
from __future__ import annotations

import logging
import random
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import db
from .config import LEAGUE_BY_SLUG
from .context import match_context
from .coupons import model_pick, settle_selection
from .matching import similarity
from .model.pipeline import fit_all, load_params, predict_match

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

BACKTEST_DAYS = 365
MS_KEY = "1:1:"
AU25_KEY = "2:101:2.5"
_FD_MATCH_MIN = 0.6           # football-data satırı eşleşmesi: iki takım adı benzerliği alt sınırı
_FD_MATCH_STRONG = 0.9        # ya da biri neredeyse kesin + diğeri en az _FD_MATCH_WEAK
_FD_MATCH_WEAK = 0.4
_BOOT = 2000                  # getiri güven aralığı için bootstrap tekrarı
_DEFAULT_IDDAA_MARGIN = 0.175  # güncel bültenden ölçülemezse (16 Eki 2026 ölçümü: MS ve 2.5 A/Ü medyanı ~%17.5)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def iddaa_margins(con: sqlite3.Connection) -> dict[str, float]:
    """Güncel bültendeki medyan marj (pazar başına): getiriyi iddaa'da oynanmış gibi hesaplamak için."""
    out = {}
    for key, n_out in ((MS_KEY, 3), (AU25_KEY, 2)):
        rows = con.execute("SELECT SUM(1.0/odd) s, COUNT(*) n FROM odds_current WHERE market_key=? GROUP BY event_id",
                           (key,)).fetchall()
        ms = [r["s"] - 1.0 for r in rows if r["n"] == n_out and 0.0 < r["s"] - 1.0 < 0.5]
        out[key] = statistics.median(ms) if len(ms) >= 50 else _DEFAULT_IDDAA_MARGIN
    return out


def _fd_index(con: sqlite3.Connection, start: str, end: str) -> dict[tuple[str, str], list[sqlite3.Row]]:
    idx: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for r in con.execute(
        """SELECT league, date, home, away, hg, ag, o1, ox, o2, o_over25, o_under25 FROM hist_odds_matches
           WHERE source='football-data' AND date BETWEEN ? AND ?""",
        (start[:10], end[:10]),
    ):
        idx[(r["league"], r["date"])].append(r)
    return idx


def _find_fd(m: sqlite3.Row, idx: dict[tuple[str, str], list[sqlite3.Row]]) -> sqlite3.Row | None:
    """ESPN maçı -> football-data satırı: aynı lig, ±1 gün, takım adı benzerliği; skor da tutmalı."""
    d0 = datetime.fromisoformat(m["date_utc"][:10])
    best: tuple[float, sqlite3.Row | None] = (0.0, None)
    for dd in (0, -1, 1):
        for r in idx.get((m["league"], (d0 + timedelta(days=dd)).strftime("%Y-%m-%d")), []):
            sh, sa = similarity(m["hn"], r["home"]), similarity(m["an"], r["away"])
            ok = (sh >= _FD_MATCH_MIN and sa >= _FD_MATCH_MIN) or (
                max(sh, sa) >= _FD_MATCH_STRONG and min(sh, sa) >= _FD_MATCH_WEAK)
            if ok and r["hg"] == m["hg"] and r["ag"] == m["ag"] and sh + sa > best[0]:
                best = (sh + sa, r)
    return best[1]


def _market_rows(fd: sqlite3.Row, kickoff: str) -> list[dict[str, Any]]:
    rows = [{"market_key": MS_KEY, "outcome_no": i + 1, "outcome_name": n, "odd": float(o), "mbs": 1, "fetched_at": kickoff}
            for i, (n, o) in enumerate((("1", fd["o1"]), ("0", fd["ox"]), ("2", fd["o2"])))]
    if fd["o_over25"] and fd["o_under25"]:
        rows += [{"market_key": AU25_KEY, "outcome_no": 1, "outcome_name": "Alt", "odd": float(fd["o_under25"]), "mbs": 1,
                  "fetched_at": kickoff},
                 {"market_key": AU25_KEY, "outcome_no": 2, "outcome_name": "Üst", "odd": float(fd["o_over25"]), "mbs": 1,
                  "fetched_at": kickoff}]
    return rows


def _pick_record(con: sqlite3.Connection, p: dict[str, Any], pick: dict[str, Any] | None,
                 margins: dict[str, float]) -> dict[str, Any] | None:
    """Seçimin sonucu ve iki orandaki kârı. pick: market_key, key, line, selection, odd, p_model, p_market."""
    if pick is None:
        return None
    res = settle_selection(con, {"match_id": p["match"]["id"], "key": pick["key"], "line": pick["line"],
                                 "outcome_name": pick["selection"], "family": pick.get("family", "")})
    if res not in ("won", "lost"):
        return None
    mkt = next(m for m in p["iddaa"]["markets"] if m["market_key"] == pick["market_key"])
    m_src = float(mkt["margin"])
    m_idd = margins.get(pick["market_key"], _DEFAULT_IDDAA_MARGIN)
    odd_idd = max(1.01, float(pick["odd"]) * (1.0 + m_src) / (1.0 + m_idd))
    won = res == "won"
    return {"key": pick["key"], "selection": pick["selection"], "odd": float(pick["odd"]), "odd_iddaa": odd_idd,
            "p_model": float(pick["p_model"]), "p_market": float(pick["p_market"]), "won": won,
            "profit": float(pick["odd"]) - 1.0 if won else -1.0, "profit_iddaa": odd_idd - 1.0 if won else -1.0}


def _summ(recs: list[dict[str, Any]], seed: int = 7) -> dict[str, Any]:
    n = len(recs)
    if n == 0:
        return {"n": 0}
    hits = sum(r["won"] for r in recs)
    prof = [r["profit"] for r in recs]
    prof_i = [r["profit_iddaa"] for r in recs]
    rng = random.Random(seed)
    boots = sorted(sum(prof_i[rng.randrange(n)] for _ in range(n)) / n for _ in range(_BOOT))
    return {
        "n": n, "hits": hits, "hit_rate": hits / n,
        "avg_odd": sum(r["odd"] for r in recs) / n,
        "p_model": sum(r["p_model"] for r in recs) / n,
        "p_market": sum(r["p_market"] for r in recs) / n,
        "edge_vs_market": hits / n - sum(r["p_market"] for r in recs) / n,
        "roi_close": sum(prof) / n,
        "roi_iddaa": sum(prof_i) / n,
        "roi_iddaa_ci95": [boots[int(0.025 * _BOOT)], boots[int(0.975 * _BOOT) - 1]],
    }


def _groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scout = [r["scout_pick"] for r in rows if r["scout_pick"]]
    out: dict[str, Any] = {
        "scout": _summ(scout),
        "scout_yuksek": _summ([r["scout_pick"] for r in rows if r["scout_pick"] and r["confidence"] == "yüksek"]),
        "scout_orta": _summ([r["scout_pick"] for r in rows if r["scout_pick"] and r["confidence"] == "orta"]),
        "model_all": _summ([r["model_pick"] for r in rows if r["model_pick"]]),
        "model_on_pas": _summ([r["model_pick"] for r in rows if r["model_pick"] and r["verdict"] == "pas"]),
        "model_on_oneri": _summ([r["model_pick"] for r in rows if r["model_pick"] and r["verdict"] == "oneri"]),
    }
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in scout:
        by_key[s["key"]].append(s)
    out["scout_by_market"] = {k: _summ(v) for k, v in by_key.items()}
    return out


def run_scout_backtest(con: sqlite3.Connection, progress: Progress, days: int = BACKTEST_DAYS) -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - timedelta(days=days)
    params = load_params(con)
    margins = iddaa_margins(con)
    idx = _fd_index(con, _iso(start - timedelta(days=2)), _iso(now))
    fd_leagues = {lg for lg, _ in idx}
    matches = con.execute(
        """SELECT m.*, th.name hn, ta.name an,
                  COALESCE(m.ft90_home, CASE WHEN m.extra_time=0 THEN m.home_goals END) hg,
                  COALESCE(m.ft90_away, CASE WHEN m.extra_time=0 THEN m.away_goals END) ag
           FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
           WHERE m.completed=1 AND m.date_utc >= ? AND m.date_utc < ? ORDER BY m.date_utc""",
        (_iso(start), _iso(now)),
    ).fetchall()
    matches = [m for m in matches if m["league"] in fd_leagues and m["hg"] is not None]
    progress(f"Scout backtest: {len(matches)} maç ({_iso(start)[:10]} → {_iso(now)[:10]}), iddaa marjı {margins}")
    rows: list[dict[str, Any]] = []
    stats = Counter()
    wk = start
    while wk < now:
        nxt = wk + timedelta(days=7)
        week = [m for m in matches if _iso(wk) <= m["date_utc"] < _iso(nxt)]
        if week:
            fm = fit_all(con, as_of=wk, params=params, with_aux=False)
            for m in week:
                fd = _find_fd(m, idx)
                if fd is None:
                    stats["oran_eslesmedi"] += 1
                    continue
                p = predict_match(con, fm, m, with_sim=False, market_rows=_market_rows(fd, m["date_utc"]))
                if p is None or not p.get("covered") or not p.get("iddaa"):
                    stats["kapsam_disi"] += 1
                    continue
                ctx = match_context(con, p, asof=True)
                v = ctx["scout"]["verdict"]
                mp = model_pick(p)
                mp_d = ({"market_key": mp.market_key, "key": mp.key, "line": mp.line, "selection": mp.outcome_name,
                         "odd": mp.odd, "p_model": mp.p_model, "p_market": mp.p_market, "family": mp.family}
                        if mp is not None else None)
                sp = v.get("pick")
                rows.append({
                    "match_id": m["id"], "date": m["date_utc"][:10], "league": m["league"], "verdict": v["verdict"],
                    "confidence": v.get("confidence"), "reason": v["headline"],
                    "scout_pick": _pick_record(con, p, sp, margins) if sp else None,
                    "model_pick": _pick_record(con, p, mp_d, margins),
                })
                stats["degerlendirildi"] += 1
        progress(f"Scout backtest: {wk.date()} haftası · toplam {stats['degerlendirildi']} maç")
        wk = nxt

    rows.sort(key=lambda r: r["date"])
    half = len(rows) // 2
    verdicts = Counter(r["verdict"] for r in rows)
    pas_reasons = Counter(r["reason"] for r in rows if r["verdict"] == "pas").most_common(6)
    by_league: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["scout_pick"]:
            by_league[r["league"]].append(r["scout_pick"])
    result = {
        "created_at": _iso(datetime.now(timezone.utc)),
        "window": [_iso(start), _iso(now)],
        "n_matches": len(rows), "skipped": dict(stats), "iddaa_margins": margins,
        "verdicts": dict(verdicts), "pas_reasons": pas_reasons,
        "all": _groups(rows),
        "first_half": _groups(rows[:half]), "second_half": _groups(rows[half:]),
        "by_league": {lg: _summ(v) for lg, v in sorted(by_league.items(), key=lambda x: -len(x[1])) if len(v) >= 20},
        "league_names": {lg: f"{LEAGUE_BY_SLUG[lg].country} · {LEAGUE_BY_SLUG[lg].name}" for lg in by_league
                         if lg in LEAGUE_BY_SLUG},
        "notes": [
            "Oranlar football-data kapanış ortalamasıdır (iddaa geçmiş oranı yok); 'iddaa' getirisi aynı adil olasılığın "
            "iddaa'nın güncel ortalama marjıyla fiyatlanmış halidir.",
            "Geçmişte yalnız MS ve 2.5 gol Alt/Üst oranı var: scout bu iki pazardan seçebildi (canlıda çifte şans, KG, "
            "handikap da seçebilir).",
            "Simülasyon (oyuncu profili) ve puan durumu bölge notları geçmişte yok; puan durumu sonuçlardan kuruldu.",
        ],
    }
    s = result["all"]["scout"]
    progress(f"Scout backtest: {verdicts} · scout önerileri n={s.get('n')} isabet={s.get('hit_rate', 0):.3f} "
             f"ROI kapanış={s.get('roi_close', 0):+.3f} iddaa={s.get('roi_iddaa', 0):+.3f}")
    with db.tx(con):
        db.meta_set(con, "scout_backtest", result)
    return result

