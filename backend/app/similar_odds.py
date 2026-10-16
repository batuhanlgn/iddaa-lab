"""Benzer oran: bültendeki MS (1X2) oranına çok yakın oranla oynanmış geçmiş maçlar nasıl bitti?

Havuz iki kaynaktan dolar (tablo: hist_odds_matches):
- football-data.co.uk: ~10 sezon, 35 lig, kapanış (yoksa açılış) pazar oranları — bkz. sources/footballdata.py
- kendi iddaa arşivimiz: ESPN maçıyla eşleşmiş, bitmiş etkinliklerin maç başlamadan önceki SON MS oranları
  (odds_history, market_key '1:1:', outcome_no 1/2/3 = "1"/"0"/"2").
Oranlar farklı bahisçilerden ve farklı marjlarla geldiği için karşılaştırma marjı arındırılmış adil olasılıklar
(f = devig) üzerinden yapılır.

Benzerlik tanımı: hedefin adil olasılıkları t_i, geçmiş maçınki f_i (i ∈ 1, X, 2). Sonuç başına oran r_i = f_i / t_i
(adil oran oranının tersiyle aynı). Sonuç benzerliği s_i = min(r_i, 1/r_i) — simetrik: %5 yüksek ya da %5 düşük aynı
cezayı alır. Maç benzerliği = min_i s_i = 1 − en büyük göreli sapma. Eşik 0.95 ⇔ üç sonucun adil oranının her biri
hedefin [0.95×, 1/0.95×] aralığında.
"""
from __future__ import annotations

import asyncio
import math
import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, NamedTuple

from . import db
from .ingest import Progress, iso, parse_iso, utcnow
from .model.markets import devig
from .sources import footballdata as fd

SIMILAR_MIN = 0.95          # varsayılan benzerlik eşiği
LOW_SAMPLE_N = 30           # bunun altında sonuç dağılımı "düşük örneklem" uyarısıyla gösterilir
TOP_SCORES_N = 6
FD_REFRESH_HOURS = 20.0     # içinde bulunulan sezon/ek lig dosyaları en fazla bu sıklıkta yeniden indirilir
FD_EXTRA_TAIL_DAYS = 120    # ek lig dosyası ilk tam yüklemeden sonra yalnızca son bu kadar günü günceller
SOURCE_FD = "football-data"
SOURCE_IDDAA = "iddaa"
_EPS = 1e-9

