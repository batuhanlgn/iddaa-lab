"""ESPN (anahtarsız, ücretsiz) futbol verisi: fikstür/sonuç + maç özeti (oyuncu ve takım istatistikleri)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import ESPN_BASE
from .http import PoliteClient

_CLOCK_RE = re.compile(r"^(\d+)'(?:\+(\d+)')?")


def parse_clock_minute(display: str | None) -> int | None:
    """"45'+7'" -> 45, "68'" -> 68. Uzatma dakikası normal süreye eklenmez (dakika ekseni 0-90)."""
    if not display:
        return None
    m = _CLOCK_RE.match(display.strip())
    if not m:
        return None
    return min(int(m.group(1)), 120)


def norm_iso(s: str) -> str:
    """ESPN "2025-09-13T11:30Z" -> "2025-09-13T11:30:00Z" (tüm tarihler tek biçimde saklanır)."""
    s = s.strip()
    if len(s) == 17 and s.endswith("Z"):
        return s[:16] + ":00Z"
    return s


def pos_group(abbr: str | None) -> str:
    """ESPN pozisyon kısaltması -> G/D/M/F. "SUB" (yedekten giren) gerçek pozisyon değildir: "M" döner ve
    çağıran taraf oyuncunun SUB dışındaki maçlarından kanonik pozisyon türetmelidir."""
    a = (abbr or "").upper()
    if a in ("", "SUB"):
        return "M"
    if a in ("G", "GK"):
        return "G"
    base = a.split("-")[0]
    if base in ("CD", "CB", "LB", "RB", "D", "SW", "LWB", "RWB", "WB", "LCB", "RCB"):
        return "D"
    if base in ("F", "CF", "ST", "LF", "RF", "LW", "RW", "SS", "RCF", "LCF"):
        return "F"
    return "M"  # DM, CM, AM, LM, RM, M, RCM, LCM ...


def _int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@dataclass
class TeamRow:
    id: str
    name: str
    short_name: str | None
    abbreviation: str | None
    logo: str | None
    color: str | None


@dataclass
class MatchRow:
    id: str
    league: str
    season: int | None
    date_utc: str
    state: str
    completed: bool
    status_detail: str | None
    home: TeamRow
    away: TeamRow
    home_goals: int | None
    away_goals: int | None
    venue: str | None
    neutral: bool = False
    extra_time: bool = False  # uzatma/penaltı: skor 90 dakika skoru DEĞİL


@dataclass
class PlayerRow:
    player_id: str
    name: str
    team_id: str
    starter: bool
    in_squad: bool
    min_on: int | None
    min_off: int | None
    minutes: int
    minutes_quality: str
    position: str | None
    pos_group: str
    shots: int | None
    shots_on_target: int | None
    goals: int | None
    assists: int | None
    own_goals: int | None
    yellow: int | None
    red: int | None


@dataclass
class TeamStatsRow:
    team_id: str
    is_home: bool
    shots: int | None
    shots_on_target: int | None
    corners: int | None
    possession: float | None
    yellow: int | None
    red: int | None
    fouls: int | None


@dataclass
class CardCount:
    """iddaa kart sayımı (Toplam Kart Sayısı kuralı): sarı 1, doğrudan kırmızı ya da ikinci sarıdan kırmızı 2.
    İkinci sarıyla atılan oyuncu: ilk sarı 1 + kırmızı 2 = 3. Yalnız 90 dakika (1. ve 2. devre)."""
    points: int
    points_ht: int
    reds: int


@dataclass
class GoalRow:
    seq: int
    team_id: str
    player_id: str | None
    minute: int | None
    period: int | None
    own_goal: bool
    penalty: bool


@dataclass
class SummaryParse:
    match_id: str
    state: str
    completed: bool
    team_stats: list[TeamStatsRow] = field(default_factory=list)
    players: list[PlayerRow] = field(default_factory=list)
    goals: list[GoalRow] = field(default_factory=list)
    home_ht: int | None = None
    away_ht: int | None = None
    home_ft90: int | None = None
    away_ft90: int | None = None
    extra_time: bool = False
    lineup_confirmed: bool = False
    has_player_stats: bool = False
    cards: dict[str, CardCount] = field(default_factory=dict)   # takım id -> iddaa kart sayımı (yoksa boş)


def _team_row(t: dict[str, Any]) -> TeamRow:
    logo = t.get("logo")
    if not logo and t.get("logos"):
        logo = t["logos"][0].get("href")
    return TeamRow(
        id=str(t["id"]),
        name=t.get("displayName") or t.get("name") or str(t["id"]),
        short_name=t.get("shortDisplayName"),
        abbreviation=t.get("abbreviation"),
        logo=logo,
        color=t.get("color"),
    )


def is_extra_time(status_type: dict[str, Any]) -> bool:
    name = str(status_type.get("name") or "").upper()
    detail = str(status_type.get("detail") or status_type.get("shortDetail") or "").upper()
    return "AET" in name or "PEN" in name or detail in ("AET", "FT-PENS", "PENS") or "EXTRA" in name


def parse_scoreboard(league: str, payload: dict[str, Any]) -> list[MatchRow]:
    out: list[MatchRow] = []
    for ev in payload.get("events", []):
        comps = ev.get("competitions") or []
        if not comps:
            continue
        comp = comps[0]
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in sides or "away" not in sides:
            continue
        st = ev.get("status", {}).get("type", {})
        state = st.get("state", "pre")
        completed = bool(st.get("completed"))
        h, a = sides["home"], sides["away"]
        hg = _int(h.get("score")) if state != "pre" else None
        ag = _int(a.get("score")) if state != "pre" else None
        # Ertelenmiş/iptal maçlar "post" olup completed=False olabilir; skorları güvenilmez.
        if state == "post" and not completed:
            hg = ag = None
        out.append(
            MatchRow(
                id=str(ev["id"]),
                league=league,
                season=_int((ev.get("season") or {}).get("year")),
                date_utc=norm_iso(ev["date"]),
                state=state,
                completed=completed,
                status_detail=st.get("detail") or st.get("description"),
                home=_team_row(h["team"]),
                away=_team_row(a["team"]),
                home_goals=hg,
                away_goals=ag,
                venue=(comp.get("venue") or {}).get("fullName"),
                neutral=bool(comp.get("neutralSite")),
                extra_time=is_extra_time(st),
            )
        )
    return out


_CARD_TYPES = ("yellow-card", "red-card")


def card_counts(payload: dict[str, Any], team_ids: list[str]) -> dict[str, CardCount]:
    """keyEvents kart olaylarından takım başına iddaa kart puanı.

    ESPN boxscore'daki yellowCards, ikinci sarıyla atılan oyuncunun İLK sarısını içermiyor (21.786 takım-maç
    satırının %99,6'sında yellow = sarı olay - ikinci sarı kırmızısı; redCards olay sayısıyla %99,9 aynı). Bu yüzden
    sayım boxscore'dan değil olaylardan yapılır. Oyuncu başına sarı en fazla 1 (aynı oyuncuya iki sarı olayı ve kırmızı
    yoksa mükerrer kayıttır), kırmızı en fazla 1. Uzatma devreleri (3+) sayılmaz. Olay listesi hiç yoksa boş döner
    (kart yok sayılmaz); takım listesinde olup kart olayı olmayan takım 0 alır.
    """
    events = payload.get("keyEvents")
    if not events:
        return {}
    per: dict[tuple[str, str], list[int]] = {}   # (takım, oyuncu) -> [sarı, kırmızı, ilk yarı sarı, ilk yarı kırmızı]
    for i, k in enumerate(events):
        if (k.get("type") or {}).get("type") not in _CARD_TYPES:
            continue
        period = _int((k.get("period") or {}).get("number"))
        if period not in (1, 2):
            continue
        tid = str((k.get("team") or {}).get("id") or "")
        parts = k.get("participants") or []
        aid = str(((parts[0] if parts else {}).get("athlete") or {}).get("id") or f"olay{i}")
        e = per.setdefault((tid, aid), [0, 0, 0, 0])
        red = k["type"]["type"] == "red-card"
        e[1 if red else 0] += 1
        if period == 1:
            e[3 if red else 2] += 1
    out = {t: CardCount(0, 0, 0) for t in team_ids}
    for (tid, _), (y, r, yh, rh) in per.items():
        if tid not in out:
            continue
        c = out[tid]
        c.points += min(y, 1) + 2 * min(r, 1)
        c.points_ht += min(yh, 1) + 2 * min(rh, 1)
        c.reds += min(r, 1)
    return out


_TEAM_STAT_MAP = {
    "totalShots": "shots",
    "shotsOnTarget": "shots_on_target",
    "wonCorners": "corners",
    "possessionPct": "possession",
    "yellowCards": "yellow",
    "redCards": "red",
    "foulsCommitted": "fouls",
}


def parse_summary(match_id: str, payload: dict[str, Any]) -> SummaryParse:
    header_comp = ((payload.get("header") or {}).get("competitions") or [{}])[0]
    st = (header_comp.get("status") or {}).get("type") or {}
    res = SummaryParse(match_id=match_id, state=st.get("state", "pre"), completed=bool(st.get("completed")))

    home_id: str | None = None
    for c in header_comp.get("competitors", []):
        if c.get("homeAway") == "home":
            home_id = str(c["id"])

    for t in (payload.get("boxscore") or {}).get("teams", []):
        tid = str(t["team"]["id"])
        vals: dict[str, Any] = {}
        for s in t.get("statistics", []):
            key = _TEAM_STAT_MAP.get(s.get("name"))
            if key:
                vals[key] = s.get("displayValue")
        if not vals:
            continue
        res.team_stats.append(
            TeamStatsRow(
                team_id=tid,
                is_home=tid == home_id,
                shots=_int(vals.get("shots")),
                shots_on_target=_int(vals.get("shots_on_target")),
                corners=_int(vals.get("corners")),
                possession=_float(vals.get("possession")),
                yellow=_int(vals.get("yellow")),
                red=_int(vals.get("red")),
                fouls=_int(vals.get("fouls")),
            )
        )

    # ESPN, istatistiği olmayan maçlarda tüm takım değerlerini 0 döndürebiliyor: bunlar eksik veridir, sıfır değil.
    stats_valid = any((t.possession or 0) > 0 or (t.shots or 0) > 0 or (t.fouls or 0) > 0 for t in res.team_stats)
    if not stats_valid:
        res.team_stats = []
    if res.state == "post":
        res.cards = card_counts(payload, [t.team_id for t in res.team_stats])

    finished = res.state == "post"
    for r in payload.get("rosters") or []:
        tid = str(r["team"]["id"])
        roster = r.get("roster") or []
        if roster:
            res.lineup_confirmed = res.lineup_confirmed or any(p.get("starter") for p in roster)
        for p in roster:
            ath = p.get("athlete") or {}
            if not ath.get("id"):
                continue
            stats = {s["name"]: s.get("value") for s in p.get("stats", []) if "name" in s}
            if not stats_valid:
                stats = {k: v for k, v in stats.items() if k in ("totalGoals", "goalAssists", "ownGoals", "yellowCards", "redCards")}
            elif stats:
                res.has_player_stats = True
            starter = bool(p.get("starter"))
            plays = p.get("plays") or []
            sub_in_min: int | None = None
            sub_out_min: int | None = None
            red_min: int | None = None
            for pl in plays:
                mnt = parse_clock_minute((pl.get("clock") or {}).get("displayValue"))
                if pl.get("substitution"):
                    if p.get("subbedIn") and sub_in_min is None and not starter:
                        sub_in_min = mnt
                    elif p.get("subbedOut"):
                        sub_out_min = mnt
                if pl.get("redCard"):
                    red_min = mnt
            quality = "exact"
            if starter:
                min_on: int | None = 0
            elif p.get("subbedIn"):
                min_on = sub_in_min
                if min_on is None:
                    quality = "inferred"
                    min_on = 70  # değişiklik dakikası yoksa yedeklerin medyan giriş dakikası
            else:
                min_on = None
            if min_on is None:
                min_off: int | None = None
                minutes = 0
            else:
                end = 90
                if p.get("subbedOut"):
                    if sub_out_min is None:
                        quality = "inferred"
                        sub_out_min = 70
                    end = sub_out_min
                if red_min is not None:
                    end = min(end, red_min)
                min_off = max(end, min_on)
                minutes = min_off - min_on
            if not finished:
                # Maç öncesi kadro: dakika henüz yok
                minutes, min_off = 0, None
            pos = (p.get("position") or {}).get("abbreviation")
            res.players.append(
                PlayerRow(
                    player_id=str(ath["id"]),
                    name=ath.get("displayName") or str(ath["id"]),
                    team_id=tid,
                    starter=starter,
                    in_squad=True,
                    min_on=min_on,
                    min_off=min_off,
                    minutes=minutes,
                    minutes_quality=quality,
                    position=pos,
                    pos_group=pos_group(pos),
                    shots=_int(stats.get("totalShots")),
                    shots_on_target=_int(stats.get("shotsOnTarget")),
                    goals=_int(stats.get("totalGoals")),
                    assists=_int(stats.get("goalAssists")),
                    own_goals=_int(stats.get("ownGoals")),
                    yellow=_int(stats.get("yellowCards")),
                    red=_int(stats.get("redCards")),
                )
            )

    away_id: str | None = None
    final: dict[str, int | None] = {"home": None, "away": None}
    periods: dict[str, list[int]] = {}
    for c in header_comp.get("competitors", []):
        side = c.get("homeAway")
        if side == "away":
            away_id = str(c["id"])
        if side in ("home", "away"):
            final[side] = _int(c.get("score"))
            ls = c.get("linescores") or []
            vals = [_int(x.get("displayValue", x.get("value"))) for x in ls]
            if vals and all(v is not None for v in vals):
                periods[side] = [int(v) for v in vals if v is not None]
    res.extra_time = is_extra_time(st)

    seq = 0
    ev_ht = {"home": 0, "away": 0}
    ev_90 = {"home": 0, "away": 0}
    ev_total = {"home": 0, "away": 0}
    for k in payload.get("keyEvents") or []:
        if not k.get("scoringPlay") or k.get("shootout"):
            continue
        text = ((k.get("type") or {}).get("text") or "").lower()
        own = "own goal" in text
        pen = "penalty" in text
        tid = str((k.get("team") or {}).get("id") or "")
        parts = k.get("participants") or []
        pid = str(parts[0]["athlete"]["id"]) if parts and parts[0].get("athlete", {}).get("id") else None
        period = _int((k.get("period") or {}).get("number"))
        res.goals.append(
            GoalRow(
                seq=seq,
                team_id=tid,
                player_id=pid,
                minute=parse_clock_minute((k.get("clock") or {}).get("displayValue")),
                period=period,
                own_goal=own,
                penalty=pen,
            )
        )
        seq += 1
        side = "home" if tid == home_id else "away" if tid == away_id else None
        if side:
            ev_total[side] += 1
            if period == 1:
                ev_ht[side] += 1
            if period in (1, 2):
                ev_90[side] += 1
    if finished and home_id and away_id:
        # 1) Doğrulanmış devre skorları (header linescores) öncelikli
        if len(periods.get("home", [])) >= 2 and len(periods.get("away", [])) >= 2:
            res.home_ht, res.away_ht = periods["home"][0], periods["away"][0]
            res.home_ft90 = periods["home"][0] + periods["home"][1]
            res.away_ft90 = periods["away"][0] + periods["away"][1]
        # 2) Gol olayları yalnızca nihai skorla birebir tutarlıysa (eksik olay listesi 0-0 sayılmaz)
        elif final["home"] is not None and ev_total["home"] == final["home"] and ev_total["away"] == final["away"]:
            res.home_ht, res.away_ht = ev_ht["home"], ev_ht["away"]
            res.home_ft90, res.away_ft90 = ev_90["home"], ev_90["away"]
        if not res.extra_time and res.home_ft90 is None and final["home"] is not None:
            res.home_ft90, res.away_ft90 = final["home"], final["away"]
    return res


async def fetch_scoreboard_month(client: PoliteClient, league: str, yyyymm: str) -> dict[str, Any]:
    return await client.get_json(f"{ESPN_BASE}/{league}/scoreboard", {"dates": yyyymm, "limit": "500"})


async def fetch_scoreboard_day(client: PoliteClient, league: str, yyyymmdd: str) -> dict[str, Any]:
    return await client.get_json(f"{ESPN_BASE}/{league}/scoreboard", {"dates": yyyymmdd})


async def fetch_summary(client: PoliteClient, league: str, event_id: str) -> dict[str, Any]:
    return await client.get_json(f"{ESPN_BASE}/{league}/summary", {"event": event_id})


def slim_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Ham yanıtın modele/denetime gereken kısmı (boyutu ~10 kat küçültür)."""
    keep = ("header", "boxscore", "rosters", "keyEvents", "gameInfo")
    return {k: payload.get(k) for k in keep if k in payload}


