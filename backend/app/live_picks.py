"""Canlı öneriler: kayıt ve sonuçlandırma (GitHub Actions'ın 15 dakikalık çalışmasında).

Tarayıcıdaki canlı modelin (web/lib/live-model.ts) birebir Python karşılığı; pazar mantığı maç öncesi modelle aynı
(markets.outcome_mask). Kriterlere uyan her seçim (maç, pazar, çizgi, sonuç) ilk görüldüğü andaki dakika, skor ve oranla
bir kez kaydedilir; maç bitince 90 dakika skoruna ve gol sırasına göre sonuçlandırılır.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from . import db
from .config import ESPN_BASE, IDDAA_EVENTS_URL
from .model import markets as mk
from .sources.http import FetchError, PoliteClient

RED_OWN = 0.67
RED_OPP = 1.25
N = 7
LIVE_MIN_EV = 0.05
LIVE_MIN_P = 0.25
LIVE_MIN_ODDS = 1.30
LIVE_MAX_ODDS = 8.0
LIVE_MAX_MINUTE = 85
LIVE_MAX_EDGE = 1.5   # model olasılığı ≤ 1.5 × piyasa (marjsız): canlıda piyasa modelin görmediğini bilir
IDDAA_LIVE_URL = IDDAA_EVENTS_URL.replace("type=0", "type=1")
MARKET_LABEL = {4: "Maç sonucu", 14: "Alt/Üst", 34: "Sıradaki gol", 23: "Kalan süre sonucu"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS live_picks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    minute INTEGER NOT NULL,
    score_home INTEGER NOT NULL,
    score_away INTEGER NOT NULL,
    red_home INTEGER NOT NULL,
    red_away INTEGER NOT NULL,
    st INTEGER NOT NULL,
    sov TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    odd REAL NOT NULL,
    p_model REAL NOT NULL,
    ev REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    settled_at TEXT,
    UNIQUE (match_id, st, sov, outcome)
);
"""


@dataclass
class LiveState:
    started: bool
    finished: bool
    period: int
    halftime: bool
    minute: int
    home: int
    away: int
    ht_home: int | None
    ht_away: int | None
    red_home: int
    red_away: int


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clock(s: str | None) -> int:
    m = re.match(r"^(\d+)", s or "")
    return int(m.group(1)) if m else 0


