"""Veri toplama: ESPN fikstür/sonuç + maç özetleri, iddaa bülteni ve oran arşivi."""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import db
from .config import (
    HISTORY_MONTHS, IDDAA_DETAIL_CONCURRENCY, IDDAA_DETAIL_HORIZON_H, IDDAA_DETAIL_MAX_PER_RUN, IDDAA_DETAIL_MIN_INTERVAL_S,
    IDDAA_DETAIL_NEAR_H, IDDAA_DETAIL_NEAR_REFRESH_MIN, IDDAA_DETAIL_REFRESH_H, LEAGUE_BY_SLUG, LEAGUES, RECHECK_DAYS,
    SUMMARY_MONTHS,
)
from .sources import espn, iddaa
from .sources.http import FetchError, PoliteClient

log = logging.getLogger(__name__)
SUMMARY_SCHEMA_VERSION = 1
Progress = Callable[[str], None]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(espn.norm_iso(s).replace("Z", "+00:00"))


def month_range(months_back: int, months_fwd: int) -> list[str]:
    now = utcnow()
    y, m = now.year, now.month
    out = []
    for k in range(-months_back, months_fwd + 1):
        mm = m + k
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        out.append(f"{yy:04d}{mm:02d}")
    return out


def _upsert_team(con: sqlite3.Connection, t: espn.TeamRow) -> None:
    con.execute(
        """INSERT INTO teams(id, name, short_name, abbreviation, logo, color) VALUES(?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, short_name=excluded.short_name,
           abbreviation=excluded.abbreviation, logo=COALESCE(excluded.logo, teams.logo),
           color=COALESCE(excluded.color, teams.color)""",
        (t.id, t.name, t.short_name, t.abbreviation, t.logo, t.color),
    )


def _upsert_match(con: sqlite3.Connection, m: espn.MatchRow, fetched_at: str) -> None:
    con.execute(
        """INSERT INTO matches(id, league, season, date_utc, state, completed, status_detail, home_id, away_id,
                               home_goals, away_goals, venue, scoreboard_fetched_at, neutral, extra_time)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET league=excluded.league, season=excluded.season, date_utc=excluded.date_utc,
             state=excluded.state, completed=excluded.completed, status_detail=excluded.status_detail,
             home_id=excluded.home_id, away_id=excluded.away_id, home_goals=excluded.home_goals,
             away_goals=excluded.away_goals, venue=excluded.venue, scoreboard_fetched_at=excluded.scoreboard_fetched_at,
             neutral=excluded.neutral, extra_time=MAX(matches.extra_time, excluded.extra_time)""",
        (
            m.id, m.league, m.season, m.date_utc, m.state, int(m.completed), m.status_detail, m.home.id, m.away.id,
            m.home_goals, m.away_goals, m.venue, fetched_at, int(m.neutral), int(m.extra_time),
        ),
    )


async def ingest_scoreboards(con: sqlite3.Connection, progress: Progress, months_back: int = HISTORY_MONTHS) -> dict[str, int]:
    months = month_range(months_back, 1)
    now = utcnow()
    current_tag = f"{now.year:04d}{now.month:02d}"
    tasks: list[tuple[str, str]] = []
    for lg in LEAGUES:
        for mo in months:
            done = db.meta_get(con, f"sb_done:{lg.slug}:{mo}")
            if done and mo < current_tag:
                continue
            tasks.append((lg.slug, mo))
    progress(f"Fikstür/sonuç: {len(tasks)} lig-ay sorgusu")
    counts: dict[str, int] = {}
    async with PoliteClient() as client:
        async def one(slug: str, mo: str) -> tuple[str, str, list[espn.MatchRow] | None, str | None]:
            try:
                payload = await espn.fetch_scoreboard_month(client, slug, mo)
            except FetchError as e:
                return slug, mo, None, str(e)
            return slug, mo, espn.parse_scoreboard(slug, payload), None

        results = await asyncio.gather(*(one(s, m) for s, m in tasks))
    fetched_at = iso(utcnow())
    errors = 0
    with db.tx(con):
        for slug, mo, rows, err in results:
            if rows is None:
                errors += 1
                log.error("Fikstür alınamadı %s %s: %s", slug, mo, err)
                continue
            for r in rows:
                _upsert_team(con, r.home)
                _upsert_team(con, r.away)
                _upsert_match(con, r, fetched_at)
            counts[slug] = counts.get(slug, 0) + len(rows)
            # Ay tamamen geçmişte ve tüm maçlar sonuçlanmış/ertelenmişse bir daha çekme
            month_end_passed = mo < current_tag and (now.day > RECHECK_DAYS or mo < month_range(1, 0)[0])
            if month_end_passed and all(r.state == "post" for r in rows):
                db.meta_set(con, f"sb_done:{slug}:{mo}", fetched_at)
    progress(f"Fikstür tamam: {sum(counts.values())} maç satırı, {errors} hatalı sorgu")
    return counts


