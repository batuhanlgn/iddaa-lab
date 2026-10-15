"""iddaa bülten maçlarını ESPN maçlarıyla eşleştirme (başlama saati + takım adı benzerliği + öğrenilmiş takma adlar)."""
from __future__ import annotations

import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from . import db

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o", "ş": "s", "ü": "u", "Ç": "c", "Ğ": "g", "Ö": "o", "Ş": "s", "Ü": "u"})
_STOP = {
    "fc", "fk", "sk", "cf", "afc", "ac", "as", "sc", "club", "de", "the", "jk", "cd", "ud", "sd", "rc", "if", "bk", "ff",
    "spor", "kulubu", "calcio", "sv", "vfb", "vfl", "tsg", "1.", "ssc", "us", "ss", "ca", "cr", "se", "ec", "sad", "a.s.",
}
_SYN = {
    "kizil yildiz": "crvena zvezda red star belgrade",
    "manchester utd": "manchester united",
    "man utd": "manchester united",
    "man city": "manchester city",
    "wolverhampton": "wolverhampton wanderers wolves",
    "inter": "internazionale inter milan",
    "bayern munih": "bayern munich",
    "bayern münih": "bayern munich",
    "koln": "cologne koln",
    "sporting lizbon": "sporting cp",
    "benfica": "benfica",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "atletico madrid": "atletico madrid",
    "basaksehir": "istanbul basaksehir",
    "nott. forest": "nottingham forest",
    "nottingham": "nottingham forest",
    "paranaense": "athletico paranaense athletico pr",
    "new york city": "new york city fc nycfc",
    "palmeiras sp": "palmeiras",
    "los angeles fc": "lafc los angeles fc",
    "lafc": "lafc los angeles fc",
}


def norm(name: str) -> str:
    s = name.translate(_TR).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("-", " ").replace("'", " ").replace(".", ". ").replace("/", " ")
    s = " ".join(s.split())
    for k, v in _SYN.items():
        if s == k or s.startswith(k + " "):
            s = v
    return s


def tokens(s: str) -> set[str]:
    return {t.strip(".") for t in s.split() if t.strip(".") and t not in _STOP and t.strip(".") not in _STOP}


def similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if na == nb:
        return 1.0
    ta, tb = tokens(na), tokens(nb)
    jac = len(ta & tb) / len(ta | tb) if ta and tb else 0.0
    contain = 1.0 if ta and tb and (ta <= tb or tb <= ta) else 0.0
    seq = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return max(jac, 0.9 * contain, seq * 0.95)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def match_iddaa_events(con: sqlite3.Connection) -> dict[str, int]:
    aliases = {(r["alias"]): r["team_id"] for r in con.execute("SELECT alias, team_id FROM team_alias WHERE source='iddaa'")}
    events = con.execute(
        "SELECT id, home_name, away_name, kickoff_utc FROM iddaa_events WHERE is_live=0 AND kickoff_utc >= ?",
        ((datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    ).fetchall()
    espn = con.execute(
        """SELECT m.id, m.date_utc, m.home_id, m.away_id, th.name hn, ta.name an, th.short_name hs, ta.short_name as_
           FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
           WHERE m.date_utc >= ?""",
        ((datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),),
    ).fetchall()
    by_time: list[tuple[datetime, sqlite3.Row]] = [(_dt(r["date_utc"]), r) for r in espn]
    matched = 0
    learned = 0
    with db.tx(con):
        for e in events:
            ko = _dt(e["kickoff_utc"])
            best: tuple[float, sqlite3.Row | None, float, float] = (0.0, None, 0.0, 0.0)
            for t, r in by_time:
                if abs((t - ko).total_seconds()) > 100 * 60:
                    continue
                sh = 1.0 if aliases.get(norm(e["home_name"])) == r["home_id"] else max(
                    similarity(e["home_name"], r["hn"]), similarity(e["home_name"], r["hs"] or r["hn"]))
                sa = 1.0 if aliases.get(norm(e["away_name"])) == r["away_id"] else max(
                    similarity(e["away_name"], r["an"]), similarity(e["away_name"], r["as_"] or r["an"]))
                time_bonus = 0.1 if abs((t - ko).total_seconds()) <= 20 * 60 else 0.0
                sc = sh + sa + time_bonus
                ok = (sh >= 0.5 and sa >= 0.5) or (max(sh, sa) >= 0.9 and min(sh, sa) >= 0.25 and time_bonus > 0)
                if ok and sc > best[0]:
                    best = (sc, r, sh, sa)
            sc, r, sh, sa = best
            if r is None:
                con.execute("UPDATE iddaa_events SET espn_match_id=NULL, match_score=NULL WHERE id=?", (e["id"],))
                continue
            con.execute("UPDATE iddaa_events SET espn_match_id=?, match_score=? WHERE id=?", (r["id"], sc, e["id"]))
            matched += 1
            # Yüksek güvenli eşleşmelerde diğer tarafın adını takma ad olarak öğren
            if sh >= 0.9 and sa < 0.9 and sa >= 0.25:
                con.execute("INSERT OR IGNORE INTO team_alias VALUES('iddaa', ?, ?, ?)", (norm(e["away_name"]), r["away_id"], sa))
                learned += 1
            if sa >= 0.9 and sh < 0.9 and sh >= 0.25:
                con.execute("INSERT OR IGNORE INTO team_alias VALUES('iddaa', ?, ?, ?)", (norm(e["home_name"]), r["home_id"], sh))
                learned += 1
    return {"iddaa_events": len(events), "matched": matched, "aliases_learned": learned}