def parse_espn_event(e: dict[str, Any]) -> LiveState | None:
    comp = (e.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    st = (e.get("status") or {}).get("type") or {}
    state = st.get("state", "pre")
    started = state in ("in", "post")
    finished = state == "post" and bool(st.get("completed"))
    period = int((e.get("status") or {}).get("period") or 0)
    halftime = "HALFTIME" in str(st.get("name", ""))
    hs, as_ = int(sides["home"].get("score") or 0), int(sides["away"].get("score") or 0)
    home_id = str((sides["home"].get("team") or {}).get("id"))
    goals: list[tuple[str, int, bool]] = []
    reds = {"home": 0, "away": 0}
    for d in comp.get("details") or []:
        side = "home" if str((d.get("team") or {}).get("id")) == home_id else "away"
        base = _clock((d.get("clock") or {}).get("displayValue"))
        if d.get("scoringPlay"):
            goals.append((side, base, bool(d.get("ownGoal"))))
        elif d.get("redCard"):
            reds[side] += 1
    ht: tuple[int, int] | None = None
    for flip in (False, True):
        fh = fa = h1 = a1 = 0
        for side, base, own in goals:
            sd = ("away" if side == "home" else "home") if (own and flip) else side
            fh += sd == "home"
            fa += sd == "away"
            if base <= 45:
                h1 += sd == "home"
                a1 += sd == "away"
        if fh == hs and fa == as_:
            ht = (h1, a1)
            break
    known_ht = period >= 2 or halftime or finished
    minute = 90 if finished else 45 if halftime else min(_clock((e.get("status") or {}).get("displayClock")), 90)
    return LiveState(started, finished, min(period, 2), halftime, minute, hs, as_,
                     ht[0] if (ht and known_ht) else None, ht[1] if (ht and known_ht) else None, reds["home"], reds["away"])


def _shares(s: LiveState, p1: float) -> tuple[float, float]:
    if not s.started:
        return p1, 1 - p1
    if s.finished:
        return 0.0, 0.0
    if s.period <= 1 and not s.halftime:
        m = min(max(s.minute, 0), 45)
        return p1 * max(45 - m, 0.5) / 45, 1 - p1
    if s.halftime:
        return 0.0, 1 - p1
    m = min(max(s.minute, 45), 90)
    return 0.0, (1 - p1) * max(90 - m, 1) / 45


def _pois(lam: float) -> np.ndarray:
    k = np.arange(N)
    p = np.array([math.exp(-lam) * lam**i / math.factorial(i) for i in k])
    p[-1] += max(0.0, 1 - p.sum())
    return p


def live_joint(lh: float, la: float, p1: float, g: float, s: LiveState) -> tuple[mk.Joint, np.ndarray, np.ndarray, float, float]:
    """Dönüş: ortak dağılım (X, Y, I, J), kalan ev/dep golleri dizileri, kalan beklenen ev/dep golleri."""
    s1, s2 = _shares(s, p1)
    adj_h = RED_OWN**s.red_home * RED_OPP**s.red_away
    adj_a = RED_OWN**s.red_away * RED_OPP**s.red_home
    lh_, la_ = lh * g * adj_h, la * g * adj_a
    a, b, c, d = np.meshgrid(np.arange(N), np.arange(N), np.arange(N), np.arange(N), indexing="ij")
    P = (_pois(lh_ * s1)[:, None, None, None] * _pois(la_ * s1)[None, :, None, None]
         * _pois(lh_ * s2)[None, None, :, None] * _pois(la_ * s2)[None, None, None, :])
    in_first = not s.started or (s.period <= 1 and not s.halftime)
    I = s.home + a if in_first else np.full_like(a, s.ht_home if s.ht_home is not None else s.home)
    J = s.away + b if in_first else np.full_like(b, s.ht_away if s.ht_away is not None else s.away)
    X = s.home + a + c
    Y = s.away + b + d
    return mk.Joint(P, X, Y, I, J), a + c, b + d, lh_ * (s1 + s2), la_ * (s1 + s2)


def outcome_prob(st: int, sov: str | None, name: str, joint: mk.Joint, rem_h: np.ndarray, rem_a: np.ndarray,
                 eh: float, ea: float) -> float | None:
    if st == 4:
        m = mk.outcome_mask("ms", None, name, joint)
    elif st == 14:
        m = mk.outcome_mask("au", sov, name, joint)
    elif st == 23:
        m = {"1": rem_h > rem_a, "0": rem_h == rem_a, "2": rem_h < rem_a}.get(name)
    elif st == 34:
        t = eh + ea
        none = math.exp(-t)
        if t <= 0:
            return None
        return {"1": (1 - none) * eh / t, "2": (1 - none) * ea / t, "Olmaz": none}.get(name)
    else:
        return None
    return float(joint.P[m].sum()) if m is not None else None


_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o", "ş": "s", "ü": "u"})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.translate(_TR).lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


async def _fetch(con: sqlite3.Connection, items: list[sqlite3.Row]) -> tuple[dict[str, LiveState], list[dict[str, Any]]]:
    async with PoliteClient(concurrency=3, min_interval=0.3) as client:
        groups: dict[tuple[str, str], set[str]] = {}
        for it in items:
            et = (datetime.fromisoformat(it["date_utc"].replace("Z", "+00:00")) - timedelta(hours=4)).strftime("%Y%m%d")
            groups.setdefault((it["league"], et), set()).add(it["id"])

        async def sb(league: str, date: str) -> list[dict[str, Any]]:
            try:
                return (await client.get_json(f"{ESPN_BASE}/{league}/scoreboard", {"dates": date})).get("events", [])
            except FetchError:
                return []

        res = await asyncio.gather(*(sb(lg, dt) for lg, dt in groups))
        states: dict[str, LiveState] = {}
        for (lg, dt), evs in zip(groups, res):
            for e in evs:
                if e.get("id") in groups[(lg, dt)]:
                    s = parse_espn_event(e)
                    if s:
                        states[e["id"]] = s
        try:
            live = (await client.get_json(IDDAA_LIVE_URL)).get("data", {}).get("events", [])
        except FetchError:
            live = []
    return states, live


def record_live_picks(con: sqlite3.Connection) -> dict[str, int]:
    con.executescript(SCHEMA)
    now = datetime.now(timezone.utc)
    items = con.execute(
        """SELECT m.id, m.league, m.date_utc, m.home_id, m.away_id, p.payload FROM matches m
           JOIN predictions p ON p.match_id = m.id
           WHERE m.date_utc >= ? AND m.date_utc <= ?""",
        (_iso(now - timedelta(hours=2, minutes=30)), _iso(now + timedelta(minutes=5))),
    ).fetchall()
    if not items:
        return {"canli_mac": 0, "yeni_oneri": 0}
    states, live = asyncio.run(_fetch(con, items))
    ev_rows = {r["espn_match_id"]: r for r in con.execute(
        "SELECT id, home_name, away_name, kickoff_utc, espn_match_id FROM iddaa_events WHERE espn_match_id IS NOT NULL")}
    by_id = {e["i"]: e for e in live if e.get("m")}
    added = n_live = 0
    with db.tx(con):
        for it in items:
            s = states.get(it["id"])
            if not s or not s.started or s.finished or s.minute > LIVE_MAX_MINUTE:
                continue
            p = json.loads(it["payload"])
            mod = p.get("model")
            if not p.get("covered") or not mod or mod.get("confidence") in ("düşük", "yok"):
                continue
            ev = ev_rows.get(it["id"])
            if ev is None:
                continue
            le = by_id.get(ev["id"])
            if le is None:
                kick = datetime.fromisoformat(ev["kickoff_utc"].replace("Z", "+00:00")).timestamp()
                le = next((e for e in live if e.get("m") and abs(e["d"] - kick) <= 1200
                           and _norm(e["hn"]) == _norm(ev["home_name"]) and _norm(e["an"]) == _norm(ev["away_name"])), None)
            if le is None:
                continue
            n_live += 1
            joint, rh, ra, eh, ea = live_joint(mod["lambda_home"], mod["lambda_away"], mod["p1"], mod.get("cal_g", 1.0), s)
            for m in le["m"]:
                if m.get("t") != 4 or m.get("st") not in MARKET_LABEL:
                    continue
                outs = [o for o in m.get("o", []) if float(o.get("odd") or 0) > 1.0]
                inv = sum(1 / float(o["odd"]) for o in outs)
                for o in outs:
                    odd = float(o.get("odd") or 0)
                    name = str(o.get("n", ""))
                    if not (LIVE_MIN_ODDS <= odd <= LIVE_MAX_ODDS):
                        continue
                    pr = outcome_prob(int(m["st"]), m.get("sov"), name, joint, rh, ra, eh, ea)
                    q = (1 / odd) / inv if inv > 0 else None
                    if pr is None or pr < LIVE_MIN_P or pr * odd - 1 < LIVE_MIN_EV or q is None or pr > LIVE_MAX_EDGE * q:
                        continue
                    cur = con.execute(
                        """INSERT OR IGNORE INTO live_picks(match_id, created_at, minute, score_home, score_away, red_home,
                               red_away, st, sov, outcome, odd, p_model, ev) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (it["id"], _iso(now), s.minute, s.home, s.away, s.red_home, s.red_away, int(m["st"]),
                         m.get("sov") or "", name, odd, pr, pr * odd - 1),
                    )
                    added += cur.rowcount
    return {"canli_mac": n_live, "yeni_oneri": added}


def _goal_sequence(con: sqlite3.Connection, m: sqlite3.Row) -> list[str] | None:
    """90 dakikadaki goller sırasıyla ('home'/'away'); kendi kalesine gol ataması skorla tutarlı olacak biçimde."""
    rows = con.execute(
        "SELECT team_id, period, minute, own_goal, seq FROM goal_events WHERE match_id=? AND period IN (1,2) ORDER BY seq",
        (m["id"],),
    ).fetchall()
    for flip in (False, True):
        seq = []
        for r in rows:
            side = "home" if r["team_id"] == m["home_id"] else "away"
            if r["own_goal"] and flip:
                side = "away" if side == "home" else "home"
            seq.append(side)
        if seq.count("home") == m["ft90_home"] and seq.count("away") == m["ft90_away"]:
            return seq
    return None


def settle_live_picks(con: sqlite3.Connection) -> dict[str, int]:
    con.executescript(SCHEMA)
    rows = con.execute(
        """SELECT lp.*, m.ft90_home, m.ft90_away, m.home_id, m.away_id, m.completed, m.state
           FROM live_picks lp JOIN matches m ON m.id = lp.match_id WHERE lp.status='open'"""
    ).fetchall()
    now = _iso(datetime.now(timezone.utc))
    settled = 0
    with db.tx(con):
        for r in rows:
            if r["state"] == "post" and not r["completed"]:
                status = "void"
            elif not r["completed"] or r["ft90_home"] is None:
                continue
            else:
                X, Y = r["ft90_home"], r["ft90_away"]
                st, name, sov = r["st"], r["outcome"], r["sov"]
                won: bool | None
                if st == 4:
                    won = {"1": X > Y, "0": X == Y, "2": X < Y}.get(name)
                elif st == 14:
                    line = float(sov)
                    won = {"Alt": X + Y < line, "Üst": X + Y > line}.get(name)
                elif st == 23:
                    rh, ra = X - r["score_home"], Y - r["score_away"]
                    won = {"1": rh > ra, "0": rh == ra, "2": rh < ra}.get(name)
                elif st == 34:
                    seq = _goal_sequence(con, {"id": r["match_id"], "home_id": r["home_id"], "ft90_home": X, "ft90_away": Y})
                    n = int(sov) if sov.isdigit() else r["score_home"] + r["score_away"] + 1
                    if seq is None:
                        won = None
                    else:
                        actual = seq[n - 1] if len(seq) >= n else "none"
                        won = {"1": actual == "home", "2": actual == "away", "Olmaz": actual == "none"}.get(name)
                else:
                    won = None
                if won is None:
                    status = "void"
                else:
                    status = "won" if won else "lost"
            con.execute("UPDATE live_picks SET status=?, settled_at=? WHERE id=?", (status, now, r["id"]))
            settled += 1
    return {"acik": len(rows), "sonuclanan": settled}


def live_picks_summary(con: sqlite3.Connection) -> dict[str, Any]:
    con.executescript(SCHEMA)
    rows = con.execute(
        """SELECT lp.*, th.name hn, ta.name an FROM live_picks lp JOIN matches m ON m.id=lp.match_id
           JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id ORDER BY lp.created_at DESC"""
    ).fetchall()
    settled = [r for r in rows if r["status"] in ("won", "lost")]
    won = [r for r in settled if r["status"] == "won"]
    by_market: dict[str, dict[str, Any]] = {}
    for r in settled:
        g = by_market.setdefault(MARKET_LABEL.get(r["st"], str(r["st"])), {"n": 0, "won": 0, "staked": 0.0, "returned": 0.0, "expected": 0.0})
        g["n"] += 1
        g["staked"] += 1
        g["expected"] += r["p_model"]
        if r["status"] == "won":
            g["won"] += 1
            g["returned"] += r["odd"]
    for g in by_market.values():
        g["hit_rate"] = g["won"] / g["n"] if g["n"] else None
        g["expected_hit_rate"] = g["expected"] / g["n"] if g["n"] else None
        g["roi"] = (g["returned"] - g["staked"]) / g["staked"] if g["staked"] else None
    return {
        "n": len(rows),
        "settled": len(settled),
        "won": len(won),
        "hit_rate": len(won) / len(settled) if settled else None,
        "expected_hit_rate": sum(r["p_model"] for r in settled) / len(settled) if settled else None,
        "roi": (sum(r["odd"] for r in won) - len(settled)) / len(settled) if settled else None,
        "by_market": by_market,
        "recent": [
            {"match_id": r["match_id"], "home": r["hn"], "away": r["an"], "created_at": r["created_at"], "minute": r["minute"],
             "score": f"{r['score_home']}-{r['score_away']}", "market": MARKET_LABEL.get(r["st"], str(r["st"])),
             "sov": r["sov"], "outcome": r["outcome"], "odd": r["odd"], "p_model": r["p_model"], "ev": r["ev"],
             "status": r["status"]}
            for r in rows[:40]
        ],
    }
