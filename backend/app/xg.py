"""Maç başı beklenen gol (xG): Understat'ten toplama, ESPN maçlarıyla eşleştirme ve saklama.

Eşleştirme: aynı lig + tarih (±1 gün) + takım adı benzerliği + skor tutarlılığı (Understat skoru = ESPN 90 dk skoru).
Bir ESPN maçına en fazla bir Understat satırı bağlanır (en yüksek benzerlik kazanır).
Biten sezonlar bir kez (final), içinde bulunulan sezon en fazla XG_REFRESH_HOURS'ta bir indirilir.
Model xG'yi yalnızca backtest'te doğrulanmış bir ağırlıkla kullanır (model_params.xg_weight); veri yoksa davranış aynıdır.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import db
from .config import HISTORY_MONTHS
from .matching import norm, similarity
from .sources import understat as us

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

XG_REFRESH_HOURS = 12.0
XG_MATCH_MIN = 0.55       # iki takım adı da en az bu kadar benzer
XG_MATCH_STRONG = 0.9     # ya da biri neredeyse kesin ...
XG_MATCH_WEAK = 0.3       # ... ve diğeri en az bu kadar (skor ve tarih zaten tutuyor)

# Understat'in kendine özgü adları -> ESPN'deki yaygın ad (benzerlik hesabından önce)
US_ALIASES: dict[str, str] = {
    "rasenballsport leipzig": "rb leipzig",
    "borussia m. gladbach": "borussia monchengladbach",
    "fc heidenheim": "1. fc heidenheim 1846",
    "parma calcio 1913": "parma",
    "fk akhmat": "akhmat grozny",
    "pari nn": "nizhny novgorod",
    "krylya sovetov samara": "krylia sovetov",
    "fakel": "fakel voronezh",
}


@dataclass(frozen=True)
class EspnMatch:
    id: str
    date: datetime
    home: str
    away: str
    hg: int
    ag: int


def _us_name(n: str) -> str:
    k = norm(n)
    return US_ALIASES.get(k, n)


def match_rows(espn: list[EspnMatch], rows: list[us.UsMatch]) -> dict[str, tuple[us.UsMatch, float]]:
    """ESPN maç kimliği -> (Understat satırı, benzerlik toplamı). Skor ve ±1 gün zorunlu; ad benzerliği eşikli."""
    by_day: dict[date, list[EspnMatch]] = {}
    for m in espn:
        by_day.setdefault(m.date.date(), []).append(m)
    cands: list[tuple[float, str, us.UsMatch]] = []
    for r in rows:
        d0 = us.us_datetime(r.date_utc).date()
        hn, an = _us_name(r.home), _us_name(r.away)
        for dd in (0, -1, 1):
            for m in by_day.get(d0 + timedelta(days=dd), []):
                if m.hg != r.hg or m.ag != r.ag:
                    continue
                sh, sa = similarity(hn, m.home), similarity(an, m.away)
                ok = (sh >= XG_MATCH_MIN and sa >= XG_MATCH_MIN) or (
                    max(sh, sa) >= XG_MATCH_STRONG and min(sh, sa) >= XG_MATCH_WEAK)
                if ok:
                    cands.append((sh + sa - 0.05 * abs(dd), m.id, r))
    # Açgözlü atama: en güçlü adaydan başla; her ESPN maçı ve her Understat satırı bir kez kullanılır
    out: dict[str, tuple[us.UsMatch, float]] = {}
    used: set[int] = set()
    for sc, mid, r in sorted(cands, key=lambda c: -c[0]):
        if mid in out or id(r) in used:
            continue
        out[mid] = (r, sc)
        used.add(id(r))
    return out


def espn_matches(con: sqlite3.Connection, league: str, start: str, end: str) -> list[EspnMatch]:
    rows = con.execute(
        """SELECT m.id, m.date_utc, th.name hn, ta.name an,
                  COALESCE(m.ft90_home, CASE WHEN m.extra_time=0 THEN m.home_goals END) hg,
                  COALESCE(m.ft90_away, CASE WHEN m.extra_time=0 THEN m.away_goals END) ag
           FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
           WHERE m.league=? AND m.completed=1 AND m.date_utc >= ? AND m.date_utc < ?""",
        (league, start, end),
    ).fetchall()
    return [EspnMatch(r["id"], datetime.fromisoformat(r["date_utc"].replace("Z", "+00:00")), r["hn"], r["an"],
                      int(r["hg"]), int(r["ag"]))
            for r in rows if r["hg"] is not None and r["ag"] is not None]


def store_league_rows(con: sqlite3.Connection, league: str, rows: list[us.UsMatch], fetched_at: str,
                      source: str = us.US_SOURCE) -> dict[str, int]:
    """Understat satırlarını ESPN maçlarına bağlayıp match_xg'ye yazar (aynı maç varsa günceller)."""
    if not rows:
        return {"rows": 0, "matched": 0}
    days = [us.us_datetime(r.date_utc) for r in rows]
    start = (min(days) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = (max(days) + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    got = match_rows(espn_matches(con, league, start, end), rows)
    with db.tx(con):
        con.executemany(
            """INSERT INTO match_xg(match_id, xg_home, xg_away, source, source_id, fetched_at) VALUES(?,?,?,?,?,?)
               ON CONFLICT(match_id) DO UPDATE SET xg_home=excluded.xg_home, xg_away=excluded.xg_away,
               source=excluded.source, source_id=excluded.source_id, fetched_at=excluded.fetched_at""",
            [(mid, r.xg_home, r.xg_away, source, r.us_id, fetched_at) for mid, (r, _) in got.items()],
        )
    return {"rows": len(rows), "matched": len(got)}


def window_seasons(today: date, months: int = HISTORY_MONTHS) -> list[int]:
    """Model veri penceresine (HISTORY_MONTHS) giren Understat sezonları (başlangıç yılları)."""
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    first = us.season_start_year(date(y, m, 1))
    return list(range(first, us.season_start_year(today) + 1))


def _due(meta: dict[str, Any] | None, finished: bool, now: datetime, refresh_hours: float) -> bool:
    if not meta:
        return True
    if finished and meta.get("final"):
        return False
    fetched = meta.get("fetched_at")
    if not fetched:
        return True
    return now - datetime.fromisoformat(fetched.replace("Z", "+00:00")) >= timedelta(hours=refresh_hours)


async def ingest_xg(con: sqlite3.Connection, progress: Progress, *, fetch: us.Fetcher | None = None,
                    today: date | None = None, refresh_hours: float = XG_REFRESH_HOURS) -> dict[str, int]:
    """Understat xG'sini indir, ESPN maçlarıyla eşleştir, match_xg'ye yaz.

    İlk çalıştırma 6 lig x ~3 sezon = ~18 istek (~1 dk); sonra yalnız içinde bulunulan sezon (6 istek, 12 saatte bir).
    fetch: (URL, Referer) -> JSON (404 için None). Verilmezse nazik istemci kullanılır (testte yerel veriler).
    Hiçbir dosya alınamazsa RuntimeError (çağıran güvenli adım bunu uyarıya çevirir).
    """
    now = datetime.now(timezone.utc)
    today = today or now.date()
    seasons = window_seasons(today)
    jobs: list[tuple[str, str, int, bool]] = []
    for slug in us.US_LEAGUES:
        for s in seasons:
            jobs.append((f"xg:{us.US_SOURCE}:{slug}:{s}", slug, s, us.season_finished(s, today)))
    metas = {j[0]: db.meta_get(con, j[0]) for j in jobs}
    todo = [j for j in jobs if _due(metas[j[0]], j[3], now, refresh_hours)]
    progress(f"xG: {len(todo)}/{len(jobs)} Understat lig-sezonu indirilecek")

    async def run(fetcher: us.Fetcher) -> list[list[us.UsMatch] | None | BaseException]:
        out: list[list[us.UsMatch] | None | BaseException] = []
        for _, slug, s, _ in todo:  # sıralı: tek eşzamanlı istek
            try:
                out.append(await us.fetch_league_season(fetcher, slug, s))
            except (RuntimeError, ValueError) as e:
                out.append(e)
        return out

    if fetch is not None:
        results = await run(fetch)
    else:
        async with us.UsClient() as client:
            results = await run(client.get_json)

    fetched_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    n_rows = n_matched = 0
    errors: list[str] = []
    for (key, slug, s, finished), res in zip(todo, results):
        if isinstance(res, BaseException):
            errors.append(f"{slug} {s}: {res}")
            continue
        if res is None:
            with db.tx(con):
                db.meta_set(con, key, {"status": "missing", "fetched_at": fetched_at, "final": finished})
            continue
        st = store_league_rows(con, slug, res, fetched_at)
        n_rows += st["rows"]
        n_matched += st["matched"]
        with db.tx(con):
            db.meta_set(con, key, {"status": "ok", "fetched_at": fetched_at, "final": finished, **st})
    total = int(con.execute("SELECT COUNT(*) FROM match_xg").fetchone()[0])
    progress(f"xG: {n_rows} Understat maçı, {n_matched} ESPN maçıyla eşleşti; tabloda {total} maç"
             + (f", {len(errors)} HATA" if errors else ""))
    for e in errors[:3]:
        progress(f"xG indirme hatası: {e}")
    if todo and len(errors) == len(todo):
        raise RuntimeError(f"Understat verisinin hiçbiri alınamadı ({len(errors)} hata); ilk hata: {errors[0]}")
    return {"due": len(todo), "rows": n_rows, "matched": n_matched, "errors": len(errors), "total": total}


def coverage(con: sqlite3.Connection, since: str) -> dict[str, dict[str, float]]:
    """Lig bazında xG kapsaması (since sonrası bitmiş maçlar)."""
    out: dict[str, dict[str, float]] = {}
    for r in con.execute(
        """SELECT m.league, COUNT(*) n, COUNT(x.match_id) k FROM matches m LEFT JOIN match_xg x ON x.match_id=m.id
           WHERE m.completed=1 AND m.date_utc >= ? AND m.league IN (%s) GROUP BY m.league""" % ",".join("?" * len(us.US_LEAGUES)),
        (since, *us.US_LEAGUES),
    ):
        out[r["league"]] = {"matches": int(r["n"]), "with_xg": int(r["k"]), "share": r["k"] / r["n"] if r["n"] else 0.0}
    return out