ESPN_STANDINGS_BASE = ESPN_BASE.replace("/apis/site/v2/", "/apis/v2/")
_STANDING_STATS = {
    "gamesPlayed": "played", "wins": "won", "ties": "drawn", "losses": "lost", "pointsFor": "gf",
    "pointsAgainst": "ga", "pointDifferential": "gd", "points": "points", "deductions": "deductions", "rank": "rank",
}


async def fetch_standings(client: PoliteClient, league: str) -> dict[str, Any]:
    return await client.get_json(f"{ESPN_STANDINGS_BASE}/{league}/standings")


def parse_standings(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Puan durumu: grup başına (MLS konferansı, Arjantin grubu, ŞL lig aşaması...) sıralı satırlar.
    Puan silme, sıralama ve not (Avrupa/küme düşme bölgesi) ESPN'in resmi tablosundan gelir; yeniden hesaplanmaz."""
    groups = []
    for ch in payload.get("children") or []:
        entries = []
        for e in (ch.get("standings") or {}).get("entries") or []:
            t = e.get("team") or {}
            if not t.get("id"):
                continue
            st = {_STANDING_STATS[s["name"]]: _int(s.get("value")) for s in e.get("stats") or [] if s.get("name") in _STANDING_STATS}
            note = e.get("note") or None
            entries.append({
                "team_id": str(t["id"]),
                "name": t.get("displayName") or t.get("name") or str(t["id"]),
                "abbreviation": t.get("abbreviation"),
                "logo": ((t.get("logos") or [{}])[0]).get("href"),
                **{k: st.get(k) for k in _STANDING_STATS.values()},
                "note": {"color": note.get("color"), "description": note.get("description")} if note else None,
            })
        if not entries:
            continue
        entries.sort(key=lambda x: (x["rank"] is None, x["rank"] or 0))
        groups.append({"name": ch.get("name") or "", "entries": entries})
    if not groups:
        return None
    season = payload.get("season") or {}
    return {"season": season.get("displayName"), "season_year": _int(season.get("year")), "groups": groups}


async def fetch_team_schedule(client: PoliteClient, team_id: str, season: int) -> dict[str, Any]:
    """Takımın bir sezondaki TÜM maçları (lig + kupa + Avrupa)."""
    return await client.get_json(f"{ESPN_BASE}/all/teams/{team_id}/schedule", {"season": str(season)})


def _score(v: Any) -> int | None:
    if isinstance(v, dict):
        return _int(v.get("value") if v.get("value") is not None else v.get("displayValue"))
    return _int(v)


def parse_team_schedule(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Takım fikstüründen yalnız tamamlanmış maçlar (karşılıklı geçmiş için)."""
    out = []
    for ev in payload.get("events") or []:
        comp = (ev.get("competitions") or [{}])[0]
        st = (comp.get("status") or ev.get("status") or {}).get("type") or {}
        if not st.get("completed"):
            continue
        sides = {c.get("homeAway"): c for c in comp.get("competitors") or []}
        if "home" not in sides or "away" not in sides:
            continue
        h, a = sides["home"], sides["away"]
        hg, ag = _score(h.get("score")), _score(a.get("score"))
        if hg is None or ag is None:
            continue
        league = ev.get("league") if isinstance(ev.get("league"), dict) else {}
        out.append({
            "id": str(ev["id"]), "date_utc": norm_iso(ev["date"]),
            "league": league.get("slug") or "", "league_name": league.get("name") or league.get("abbreviation") or "",
            "home_id": str(h["team"]["id"]), "away_id": str(a["team"]["id"]),
            "home_name": h["team"].get("displayName") or h["team"].get("name") or "",
            "away_name": a["team"].get("displayName") or a["team"].get("name") or "",
            "home_goals": hg, "away_goals": ag, "extra_time": is_extra_time(st),
        })
    return out
