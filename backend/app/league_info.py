"""Lig puan durumu (ESPN resmi tablosu) ve iki takım arasındaki karşılıklı geçmiş.

Puan durumu lig başına meta'da tutulur (`standings:<slug>`). Karşılıklı geçmiş önce ana `matches` tablosundan
(son 27 ay, tüm organizasyonlar) okunur; 5 maça tamamlanmıyorsa ESPN takım fikstüründen eski sezonlar çekilip
ayrı `h2h_history` tablosuna yazılır — model eğitimi bu tabloyu görmez.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import timedelta
from typing import Any, Callable

from . import db
from .config import H2H_LIMIT, H2H_MAX_REQUESTS, H2H_MAX_SEASONS_BACK, LEAGUE_BY_SLUG, LEAGUES
from .ingest import iso, utcnow
from .sources import espn
from .sources.http import FetchError, PoliteClient

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

_NON_COMPETITIVE = ("club.friendly",)


# ---------------------------------------------------------------- puan durumu

async def ingest_standings(con: sqlite3.Connection, progress: Progress) -> dict[str, int]:
    """Tüm ligler için puan durumu. Tablosu olmayan (eleme usulü kupa) ligler sessizce atlanır."""
    async with PoliteClient() as client:
        async def one(slug: str) -> tuple[str, dict[str, Any] | None, str | None]:
            try:
                return slug, espn.parse_standings(await espn.fetch_standings(client, slug)), None
            except FetchError as e:
                return slug, None, str(e)

        results = await asyncio.gather(*(one(lg.slug) for lg in LEAGUES))
    fetched_at = iso(utcnow())
    stats = {"ok": 0, "no_table": 0, "error": 0}
    with db.tx(con):
        for slug, table, err in results:
            if err is not None:
                stats["error"] += 1
                log.error("Puan durumu alınamadı %s: %s", slug, err)
                continue
            if table is None:
                stats["no_table"] += 1
                continue
            db.meta_set(con, f"standings:{slug}", {**table, "fetched_at": fetched_at})
            stats["ok"] += 1
    progress(f"Puan durumu: {stats}")
    return stats


def league_standings(con: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    return db.meta_get(con, f"standings:{slug}")


def all_standings(con: sqlite3.Connection) -> dict[str, Any]:
    out = []
    for lg in LEAGUES:
        t = league_standings(con, lg.slug)
        if t is None:
            continue
        out.append({"slug": lg.slug, "name": lg.name, "country": lg.country, "is_cup": lg.is_cup, **t})
    return {"leagues": out}


def match_standings(con: sqlite3.Connection, slug: str, home_id: str, away_id: str) -> dict[str, Any] | None:
    """Maçın ligindeki ilgili grup (iki takımdan en az birini içeren). Takımlar farklı gruptaysa ev sahibininki."""
    t = league_standings(con, slug)
    if t is None:
        return None
    best = None
    for g in t["groups"]:
        ids = {e["team_id"] for e in g["entries"]}
        hits = (home_id in ids) + (away_id in ids)
        if hits and (best is None or hits > best[0]):
            best = (hits, g)
    if best is None:
        return None
    return {"season": t.get("season"), "group": best[1]["name"], "entries": best[1]["entries"], "fetched_at": t.get("fetched_at")}


# ---------------------------------------------------------------- karşılıklı geçmiş (tablo: db.SCHEMA h2h_history)

def head_to_head(con: sqlite3.Connection, a_id: str, b_id: str, before: str, limit: int = H2H_LIMIT) -> list[dict[str, Any]]:
    """İki takımın `before` öncesi son `limit` resmi maçı (yeniden eskiye). Skor uzatmalar dahil nihai skordur."""
    rows: dict[str, dict[str, Any]] = {}
    for r in con.execute(
        """SELECT m.id, m.date_utc, m.league, m.home_id, m.away_id, m.home_goals, m.away_goals, m.extra_time,
                  th.name home_name, ta.name away_name
           FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
           WHERE m.completed=1 AND m.home_goals IS NOT NULL AND m.date_utc < ?
             AND ((m.home_id=? AND m.away_id=?) OR (m.home_id=? AND m.away_id=?))
           ORDER BY m.date_utc DESC LIMIT ?""",
        (before, a_id, b_id, b_id, a_id, limit),
    ):
        lg = LEAGUE_BY_SLUG.get(r["league"])
        rows[r["id"]] = {**dict(r), "extra_time": bool(r["extra_time"]),
                         "league_name": f"{lg.country} · {lg.name}" if lg else r["league"]}
    placeholders = ",".join("?" * len(_NON_COMPETITIVE))
    for r in con.execute(
        f"""SELECT * FROM h2h_history WHERE date_utc < ? AND league NOT IN ({placeholders})
            AND ((home_id=? AND away_id=?) OR (home_id=? AND away_id=?)) ORDER BY date_utc DESC LIMIT ?""",
        (before, *_NON_COMPETITIVE, a_id, b_id, b_id, a_id, limit),
    ):
        if r["id"] in rows:
            continue
        lg = LEAGUE_BY_SLUG.get(r["league"])
        rows[r["id"]] = {**dict(r), "extra_time": bool(r["extra_time"]),
                         "league_name": f"{lg.country} · {lg.name}" if lg else (r["league_name"] or r["league"])}
    return sorted(rows.values(), key=lambda x: x["date_utc"], reverse=True)[:limit]


def _earliest_season(con: sqlite3.Connection, team_id: str) -> int:
    r = con.execute("SELECT MIN(season) s FROM matches WHERE home_id=? OR away_id=?", (team_id, team_id)).fetchone()
    return int(r["s"]) if r and r["s"] is not None else utcnow().year


async def ingest_h2h(con: sqlite3.Connection, progress: Progress, days: float = 7) -> dict[str, int]:
    """Yaklaşan maçlarda karşılıklı geçmiş 5'ten azsa ev sahibinin eski sezon fikstürlerini çeker.

    Bitmiş sezonlar değişmez: her (takım, sezon) bir kez çekilir (`sched_done:` meta). İstek sayısı iş başına
    sınırlıdır; ilk çalışmalarda eksikler birkaç güncellemeye yayılır."""
    now = utcnow()
    upcoming = con.execute(
        """SELECT DISTINCT home_id, away_id, date_utc FROM matches
           WHERE state='pre' AND date_utc >= ? AND date_utc <= ?""",
        (iso(now), iso(now + timedelta(days=days))),
    ).fetchall()
    stop_season = now.year - H2H_MAX_SEASONS_BACK
    pending = [(r["home_id"], r["away_id"], r["date_utc"]) for r in upcoming]
    stats = {"pairs": len(pending), "requests": 0, "rows": 0, "errors": 0}
    next_season: dict[str, int] = {}
    async with PoliteClient() as client:
        while pending and stats["requests"] < H2H_MAX_REQUESTS:
            todo: dict[str, int] = {}
            still: list[tuple[str, str, str]] = []
            for home, away, date in pending:
                if len(head_to_head(con, home, away, date)) >= H2H_LIMIT:
                    continue
                season = next_season[home] if home in next_season else _earliest_season(con, home)
                while season >= stop_season and db.meta_get(con, f"sched_done:{home}:{season}"):
                    season -= 1
                next_season[home] = season
                if season < stop_season:
                    continue
                todo[home] = season
                still.append((home, away, date))
            if not todo:
                break
            batch = list(todo.items())[: H2H_MAX_REQUESTS - stats["requests"]]

            async def one(team: str, season: int) -> tuple[str, int, list[dict[str, Any]] | None]:
                try:
                    return team, season, espn.parse_team_schedule(await espn.fetch_team_schedule(client, team, season))
                except FetchError as e:
                    log.warning("Takım fikstürü alınamadı %s %s: %s", team, season, e)
                    return team, season, None

            results = await asyncio.gather(*(one(t, s) for t, s in batch))
            stats["requests"] += len(batch)
            fetched_at = iso(utcnow())
            with db.tx(con):
                for team, season, games in results:
                    next_season[team] = season - 1
                    if games is None:
                        stats["errors"] += 1
                        continue
                    for g in games:
                        con.execute(
                            """INSERT OR REPLACE INTO h2h_history(id, date_utc, league, league_name, home_id, away_id,
                                   home_name, away_name, home_goals, away_goals, extra_time) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (g["id"], g["date_utc"], g["league"], g["league_name"], g["home_id"], g["away_id"],
                             g["home_name"], g["away_name"], g["home_goals"], g["away_goals"], int(g["extra_time"])),
                        )
                    stats["rows"] += len(games)
                    db.meta_set(con, f"sched_done:{team}:{season}", fetched_at)
            pending = still
    progress(f"Karşılıklı geçmiş: {stats}")
    return stats