def _store_summary(con: sqlite3.Connection, league: str, match_id: str, payload: dict, fetched_at: str) -> str:
    parsed = espn.parse_summary(match_id, payload)
    con.execute("DELETE FROM team_match_stats WHERE match_id=?", (match_id,))
    con.execute("DELETE FROM player_match WHERE match_id=?", (match_id,))
    con.execute("DELETE FROM goal_events WHERE match_id=?", (match_id,))
    for t in parsed.team_stats:
        cc = parsed.cards.get(t.team_id)
        con.execute(
            """INSERT INTO team_match_stats(match_id, team_id, is_home, shots, shots_on_target, corners, possession, yellow,
                   red, fouls, card_points, card_points_ht, red_cards_90) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (match_id, t.team_id, int(t.is_home), t.shots, t.shots_on_target, t.corners, t.possession, t.yellow, t.red, t.fouls,
             cc.points if cc else None, cc.points_ht if cc else None, cc.reds if cc else None),
        )
    for p in parsed.players:
        con.execute(
            "INSERT INTO players(id, name, position) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, position=COALESCE(excluded.position, players.position)",
            (p.player_id, p.name, p.position),
        )
        con.execute(
            "INSERT OR REPLACE INTO player_match VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                match_id, p.team_id, p.player_id, int(p.in_squad), int(p.starter), p.min_on, p.min_off, p.minutes,
                p.minutes_quality, p.position, p.pos_group, p.shots, p.shots_on_target, p.goals, p.assists,
                p.own_goals, p.yellow, p.red,
            ),
        )
    for g in parsed.goals:
        con.execute(
            "INSERT INTO goal_events VALUES(?,?,?,?,?,?,?,?)",
            (match_id, g.seq, g.team_id, g.player_id, g.minute, g.period, int(g.own_goal), int(g.penalty)),
        )
    if parsed.state == "post":
        status = "ok" if parsed.has_player_stats and parsed.team_stats else "missing_players"
    else:
        status = "pre_lineup" if parsed.lineup_confirmed else "pre"
    con.execute(
        """UPDATE matches SET summary_fetched_at=?, summary_status=?, home_ht=?, away_ht=?, lineup_confirmed=?,
                              ft90_home=?, ft90_away=?, extra_time=MAX(extra_time, ?) WHERE id=?""",
        (fetched_at, status, parsed.home_ht, parsed.away_ht, int(parsed.lineup_confirmed and parsed.state == "pre"),
         parsed.home_ft90, parsed.away_ft90, int(parsed.extra_time), match_id),
    )
    blob = zlib.compress(json.dumps(espn.slim_summary(payload), ensure_ascii=False).encode("utf-8"), 6)
    con.execute(
        "INSERT OR REPLACE INTO raw_summaries VALUES(?,?,?,?)", (match_id, fetched_at, SUMMARY_SCHEMA_VERSION, blob)
    )
    return status


def summaries_todo(con: sqlite3.Connection, months: int = SUMMARY_MONTHS, limit: int | None = None) -> list[sqlite3.Row]:
    now = utcnow()
    since = iso(now - timedelta(days=30.5 * months))
    recheck_since = iso(now - timedelta(days=RECHECK_DAYS))
    soon = iso(now + timedelta(hours=36))
    q = """
      SELECT id, league, date_utc FROM matches
      WHERE (
        completed=1 AND date_utc >= ? AND (
          summary_fetched_at IS NULL
          OR summary_status NOT IN ('ok','missing_players')
          OR (date_utc >= ? AND summary_fetched_at < strftime('%Y-%m-%dT%H:%M:%SZ', date_utc, '+1 day'))
        )
      ) OR (state='pre' AND date_utc <= ? AND date_utc >= ?)
      ORDER BY date_utc DESC
    """
    rows = con.execute(q, (since, recheck_since, soon, iso(now - timedelta(hours=3)))).fetchall()
    # Lig bazında detay penceresi (genişletilmiş liglerde daha kısa)
    out = []
    for r in rows:
        lg = LEAGUE_BY_SLUG.get(r["league"])
        window = lg.detail_months if lg else months
        if r["date_utc"] >= iso(now - timedelta(days=30.5 * window)) or r["date_utc"] >= iso(now - timedelta(hours=3)):
            out.append(r)
    return out[:limit] if limit else out


async def ingest_summaries(con: sqlite3.Connection, progress: Progress, limit: int | None = None, batch: int = 60,
                           pre_only: bool = False) -> dict[str, int]:
    todo = summaries_todo(con, limit=limit)
    if pre_only:  # saatlik kadro işi: yalnız başlamamış maçlar (resmi ilk 11 açıklandıysa yakalanır)
        todo = [r for r in todo if r["date_utc"] >= iso(utcnow())]
    progress(f"Maç özetleri: {len(todo)} maç kuyrukta")
    stats = {"ok": 0, "missing_players": 0, "pre": 0, "pre_lineup": 0, "error": 0}
    async with PoliteClient() as client:
        for i in range(0, len(todo), batch):
            chunk = todo[i : i + batch]

            async def one(row: sqlite3.Row) -> tuple[sqlite3.Row, dict | None, str | None]:
                try:
                    return row, await espn.fetch_summary(client, row["league"], row["id"]), None
                except FetchError as e:
                    return row, None, str(e)

            results = await asyncio.gather(*(one(r) for r in chunk))
            fetched_at = iso(utcnow())
            with db.tx(con):
                for row, payload, err in results:
                    if payload is None:
                        stats["error"] += 1
                        con.execute(
                            "UPDATE matches SET summary_status='error', summary_fetched_at=? WHERE id=?", (fetched_at, row["id"])
                        )
                        log.error("Özet alınamadı %s: %s", row["id"], err)
                        continue
                    st = _store_summary(con, row["league"], row["id"], payload, fetched_at)
                    stats[st] = stats.get(st, 0) + 1
            progress(f"Maç özetleri: {min(i + batch, len(todo))}/{len(todo)} ({client.requests} istek)")
    return stats


def _odds_signature(rows: list[tuple[str, int, float]]) -> dict[tuple[str, int], float]:
    return {(k, n): o for k, n, o in rows}


def is_detail_key(market_key: str) -> bool:
    """market_key "t:st:sov" maç detayından çekilen bir aileye (korner, kart) mi ait?"""
    parts = market_key.split(":")
    try:
        return (int(parts[0]), int(parts[1])) in iddaa.DETAIL_MARKETS
    except (ValueError, IndexError):
        return False


def _write_markets(con: sqlite3.Connection, event_id: int, markets: list[iddaa.Market], fetched_at: str,
                   prev: dict[tuple[str, int], float]) -> int:
    """Pazarları odds_current'a yazar; önceki orandan farklı olanları odds_history'ye arşivler (değişen sayısı)."""
    changed = 0
    for m in markets:
        for o in m.outcomes:
            con.execute(
                "INSERT OR REPLACE INTO odds_current VALUES(?,?,?,?,?,?,?)",
                (event_id, m.market_key, o.no, o.name, o.odd, m.mbs, fetched_at),
            )
            if prev.get((m.market_key, o.no)) != o.odd:
                con.execute("INSERT INTO odds_history VALUES(?,?,?,?,?)", (event_id, m.market_key, o.no, o.odd, fetched_at))
                changed += 1
    return changed


async def ingest_iddaa(con: sqlite3.Connection, progress: Progress) -> dict[str, int]:
    async with PoliteClient(concurrency=1, min_interval=1.0) as client:
        comps_payload = await iddaa.fetch_competitions(client)
        events_payload = await iddaa.fetch_events(client)
    comps = iddaa.parse_competitions(comps_payload)
    events = iddaa.parse_events(events_payload)
    fetched_at = iso(utcnow())
    changed = 0
    with db.tx(con):
        for c in comps:
            con.execute(
                "INSERT OR REPLACE INTO iddaa_competitions(id, name, country_code, short_name, icon) VALUES(?,?,?,?,?)",
                (c["id"], c["name"], c["country_code"], c["short_name"], c["icon"]),
            )
        if not events:
            raise ValueError("iddaa bülteni boş döndü; mevcut oranlar korunuyor")
        # Bu bültende olmayan etkinlikler artık satışta değil: pasifleştir ve güncel oranlarını kaldır
        con.execute("UPDATE iddaa_events SET active=0")
        for e in events:
            con.execute(
                """INSERT INTO iddaa_events(id, competition_id, home_name, away_name, kickoff_utc, mbs, is_live, last_seen_at, active)
                   VALUES(?,?,?,?,?,?,?,?,1)
                   ON CONFLICT(id) DO UPDATE SET competition_id=excluded.competition_id, home_name=excluded.home_name,
                     away_name=excluded.away_name, kickoff_utc=excluded.kickoff_utc, mbs=excluded.mbs,
                     is_live=excluded.is_live, last_seen_at=excluded.last_seen_at, active=1""",
                (e.id, e.competition_id, e.home_name, e.away_name, e.kickoff_utc, e.mbs, int(e.is_live), fetched_at),
            )
            if e.is_live:
                # canlı oranlar maç öncesi modelle karşılaştırılamaz; eski maç öncesi oranlar da geçersiz
                con.execute("DELETE FROM odds_current WHERE event_id=?", (e.id,))
                continue
            cur_rows = con.execute("SELECT market_key, outcome_no, odd FROM odds_current WHERE event_id=?", (e.id,)).fetchall()
            prev = _odds_signature([(r["market_key"], r["outcome_no"], r["odd"]) for r in cur_rows])
            # Toplu bültenin kapsadığı pazarlar yenilenir; maç detayından gelen (korner/kart) oranlar detay çekimine kalır
            for mkey in {r["market_key"] for r in cur_rows if not is_detail_key(r["market_key"])}:
                con.execute("DELETE FROM odds_current WHERE event_id=? AND market_key=?", (e.id, mkey))
            changed += _write_markets(con, e.id, e.markets, fetched_at, prev)
        con.execute("DELETE FROM odds_current WHERE event_id IN (SELECT id FROM iddaa_events WHERE active=0)")
        db.meta_set(con, "iddaa_last_fetch", fetched_at)
    progress(f"iddaa bülteni: {len(events)} futbol maçı, {changed} oran değişikliği arşivlendi")
    return {"events": len(events), "odds_changed": changed}


def details_due(con: sqlite3.Connection, now: datetime | None = None) -> list[sqlite3.Row]:
    """Detayı (korner/kart pazarları) çekilecek etkinlikler: ESPN maçıyla eşleşmiş (modelin kapsadığı lig), satışta ve
    IDDAA_DETAIL_HORIZON_H saat içinde başlayacak; son çekimden IDDAA_DETAIL_REFRESH_H saat geçmiş ya da başlamaya
    IDDAA_DETAIL_NEAR_H saatten az kalmış ve IDDAA_DETAIL_NEAR_REFRESH_MIN dakika geçmiş. En yakın maç önce."""
    now = now or utcnow()
    rows = con.execute(
        """SELECT e.id, e.kickoff_utc, e.detail_fetched_at FROM iddaa_events e JOIN matches m ON m.id = e.espn_match_id
           WHERE e.active=1 AND e.is_live=0 AND e.kickoff_utc > ? AND e.kickoff_utc <= ? ORDER BY e.kickoff_utc, e.id""",
        (iso(now), iso(now + timedelta(hours=IDDAA_DETAIL_HORIZON_H))),
    ).fetchall()
    out = []
    for r in rows:
        if r["detail_fetched_at"] is None:
            out.append(r)
            continue
        age = now - parse_iso(r["detail_fetched_at"])
        to_kick = parse_iso(r["kickoff_utc"]) - now
        if age >= timedelta(hours=IDDAA_DETAIL_REFRESH_H) or (
            to_kick <= timedelta(hours=IDDAA_DETAIL_NEAR_H) and age >= timedelta(minutes=IDDAA_DETAIL_NEAR_REFRESH_MIN)
        ):
            out.append(r)
    return out[:IDDAA_DETAIL_MAX_PER_RUN]


async def ingest_iddaa_details(con: sqlite3.Connection, progress: Progress, dump_dir: Path | None = None) -> dict[str, int]:
    """Maç detayından korner/kart pazarları (toplu bültende yok). Etkinlik başına detay ailelerinin oranları tamamen
    yenilenir (kalkan çizgiler silinir), değişen oranlar odds_history'ye arşivlenir. dump_dir verilirse ham yanıtlar
    oraya yazılır (doğrulama çalıştırmaları için). Hiçbir istek başarılı olmazsa hata fırlatır (çağıran uyarı yazar)."""
    todo = details_due(con)
    if not todo:
        progress("iddaa maç detayı: çekilecek maç yok")
        return {"due": 0, "fetched": 0, "errors": 0, "markets": 0, "odds_changed": 0, "requests": 0}
    t0 = time.monotonic()
    async with PoliteClient(concurrency=IDDAA_DETAIL_CONCURRENCY, min_interval=IDDAA_DETAIL_MIN_INTERVAL_S) as client:
        async def one(eid: int) -> tuple[int, dict | None, str | None]:
            try:
                return eid, await iddaa.fetch_event_detail(client, eid), None
            except FetchError as e:
                return eid, None, str(e)

        results = await asyncio.gather(*(one(int(r["id"])) for r in todo))
        n_requests = client.requests
    elapsed = time.monotonic() - t0
    fetched_at = iso(utcnow())
    stats = {"due": len(todo), "fetched": 0, "errors": 0, "markets": 0, "odds_changed": 0, "requests": n_requests}
    with db.tx(con):
        for eid, payload, err in results:
            if payload is None:
                stats["errors"] += 1
                log.error("iddaa maç detayı alınamadı %s: %s", eid, err)
                continue
            if dump_dir is not None:
                dump_dir.mkdir(parents=True, exist_ok=True)
                (dump_dir / f"event_{eid}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            try:
                ev = iddaa.parse_event_detail(payload, eid)
            except (ValueError, KeyError, TypeError) as e:
                stats["errors"] += 1
                log.error("iddaa maç detayı çözülemedi %s: %s", eid, e)
                continue
            cur_rows = con.execute("SELECT market_key, outcome_no, odd FROM odds_current WHERE event_id=?", (eid,)).fetchall()
            prev = _odds_signature([(r["market_key"], r["outcome_no"], r["odd"]) for r in cur_rows if is_detail_key(r["market_key"])])
            for mkey in {k for k, _ in prev}:
                con.execute("DELETE FROM odds_current WHERE event_id=? AND market_key=?", (eid, mkey))
            con.execute("UPDATE iddaa_events SET detail_fetched_at=? WHERE id=?", (fetched_at, eid))
            stats["fetched"] += 1
            if ev is None or ev.is_live:
                continue  # etkinlik detayı yok / başlamış: maç öncesi korner/kart oranı tutulmaz
            stats["markets"] += len(ev.markets)
            stats["odds_changed"] += _write_markets(con, eid, ev.markets, fetched_at, prev)
    progress(f"iddaa maç detayı: {stats['fetched']}/{stats['due']} maç, {stats['markets']} korner/kart pazarı, "
             f"{stats['odds_changed']} oran değişikliği, {n_requests} istek, {elapsed:.1f} sn, {stats['errors']} hata")
    if stats["fetched"] == 0:
        raise RuntimeError(f"iddaa maç detaylarının hiçbiri alınamadı ({stats['errors']} hata)")
    return stats


def repair_missing_stats(con: sqlite3.Connection) -> int:
    """Eski kayıtlarda 'tüm değerler 0' biçimindeki eksik istatistikleri eksik olarak işaretler (idempotent)."""
    bad = [
        r["match_id"]
        for r in con.execute(
            """SELECT match_id FROM team_match_stats GROUP BY match_id
               HAVING SUM(COALESCE(possession,0))=0 AND SUM(COALESCE(shots,0))=0 AND SUM(COALESCE(fouls,0))=0"""
        )
    ]
    if not bad:
        return 0
    with db.tx(con):
        for mid in bad:
            con.execute("DELETE FROM team_match_stats WHERE match_id=?", (mid,))
            con.execute("UPDATE player_match SET shots=NULL, shots_on_target=NULL WHERE match_id=?", (mid,))
            con.execute("UPDATE matches SET summary_status='missing_players' WHERE id=? AND summary_status='ok'", (mid,))
    return len(bad)


def backfill_card_points(con: sqlite3.Connection) -> int:
    """Saklı ham özetlerden iddaa kart sayımını (espn.card_counts) eski kayıtlara yazar (idempotent: yalnız boş olanlar).
    Olay listesi olmayan özetlerde değer boş kalır (kart yok sayılmaz)."""
    rows = con.execute(
        """SELECT r.match_id, r.payload FROM raw_summaries r JOIN matches m ON m.id=r.match_id
           WHERE m.completed=1 AND EXISTS (SELECT 1 FROM team_match_stats s WHERE s.match_id=r.match_id
                                          AND s.card_points IS NULL)"""
    ).fetchall()
    n = 0
    with db.tx(con):
        for r in rows:
            try:
                payload = json.loads(zlib.decompress(r["payload"]).decode("utf-8"))
            except (zlib.error, ValueError):
                continue
            tids = [x["team_id"] for x in con.execute("SELECT team_id FROM team_match_stats WHERE match_id=?", (r["match_id"],))]
            cards = espn.card_counts(payload, tids)
            for tid, cc in cards.items():
                con.execute(
                    "UPDATE team_match_stats SET card_points=?, card_points_ht=?, red_cards_90=? WHERE match_id=? AND team_id=?",
                    (cc.points, cc.points_ht, cc.reds, r["match_id"], tid),
                )
            n += int(bool(cards))
    return n


def backfill_periods(con: sqlite3.Connection) -> int:
    """Saklı ham özetlerden devre skorlarını (İY, 90 dk) ve uzatma bayrağını yeniden türetir (idempotent)."""
    rows = con.execute(
        """SELECT r.match_id, r.payload FROM raw_summaries r JOIN matches m ON m.id=r.match_id
           WHERE m.completed=1 AND (m.ft90_home IS NULL OR m.extra_time=1)"""
    ).fetchall()
    n = 0
    with db.tx(con):
        for r in rows:
            try:
                payload = json.loads(zlib.decompress(r["payload"]).decode("utf-8"))
            except (zlib.error, ValueError):
                continue
            parsed = espn.parse_summary(r["match_id"], payload)
            con.execute(
                "UPDATE matches SET home_ht=?, away_ht=?, ft90_home=?, ft90_away=?, extra_time=MAX(extra_time, ?) WHERE id=?",
                (parsed.home_ht, parsed.away_ht, parsed.home_ft90, parsed.away_ft90, int(parsed.extra_time), r["match_id"]),
            )
            n += 1
        # Skorbord durum metninden uzatma bayrağı (özeti olmayan maçlar için)
        con.execute("UPDATE matches SET extra_time=1 WHERE status_detail IN ('AET','FT-Pens') AND extra_time=0")
        # Uzatmasız ve özetsiz maçlarda 90 dk skoru = nihai skor
        con.execute(
            """UPDATE matches SET ft90_home=home_goals, ft90_away=away_goals
               WHERE completed=1 AND extra_time=0 AND ft90_home IS NULL AND home_goals IS NOT NULL"""
        )
    return n