SIMILARITY_DEFINITION = (
    "Üç sonucun (1, X, 2) marjı arındırılmış adil oranlarının her biri hedefin ±%5'i içinde: "
    "oran/hedef ∈ [0.95, 1/0.95]. Benzerlik = 1 − en büyük göreli sapma."
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS hist_odds_matches (
    source TEXT NOT NULL,             -- football-data | iddaa
    src_key TEXT NOT NULL,            -- football-data: lig:tarih:ev:deplasman, iddaa: ESPN maç kimliği
    league TEXT NOT NULL,             -- ESPN lig kısaltması (eng.1, tur.1 ...)
    date TEXT NOT NULL,               -- YYYY-MM-DD
    home TEXT NOT NULL,
    away TEXT NOT NULL,
    hg INTEGER NOT NULL,              -- 90 dakika skoru
    ag INTEGER NOT NULL,
    hthg INTEGER,
    htag INTEGER,
    o1 REAL NOT NULL,                 -- ham 1X2 oranı
    ox REAL NOT NULL,
    o2 REAL NOT NULL,
    f1 REAL NOT NULL,                 -- marjı arındırılmış adil olasılık
    fx REAL NOT NULL,
    f2 REAL NOT NULL,
    odds_src TEXT,                    -- hangi oran sütunu (AvgC, PSC, B365 ... / iddaa)
    PRIMARY KEY (source, src_key)
);
-- kapsayan indeks: arama ve özetler tabloya inmeden indeksten okunur
CREATE INDEX IF NOT EXISTS ix_hist_odds_f ON hist_odds_matches(f1, f2, fx, hg, ag, hthg, htag, source, league, date);
"""


# ---------------------------------------------------------------------------------------------------------------
# Havuzu doldurma
# ---------------------------------------------------------------------------------------------------------------

def _due(meta: dict[str, Any] | None, past: bool, now: datetime, refresh_hours: float) -> bool:
    """Geçmiş sezon dosyası, sezon bittikten sonra bir kez indirildiyse (final) bir daha indirilmez."""
    if not meta:
        return True
    if past and meta.get("final"):
        return False
    fetched = meta.get("fetched_at")
    if not fetched:
        return True
    return now - parse_iso(fetched) >= timedelta(hours=refresh_hours)


def _fd_row(m: fd.HistMatch) -> tuple[Any, ...]:
    f1, fx, f2 = devig([m.o1, m.ox, m.o2])
    return (SOURCE_FD, m.key, m.league, m.date, m.home, m.away, m.hg, m.ag, m.hthg, m.htag,
            m.o1, m.ox, m.o2, float(f1), float(fx), float(f2), m.odds_src)


_INSERT = "INSERT OR REPLACE INTO hist_odds_matches VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"

_IDDAA_CLOSING_SQL = """
WITH last AS (
    SELECT h.event_id, h.outcome_no, h.odd,
           ROW_NUMBER() OVER (PARTITION BY h.event_id, h.outcome_no ORDER BY h.fetched_at DESC) rn
    FROM odds_history h JOIN iddaa_events e ON e.id = h.event_id
    WHERE h.market_key = '1:1:' AND h.fetched_at < e.kickoff_utc AND e.espn_match_id IS NOT NULL
)
SELECT m.id match_id, m.league, m.date_utc, th.name home, ta.name away,
       COALESCE(m.ft90_home, CASE WHEN m.extra_time = 0 THEN m.home_goals END) hg,
       COALESCE(m.ft90_away, CASE WHEN m.extra_time = 0 THEN m.away_goals END) ag,
       m.home_ht, m.away_ht,
       MAX(CASE WHEN l.outcome_no = 1 THEN l.odd END) o1,
       MAX(CASE WHEN l.outcome_no = 2 THEN l.odd END) ox,
       MAX(CASE WHEN l.outcome_no = 3 THEN l.odd END) o2
FROM last l
JOIN iddaa_events e ON e.id = l.event_id
JOIN matches m ON m.id = e.espn_match_id AND m.completed = 1
JOIN teams th ON th.id = m.home_id
JOIN teams ta ON ta.id = m.away_id
WHERE l.rn = 1
GROUP BY e.id
ORDER BY e.id
"""


def _iddaa_rows(con: sqlite3.Connection) -> list[tuple[Any, ...]]:
    """Kendi arşivimizden kapanış MS oranlı, bitmiş maçlar. Aynı ESPN maçına bağlı birden çok etkinlik varsa
    sonuncusu kalır (src_key = ESPN maç kimliği)."""
    out: dict[str, tuple[Any, ...]] = {}
    for r in con.execute(_IDDAA_CLOSING_SQL):
        if r["hg"] is None or r["ag"] is None or None in (r["o1"], r["ox"], r["o2"]):
            continue
        o1, ox, o2 = float(r["o1"]), float(r["ox"]), float(r["o2"])
        if min(o1, ox, o2) <= 1.0:
            continue
        f1, fx, f2 = devig([o1, ox, o2])
        hthg, htag = r["home_ht"], r["away_ht"]
        if hthg is None or htag is None or hthg > r["hg"] or htag > r["ag"]:
            hthg = htag = None
        out[str(r["match_id"])] = (SOURCE_IDDAA, str(r["match_id"]), r["league"], r["date_utc"][:10], r["home"], r["away"],
                                   int(r["hg"]), int(r["ag"]), hthg, htag, o1, ox, o2,
                                   float(f1), float(fx), float(f2), "iddaa")
    return list(out.values())


async def ingest_history(con: sqlite3.Connection, progress: Progress, *, fetch: fd.Fetcher | None = None,
                         today: date | None = None, seasons: int = fd.FD_SEASONS,
                         refresh_hours: float = FD_REFRESH_HOURS) -> dict[str, int]:
    """football-data arşivini indir/güncelle + iddaa arşivinden kapanış oranlı satırları yeniden kur.

    - Geçmiş sezon dosyaları sezon bittikten sonra bir kez indirilir (meta 'fdh:{sezon}:{kod}' final=true).
    - İçinde bulunulan sezon (19 dosya) ve ek ligler (16 dosya) en fazla refresh_hours'ta bir yeniden indirilir.
    - İlk çalıştırma ~190+16 istek (~4 dk); sonraki günlük çalıştırmalar ~35 istek (~45 sn); arada çağrılırsa 0 istek.
    - Pencereden (seasons) eskiye düşen football-data satırları silinir.
    fetch: URL -> CSV baytları (404 için None). Verilmezse nazik HTTP istemcisi kullanılır (testte yerel dosyalar).
    Hiçbir dosya alınamazsa (ağ/erişim engeli) iddaa satırları yine yazılır, ardından RuntimeError yükselir.
    """
    today = today or utcnow().date()
    now = utcnow()
    cur = fd.season_start_year(today)
    first = cur - seasons + 1
    min_date = date(first, fd.FD_SEASON_START_MONTH, 1).isoformat()

    # (meta anahtarı, url, lig, geçmiş sezon mu, ek lig mi)
    jobs: list[tuple[str, str, str, bool, bool]] = []
    for y in range(first, cur + 1):
        s = fd.season_code(y)
        for lg in fd.FD_MAIN:
            jobs.append((f"fdh:{s}:{lg.code}", fd.main_url(s, lg.code), lg.slug, y < cur, False))
    for lg in fd.FD_EXTRA:
        jobs.append((f"fdh:new:{lg.code}", fd.extra_url(lg.code), lg.slug, False, True))
    metas: dict[str, dict[str, Any] | None] = {j[0]: db.meta_get(con, j[0]) for j in jobs}
    todo = [j for j in jobs if _due(metas[j[0]], j[3], now, refresh_hours)]
    progress(f"benzer oran: {len(todo)}/{len(jobs)} football-data dosyası indirilecek")

    async def run(fetcher: fd.Fetcher) -> list[bytes | None | BaseException]:
        return await asyncio.gather(*(fetcher(j[1]) for j in todo), return_exceptions=True)

    if fetch is not None:
        results = await run(fetch)
    else:
        async with fd.FdClient() as client:
            results = await run(client.get_bytes)

    fetched_at = iso(now)
    tail_from = (today - timedelta(days=FD_EXTRA_TAIL_DAYS)).isoformat()
    n_rows = n_missing = 0
    errors: list[str] = []
    parsed: list[tuple[tuple[str, str, str, bool, bool], list[fd.HistMatch] | None]] = []
    for job, res in zip(todo, results):
        key, url, slug, past, extra = job
        if isinstance(res, BaseException):
            errors.append(f"{url}: {res}")
            continue
        if res is None:
            parsed.append((job, None))
            continue
        lo = min_date
        prev = metas[key]
        if extra and prev and prev.get("status") == "ok":
            lo = max(min_date, tail_from)
        parsed.append((job, fd.parse_csv(fd.decode_csv(res), slug, min_date=lo)))

    id_rows = _iddaa_rows(con)
    with db.tx(con):
        for (key, url, slug, past, extra), ms in parsed:
            if ms is None:
                n_missing += 1
                db.meta_set(con, key, {"status": "missing", "fetched_at": fetched_at, "final": past, "rows": 0})
                continue
            con.executemany(_INSERT, [_fd_row(m) for m in ms])
            n_rows += len(ms)
            db.meta_set(con, key, {"status": "ok", "fetched_at": fetched_at, "final": past, "rows": len(ms)})
        pruned = con.execute("DELETE FROM hist_odds_matches WHERE source=? AND date < ?", (SOURCE_FD, min_date)).rowcount
        con.execute("DELETE FROM hist_odds_matches WHERE source=?", (SOURCE_IDDAA,))
        con.executemany(_INSERT, id_rows)
        total = con.execute("SELECT COUNT(*) FROM hist_odds_matches").fetchone()[0]
        db.meta_set(con, "similar_odds_last_ingest", {"at": fetched_at, "pool": total, "errors": len(errors)})

    progress(f"benzer oran: {len(parsed) - n_missing} dosya ({n_rows} satır) güncellendi, {n_missing} dosya yok, "
             f"{len(id_rows)} iddaa maçı, havuz {total} maç" + (f", {len(errors)} HATA" if errors else ""))
    for e in errors[:5]:
        progress(f"benzer oran indirme hatası: {e}")
    if todo and len(errors) == len(todo):
        raise RuntimeError(f"football-data.co.uk dosyalarının hiçbiri alınamadı ({len(errors)} hata); ilk hata: {errors[0]}")
    return {"files_due": len(todo), "files_ok": len(parsed) - n_missing, "files_missing": n_missing,
            "fd_rows": n_rows, "iddaa_rows": len(id_rows), "pruned": pruned, "pool": int(total), "errors": len(errors)}


# ---------------------------------------------------------------------------------------------------------------
# Arama
# ---------------------------------------------------------------------------------------------------------------

def _wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, c - h), min(1.0, c + h)]


def _sim(f: tuple[float, float, float], t: tuple[float, float, float]) -> float:
    return min(min(fi / ti, ti / fi) for fi, ti in zip(f, t))


class _Cand(NamedTuple):
    rowid: int
    source: str
    league: str
    date: str
    hg: int
    ag: int
    hthg: int | None
    htag: int | None
    f1: float
    fx: float
    f2: float
    sim: float


def _examples(con: sqlite3.Connection, cands: list[_Cand]) -> list[dict[str, Any]]:
    """Örnek maçların ad/oran alanları yalnızca gösterilecek satırlar için ikinci sorguyla okunur."""
    if not cands:
        return []
    cur = con.cursor()
    cur.row_factory = None
    ids = [c.rowid for c in cands]
    det = {r[0]: r for r in cur.execute(
        f"SELECT rowid, home, away, o1, ox, o2 FROM hist_odds_matches WHERE rowid IN ({','.join('?' * len(ids))})", ids)}
    out = []
    for c in cands:
        _rid, home, away, o1, ox, o2 = det[c.rowid]
        name, country = fd.league_info(c.league)
        out.append({
            "source": c.source, "date": c.date, "league": c.league, "league_name": name, "country": country,
            "home": home, "away": away, "hg": c.hg, "ag": c.ag, "hthg": c.hthg, "htag": c.htag,
            "odds": {"1": o1, "0": ox, "2": o2}, "similarity": round(c.sim, 4),
        })
    return out


def _dedupe(cands: list[_Cand]) -> list[_Cand]:
    """Aynı maç hem football-data'da hem iddaa arşivinde olabilir (takım adları farklı). Aday kümesi zaten dar
    olduğundan: aynı lig, ±1 gün ve aynı skorlu football-data satırı varsa iddaa satırı atılır."""
    fd_keys = {(c.league, c.date, c.hg, c.ag) for c in cands if c.source == SOURCE_FD}
    if not fd_keys:
        return cands
    out = []
    for c in cands:
        if c.source == SOURCE_IDDAA:
            d = date.fromisoformat(c.date)
            if any((c.league, (d + timedelta(days=k)).isoformat(), c.hg, c.ag) in fd_keys for k in (-1, 0, 1)):
                continue
        out.append(c)
    return out


def _pool_size(con: sqlite3.Connection) -> int:
    """Havuz büyüklüğü son ingest'te meta'ya yazılır (her çağrıda COUNT(*) taraması yapılmaz)."""
    m = db.meta_get(con, "similar_odds_last_ingest")
    if isinstance(m, dict) and isinstance(m.get("pool"), int):
        return m["pool"]
    return int(con.execute("SELECT COUNT(*) FROM hist_odds_matches").fetchone()[0])


def find_similar_probs(con: sqlite3.Connection, probs: tuple[float, float, float] | list[float], *,
                       min_similarity: float = SIMILAR_MIN, limit_examples: int = 12,
                       odds: tuple[float, float, float] | None = None, basis: str = "model") -> dict[str, Any]:
    """Hedef adil 1X2 olasılıklarına (ör. modelin MS olasılıkları) benzer geçmiş maçlar. Olasılıklar normalize edilir.
    SQL'de kapsayan indeksle aralık filtresi (f1, f2, fx ∈ [t·s, t/s]; tabloya inilmez), ardından Python'da kesin
    benzerlik ve özetler; ad/oran alanları yalnızca örnek satırlar için okunur."""
    if len(probs) != 3 or any(not (0.0 < float(p) < 1.0) for p in probs):
        raise ValueError(f"Geçersiz 1X2 olasılıkları: {probs}")
    if not (0.5 <= min_similarity <= 1.0):
        raise ValueError(f"Benzerlik eşiği 0.5-1 arasında olmalı: {min_similarity}")
    tot = float(sum(probs))
    t = (float(probs[0]) / tot, float(probs[1]) / tot, float(probs[2]) / tot)
    s = min_similarity
    cur = con.cursor()
    cur.row_factory = None
    rows = cur.execute(
        """SELECT rowid, source, league, date, hg, ag, hthg, htag, f1, fx, f2
           FROM hist_odds_matches
           WHERE f1 BETWEEN ? AND ? AND f2 BETWEEN ? AND ? AND fx BETWEEN ? AND ?""",
        (t[0] * s - _EPS, t[0] / s + _EPS, t[2] * s - _EPS, t[2] / s + _EPS, t[1] * s - _EPS, t[1] / s + _EPS),
    ).fetchall()
    cands = []
    for r in rows:
        x = _sim((r[8], r[9], r[10]), t)
        if x >= s - _EPS:
            cands.append(_Cand(*r, x))
    matched = _dedupe(cands)
    n = len(matched)

    target: dict[str, Any] = {
        "basis": basis,
        "odds": {"1": odds[0], "0": odds[1], "2": odds[2]} if odds else None,
        "probs": {"1": t[0], "0": t[1], "2": t[2]},
        "fair_odds": {"1": 1 / t[0], "0": 1 / t[1], "2": 1 / t[2]},
    }
    out: dict[str, Any] = {
        "n": n, "pool_size": _pool_size(con), "low_sample": n < LOW_SAMPLE_N, "min_sample": LOW_SAMPLE_N,
        "similarity": {"min": s, "definition": SIMILARITY_DEFINITION},
        "target": target,
        "outcomes": None, "outcomes_ci95": None, "pool_implied": None,
        "top_scores": [], "over25": None, "btts": None, "avg_goals": None, "ht": None,
        "sources": {SOURCE_FD: 0, SOURCE_IDDAA: 0}, "leagues": [], "date_range": None,
        "closest": [], "recent": [],
    }
    if n == 0:
        return out

    res = Counter("1" if c.hg > c.ag else "0" if c.hg == c.ag else "2" for c in matched)
    out["outcomes"] = {k: res[k] / n for k in ("1", "0", "2")}
    out["outcomes_ci95"] = {k: _wilson(res[k], n) for k in ("1", "0", "2")}
    out["pool_implied"] = {
        "1": sum(c.f1 for c in matched) / n,
        "0": sum(c.fx for c in matched) / n,
        "2": sum(c.f2 for c in matched) / n,
    }
    scores = Counter((c.hg, c.ag) for c in matched)
    out["top_scores"] = [{"score": f"{h}-{a}", "hg": h, "ag": a, "count": k, "share": k / n}
                         for (h, a), k in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_SCORES_N]]
    out["over25"] = sum(1 for c in matched if c.hg + c.ag >= 3) / n
    out["btts"] = sum(1 for c in matched if c.hg > 0 and c.ag > 0) / n
    out["avg_goals"] = sum(c.hg + c.ag for c in matched) / n
    ht = [(c.hthg, c.htag) for c in matched if c.hthg is not None and c.htag is not None]
    if ht:
        hc = Counter("1" if h > a else "0" if h == a else "2" for h, a in ht)
        out["ht"] = {"n": len(ht), "outcomes": {k: hc[k] / len(ht) for k in ("1", "0", "2")}}
    src = Counter(c.source for c in matched)
    out["sources"] = {SOURCE_FD: src.get(SOURCE_FD, 0), SOURCE_IDDAA: src.get(SOURCE_IDDAA, 0)}
    lgs = Counter(c.league for c in matched)
    out["leagues"] = [{"league": lg, "name": fd.league_info(lg)[0], "country": fd.league_info(lg)[1], "count": k}
                      for lg, k in lgs.most_common(5)]
    dates = [c.date for c in matched]
    out["date_range"] = {"from": min(dates), "to": max(dates)}
    lim = max(0, limit_examples)
    by_date = sorted(matched, key=lambda c: c.date, reverse=True)
    out["recent"] = _examples(con, by_date[:lim])
    # en yakın: benzerlik azalan; eşitlikte yeni maç önce (sıralama kararlı)
    out["closest"] = _examples(con, sorted(by_date, key=lambda c: -c.sim)[:lim])
    return out


def find_similar(con: sqlite3.Connection, odds: tuple[float, float, float], *, min_similarity: float = SIMILAR_MIN,
                 limit_examples: int = 12) -> dict[str, Any]:
    """Hedef iddaa MS oranları (1, X, 2) -> marjı arındırılıp find_similar_probs ile aranır."""
    if len(odds) != 3 or any(float(o) <= 1.0 for o in odds):
        raise ValueError(f"Geçersiz MS oranları: {odds}")
    o = (float(odds[0]), float(odds[1]), float(odds[2]))
    p = devig(list(o))
    return find_similar_probs(con, (float(p[0]), float(p[1]), float(p[2])), min_similarity=min_similarity,
                              limit_examples=limit_examples, odds=o, basis="iddaa")


def payload_target(payload: dict[str, Any]) -> tuple[str, tuple[float, float, float]] | None:
    """Tahmin yükünden hedef: önce iddaa MS oranları ("iddaa", oranlar), yoksa modelin MS olasılıkları ("model", p)."""
    idd = payload.get("iddaa") or {}
    for m in idd.get("markets", []):
        if m.get("key") == "ms" and not m.get("line"):
            o = {x["name"]: float(x["odd"]) for x in m.get("outcomes", [])}
            if all(k in o and o[k] > 1.0 for k in ("1", "0", "2")):
                return "iddaa", (o["1"], o["0"], o["2"])
    for m in payload.get("markets") or []:
        if m.get("key") == "ms" and not m.get("line"):
            p = {x["name"]: float(x["p_model"]) for x in m.get("outcomes", [])}
            if all(k in p and 0.0 < p[k] < 1.0 for k in ("1", "0", "2")):
                return "model", (p["1"], p["0"], p["2"])
    return None


def similar_for_payload(con: sqlite3.Connection, payload: dict[str, Any], *, min_similarity: float = SIMILAR_MIN,
                        limit_examples: int = 12) -> dict[str, Any] | None:
    """Maç sayfası/dışa aktarım için tek çağrı: hedef yoksa None."""
    tg = payload_target(payload)
    if tg is None:
        return None
    basis, v = tg
    if basis == "iddaa":
        return find_similar(con, v, min_similarity=min_similarity, limit_examples=limit_examples)
    return find_similar_probs(con, v, min_similarity=min_similarity, limit_examples=limit_examples, basis="model")
