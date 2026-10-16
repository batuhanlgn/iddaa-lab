"""Spor Toto: haftalık program, maç olasılıkları, bütçeli sistem kuponları ve sonuçlandırma.

Kupon kuralı: her maç için 1, 2 ya da 3 sonuç işaretlenir; kolon sayısı = Π(işaret sayısı), maliyet = kolon × kolon
bedeli. Haftada üç kupon, her biri bütçe (TOTO_BUDGET_TL) ve kupon başına kolon sınırı içinde:
  olasilik     15 maçı da bilme olasılığını en büyütür: max Σ log(kapsanan olasılık_i)  koşul: 2^çift · 3^üçlü ≤ en çok
               kolon. Çift/üçlü sayısı küçük olduğundan kesin DP (optimize).
  kalabalik    oynanma oranlarına (kalabalık) göre beklenen ikramiyeyi en büyütür (sportoto_crowd).
  kalabalik_2  aynı amaç, kalabalik ile ortak kolonu yok (sportoto_crowd).

Kuponlar (toto_coupon_sets, PK hafta + tür) kapanıştan TOTO_LOCK_MINUTES önce ayrı ayrı kilitlenir; o ana kadar her
güncellemede en taze olasılıklar ve oynanma oranlarıyla yeniden kurulur. Kalabalık verisi ya da N/havuz tahmini yoksa
yalnız Kupon 1 kurulur (neden yükte yazar). Sonuç açıklanınca her kuponun kazanan kolonları ve ikramiyesi saklanır.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from . import db
from .config import TOTO_BUDGET_TL, TOTO_DEFAULT_COLUMN_PRICE, TOTO_DEFAULT_MAX_COLUMN, TOTO_LOCK_MINUTES
from .matching import similarity
from .model import markets as mk
from .sources import sportoto as src
from .sources.http import PoliteClient

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

OUTCOMES = ("1", "0", "2")
TIERS = (15, 14, 13, 12)
KINDS = ("olasilik", "kalabalik", "kalabalik_2")
KIND_INFO: dict[str, tuple[str, str]] = {
    "olasilik": ("Kupon 1 · Olasılık", "15 maçı da bilme olasılığını en büyüten kupon (bugünkü mantık)."),
    "kalabalik": ("Kupon 2 · Kalabalık",
                  "Beklenen ikramiyeyi en büyüten kupon: az oynanan ama makul sonuçlara ağırlık verir; herkesin oynadığı "
                  "favori tutsa da ikramiye çok kişiyle bölünür."),
    "kalabalik_2": ("Kupon 3 · Kalabalık (ikinci)",
                    "Kupon 2 ile aynı amaç, ama Kupon 2'nin hiçbir kolonunu tekrar etmez (en az bir maçta işaretler ayrık): "
                    "ikinci en iyi seçimler."),
}
_MATCH_WINDOW_S = 100 * 60
_SUFFIXES = (" a.ş.", " a.ş", " aş")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _clean(name: str) -> str:
    n = name.strip()
    low = n.lower()
    for suf in _SUFFIXES:
        if low.endswith(suf):
            return n[: -len(suf)].strip()
    return n


def split_event_name(name: str) -> list[tuple[str, str]]:
    """"Ev-Deplasman" ya da "Ev - Deplasman". Takım adında da tire olabileceği için tüm ayırma noktaları aday döner."""
    if " - " in name:
        h, a = name.split(" - ", 1)
        return [(_clean(h), _clean(a))]
    parts = name.split("-")
    return [(_clean("-".join(parts[:i])), _clean("-".join(parts[i:]))) for i in range(1, len(parts))]


# ---------------------------------------------------------------- eşleştirme

def _best_match(cands: list[tuple[str, str]], kickoff: str | None, rows: list[sqlite3.Row], time_key: str,
                hn: str, an: str) -> tuple[sqlite3.Row | None, str, str]:
    if kickoff is None:
        return None, cands[0][0], cands[0][1]
    ko = _dt(kickoff)
    best: tuple[float, sqlite3.Row | None, str, str] = (0.0, None, cands[0][0], cands[0][1])
    for r in rows:
        if abs((_dt(r[time_key]) - ko).total_seconds()) > _MATCH_WINDOW_S:
            continue
        for h, a in cands:
            sh, sa = similarity(h, r[hn]), similarity(a, r[an])
            if (sh >= 0.62 and sa >= 0.62) or (max(sh, sa) >= 0.9 and min(sh, sa) >= 0.35):
                if sh + sa > best[0]:
                    best = (sh + sa, r, h, a)
    return best[1], best[2], best[3]


def match_events(con: sqlite3.Connection, cycle_no: int) -> int:
    """Toto maçlarını iddaa bülteni (oran) ve ESPN maçlarıyla (model tahmini) eşleştirir."""
    evs = con.execute("SELECT * FROM toto_events WHERE cycle_no=?", (cycle_no,)).fetchall()
    kos = [e["kickoff_utc"] for e in evs if e["kickoff_utc"]]
    if not kos:
        return 0
    lo = _iso(min(_dt(k) for k in kos) - timedelta(hours=3))
    hi = _iso(max(_dt(k) for k in kos) + timedelta(hours=3))
    espn_rows = con.execute(
        """SELECT m.id, m.date_utc, th.name hn, ta.name an FROM matches m
           JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id WHERE m.date_utc BETWEEN ? AND ?""",
        (lo, hi),
    ).fetchall()
    iddaa_rows = con.execute(
        "SELECT id, kickoff_utc, home_name, away_name, espn_match_id FROM iddaa_events WHERE kickoff_utc BETWEEN ? AND ?",
        (lo, hi),
    ).fetchall()
    n = 0
    with db.tx(con):
        for e in evs:
            cands = split_event_name(e["event_name"])
            ie, h, a = _best_match(cands, e["kickoff_utc"], iddaa_rows, "kickoff_utc", "home_name", "away_name")
            em, h2, a2 = _best_match(cands, e["kickoff_utc"], espn_rows, "date_utc", "hn", "an")
            espn_id = em["id"] if em is not None else (ie["espn_match_id"] if ie is not None else None)
            home, away = (h, a) if ie is not None else (h2, a2)
            con.execute(
                "UPDATE toto_events SET home=?, away=?, espn_match_id=?, iddaa_event_id=? WHERE cycle_no=? AND event_no=?",
                (home, away, espn_id, ie["id"] if ie is not None else None, cycle_no, e["event_no"]),
            )
            n += espn_id is not None or ie is not None
    return n


# ---------------------------------------------------------------- olasılıklar

def _latest_payload(con: sqlite3.Connection, match_id: str) -> dict[str, Any] | None:
    r = con.execute("SELECT payload FROM predictions WHERE match_id=? ORDER BY created_at DESC LIMIT 1", (match_id,)).fetchone()
    return json.loads(r["payload"]) if r else None


def event_probs(con: sqlite3.Connection, ev: sqlite3.Row) -> dict[str, Any]:
    """1/0/2 olasılığı, öncelik sırasıyla: model+piyasa harmanı > model > iddaa oranı (marjsız) > bilgi yok (eşit)."""
    out: dict[str, Any] = {"source": "yok", "probs": {o: 1 / 3 for o in OUTCOMES}, "confidence": None, "match_id": None,
                           "league_name": None, "odds": None, "model": None, "market": None}
    p = _latest_payload(con, ev["espn_match_id"]) if ev["espn_match_id"] else None
    if p is not None:
        out["match_id"] = p["match"]["id"]
        out["league_name"] = p["match"].get("league_name")
    if p is not None and p.get("covered"):
        out["confidence"] = p["model"]["confidence"]
        ms_model = next((m for m in p.get("markets") or [] if m["key"] == "ms"), None)
        if ms_model:
            out["model"] = {o["name"]: o["p_model"] for o in ms_model["outcomes"]}
        ms_iddaa = next((m for m in (p.get("iddaa") or {}).get("markets") or [] if m["key"] == "ms"), None)
        if ms_iddaa:
            outs = {o["name"]: o for o in ms_iddaa["outcomes"]}
            if all(k in outs for k in OUTCOMES):
                out["odds"] = {k: outs[k]["odd"] for k in OUTCOMES}
                out["market"] = {k: outs[k]["p_market"] for k in OUTCOMES}
                if all(outs[k].get("p_blend") is not None for k in OUTCOMES):
                    s = sum(outs[k]["p_blend"] for k in OUTCOMES)
                    out.update(source="harman", probs={k: outs[k]["p_blend"] / s for k in OUTCOMES})
                    return out
        if out["model"] and all(k in out["model"] for k in OUTCOMES):
            out.update(source="model", probs=dict(out["model"]))
            return out
    if ev["iddaa_event_id"] is not None:
        odds = {r["outcome_name"]: r["odd"] for r in con.execute(
            "SELECT outcome_name, odd FROM odds_current WHERE event_id=? AND market_key='1:1:'", (ev["iddaa_event_id"],))}
        if all(k in odds for k in OUTCOMES):
            q = mk.devig([odds[k] for k in OUTCOMES])
            out.update(source="piyasa", probs=dict(zip(OUTCOMES, q)), odds={k: odds[k] for k in OUTCOMES},
                       market=dict(zip(OUTCOMES, q)))
    return out


# ---------------------------------------------------------------- kupon optimizasyonu

def optimize(probs: list[dict[str, float]], max_columns: int) -> list[list[str]]:
    """Her maç için işaretlenecek sonuçlar (olasılığa göre ilk 1/2/3). Kolon ≤ max_columns altında Π kapsama en büyük."""
    ranked = [sorted(OUTCOMES, key=lambda o: -p[o]) for p in probs]
    gain = []
    for p, r in zip(probs, ranked):
        c1 = max(p[r[0]], 1e-12)
        c2 = max(p[r[0]] + p[r[1]], 1e-12)
        gain.append((math.log(c1), math.log(c2), 0.0))
    max_d = int(math.floor(math.log2(max(max_columns, 1)) + 1e-9))
    max_t = int(math.floor(math.log(max(max_columns, 1), 3) + 1e-9))
    # dp[(d, t)] = (toplam log kapsama, seçim listesi)
    dp: dict[tuple[int, int], tuple[float, list[int]]] = {(0, 0): (0.0, [])}
    for g in gain:
        nxt: dict[tuple[int, int], tuple[float, list[int]]] = {}
        for (d, t), (v, sel) in dp.items():
            for size, (dd, tt) in ((1, (d, t)), (2, (d + 1, t)), (3, (d, t + 1))):
                if dd > max_d or tt > max_t or 2**dd * 3**tt > max_columns:
                    continue
                nv = v + g[size - 1]
                if (dd, tt) not in nxt or nv > nxt[(dd, tt)][0]:
                    nxt[(dd, tt)] = (nv, sel + [size])
        dp = nxt
    _, sizes = max(dp.values(), key=lambda x: (x[0], -len([s for s in x[1] if s > 1])))
    return [r[:s] for r, s in zip(ranked, sizes)]


def hit_distribution(covers: list[float]) -> list[float]:
    """En iyi kolondaki doğru sayısının dağılımı (Poisson-binom): dist[k] = P(k maç kapsandı)."""
    dist = [1.0]
    for c in covers:
        new = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            new[k] += v * (1 - c)
            new[k + 1] += v * c
        dist = new
    return dist


def winning_columns(picks: list[list[str]], winners: list[str]) -> dict[int, int]:
    """Sistem kuponunda k doğru tutturan kolon sayısı: Π (isabet ? x + (s−1) : s) polinomunun katsayıları."""
    poly = [1]
    for sel, w in zip(picks, winners):
        s = len(sel)
        term = [s - 1, 1] if w in sel else [s]
        new = [0] * (len(poly) + len(term) - 1)
        for i, a in enumerate(poly):
            for j, b in enumerate(term):
                new[i + j] += a * b
        poly = new
    return {k: poly[k] for k in TIERS if k < len(poly) and poly[k] > 0}


def _pool(con: sqlite3.Connection) -> dict[str, Any]:
    cfg = db.meta_get(con, "toto_pool")
    if cfg:
        return {**cfg, "source": "iddaa"}
    return {"column_price": TOTO_DEFAULT_COLUMN_PRICE, "max_column": TOTO_DEFAULT_MAX_COLUMN, "source": "varsayılan"}


def max_columns(pool: dict[str, Any]) -> int:
    return min(int(TOTO_BUDGET_TL // pool["column_price"]), int(pool["max_column"]))


def build_coupon(con: sqlite3.Connection, cycle_no: int) -> dict[str, Any]:
    """Kupon 1 (olasilik); Kupon 2/3 bu yükün olasılıkları ve maç bilgisiyle kurulur."""
    pool = _pool(con)
    max_cols = max_columns(pool)
    evs = con.execute("SELECT * FROM toto_events WHERE cycle_no=? ORDER BY event_no", (cycle_no,)).fetchall()
    infos = [event_probs(con, e) for e in evs]
    picks = optimize([i["probs"] for i in infos], max_cols)
    covers = [sum(i["probs"][o] for o in sel) for i, sel in zip(infos, picks)]
    dist = hit_distribution(covers)
    columns = math.prod(len(s) for s in picks)
    n = len(evs)
    events = []
    for e, info, sel, cov in zip(evs, infos, picks, covers):
        events.append({
            "event_no": e["event_no"], "event_name": e["event_name"], "home": e["home"], "away": e["away"],
            "competition": e["competition"], "kickoff_utc": e["kickoff_utc"], "picks": sel, "cover": cov,
            "kind": {1: "banko", 2: "çift", 3: "üçlü"}[len(sel)], **info,
        })
    title, desc = KIND_INFO["olasilik"]
    return {
        "kind": "olasilik", "title": title, "description": desc, "expected_prize": None, "expected_prize_by_tier": None,
        "cycle_no": cycle_no, "budget": TOTO_BUDGET_TL, "column_price": pool["column_price"], "max_column": pool["max_column"],
        "pool_source": pool["source"], "columns": columns, "cost": columns * pool["column_price"],
        "p15": dist[n] if n == 15 else 0.0,
        "p_at_least": {str(k): sum(dist[k:]) for k in TIERS if k <= n},
        "expected_hits": sum(covers), "events": events,
        "n_no_data": sum(1 for i in infos if i["source"] == "yok"),
    }


def _upsert(con: sqlite3.Connection, c: dict[str, Any], locked: int, ts: str) -> None:
    con.execute(
        """INSERT INTO toto_coupon_sets(cycle_no, kind, created_at, updated_at, locked, budget, column_price, columns, cost,
                                        p15, expected_prize, payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(cycle_no, kind) DO UPDATE SET updated_at=excluded.updated_at, locked=excluded.locked,
             budget=excluded.budget, column_price=excluded.column_price, columns=excluded.columns, cost=excluded.cost,
             p15=excluded.p15, expected_prize=excluded.expected_prize, payload=excluded.payload""",
        (c["cycle_no"], c["kind"], ts, ts, locked, c["budget"], c["column_price"], c["columns"], c["cost"], c["p15"],
         c.get("expected_prize"), json.dumps(c, ensure_ascii=False)),
    )


def update_coupon(con: sqlite3.Connection, cycle_no: int) -> str:
    """Haftanın üç kuponunu kurar/günceller; kilitli kupon değişmez. Kalabalık kuponları kurulamazsa nedeni Kupon 1'in
    yüküne (crowd_status) yazılır ve kilitlenmemiş eski kalabalık kuponları silinir."""
    w = con.execute("SELECT payin_end_utc FROM toto_weeks WHERE cycle_no=?", (cycle_no,)).fetchone()
    if w is None:
        return "hafta yok"
    now = datetime.now(timezone.utc)
    end = _dt(w["payin_end_utc"])
    rows = {r["kind"]: r for r in con.execute("SELECT kind, locked FROM toto_coupon_sets WHERE cycle_no=?", (cycle_no,))}
    if "olasilik" in rows and all(r["locked"] for r in rows.values()):
        return "kilitli"
    if now >= end:
        if rows:
            con.execute("UPDATE toto_coupon_sets SET locked=1 WHERE cycle_no=?", (cycle_no,))
            return "kapanış geçti, kilitlendi"
        return "kapanış geçti, kupon yok"
    lock_at = end - timedelta(minutes=TOTO_LOCK_MINUTES)
    locked = int(now >= lock_at)
    base = build_coupon(con, cycle_no)
    from .sportoto_crowd import build_crowd_coupons  # geç içe aktarma: sportoto_crowd bu modülü kullanır

    try:
        built, reason = build_crowd_coupons(con, cycle_no, base, lock_at, max_columns(_pool(con)))
    except Exception as e:  # noqa: BLE001 - kalabalık kuponu hatası Kupon 1'i engellemesin
        log.exception("Kalabalık kuponları kurulamadı")
        built, reason = {}, f"Kalabalık kuponları hesaplanamadı ({type(e).__name__}: {e})"
    coupons = {"olasilik": built.get("olasilik", base), **{k: v for k, v in built.items() if k != "olasilik"}}
    coupons["olasilik"]["crowd_status"] = {"available": reason is None, "reason": reason}
    ts = _iso(now)
    for kind in KINDS:
        if kind in rows and rows[kind]["locked"]:
            continue
        if kind in coupons:
            _upsert(con, coupons[kind], locked, ts)
        elif kind in rows:
            con.execute("DELETE FROM toto_coupon_sets WHERE cycle_no=? AND kind=?", (cycle_no, kind))
    parts = [f"{k}: {c['columns']} kolon · {c['cost']:.0f} TL · 15 bilme %{100 * c['p15']:.3f}"
             + (f" · beklenen ikramiye {c['expected_prize']:.0f} TL" if c.get("expected_prize") is not None else "")
             for k, c in coupons.items()]
    if reason:
        parts.append(f"kalabalık kuponu yok: {reason}")
    return " | ".join(parts) + (" · kilitlendi" if locked else "")


# ---------------------------------------------------------------- veri toplama ve sonuçlandırma

def _store_week(con: sqlite3.Connection, w: src.TotoWeek, fetched_at: str) -> None:
    con.execute(
        """INSERT INTO toto_weeks(cycle_no, program_name, payin_begin_utc, payin_end_utc, fetched_at)
           VALUES(?,?,?,?,?) ON CONFLICT(cycle_no) DO UPDATE SET program_name=excluded.program_name,
           payin_begin_utc=excluded.payin_begin_utc, payin_end_utc=excluded.payin_end_utc, fetched_at=excluded.fetched_at""",
        (w.cycle_no, w.program_name, w.payin_begin_utc, w.payin_end_utc, fetched_at),
    )
    for e in w.events:
        con.execute(
            """INSERT INTO toto_events(cycle_no, event_no, event_name, competition, kickoff_utc, result, winner)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(cycle_no, event_no) DO UPDATE SET event_name=excluded.event_name,
               competition=excluded.competition, kickoff_utc=excluded.kickoff_utc,
               result=COALESCE(excluded.result, toto_events.result), winner=COALESCE(excluded.winner, toto_events.winner)""",
            (w.cycle_no, e.event_no, e.event_name, e.competition, e.kickoff_utc, e.result, e.winner),
        )


def settle_coupon(con: sqlite3.Connection, cycle_no: int) -> str | None:
    """Haftanın açık kuponlarını (her tür ayrı) resmi sonuç ve ikramiye tablosuyla sonuçlandırır."""
    rows = con.execute("SELECT * FROM toto_coupon_sets WHERE cycle_no=? AND status='open'", (cycle_no,)).fetchall()
    w = con.execute("SELECT dividends FROM toto_weeks WHERE cycle_no=?", (cycle_no,)).fetchone()
    if not rows or w is None or w["dividends"] is None:
        return None
    winners = {r["event_no"]: r["winner"] for r in con.execute(
        "SELECT event_no, winner FROM toto_events WHERE cycle_no=?", (cycle_no,))}
    amounts = {d["tier"]: d["amount"] for d in json.loads(w["dividends"])}
    out = []
    for row in rows:
        payload = json.loads(row["payload"])
        picks = [ev["picks"] for ev in payload["events"]]
        res = [winners.get(ev["event_no"]) for ev in payload["events"]]
        if any(r is None for r in res):
            return None
        hits = sum(1 for sel, r in zip(picks, res) if r in sel)
        cols = winning_columns(picks, res)  # type: ignore[arg-type]
        prize = sum(n * amounts.get(k, 0.0) for k, n in cols.items())
        con.execute(
            """UPDATE toto_coupon_sets SET status='settled', hits=?, winning_columns=?, prize=?, settled_at=?, locked=1
               WHERE cycle_no=? AND kind=?""",
            (hits, json.dumps({str(k): v for k, v in cols.items()}), prize, _iso(datetime.now(timezone.utc)), cycle_no,
             row["kind"]),
        )
        out.append(f"{row['kind']} {hits}/15 · {prize:.2f} TL")
    return f"hafta {cycle_no}: " + " · ".join(out)


async def ingest_toto(con: sqlite3.Connection, progress: Progress) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {}
    fetched_at = _iso(now)
    async with PoliteClient() as client:
        cfg = await src.fetch_pool_config(client)
        week = await src.fetch_open_week(client)
        pending = [r["cycle_no"] for r in con.execute(
            "SELECT cycle_no FROM toto_weeks WHERE status='open' AND payin_end_utc < ?", (_iso(now),))]
        results = {c: await src.fetch_result(client, c) for c in pending}
        with db.tx(con):
            if cfg is not None:
                db.meta_set(con, "toto_pool", {**cfg, "fetched_at": fetched_at})
            if week is not None:
                _store_week(con, week, fetched_at)
            for c, res in results.items():
                if res is None or res.dividends is None or any(e.winner is None for e in res.events):
                    continue
                _store_week(con, res, fetched_at)
                con.execute("UPDATE toto_weeks SET dividends=?, status='settled' WHERE cycle_no=?",
                            (json.dumps(res.dividends, ensure_ascii=False), c))
        if week is not None:
            out["matched"] = match_events(con, week.cycle_no)
        # Kalabalık (oynanma oranları) + N/havuz tahmini için son haftaların resmi sonuçları: hata Kupon 1'i durdurmaz
        try:
            from .sportoto_crowd import refresh_crowd  # geç içe aktarma: sportoto_crowd bu modülü kullanır

            out["crowd"] = await refresh_crowd(con, client, week.cycle_no if week is not None else None, progress)
        except Exception as e:  # noqa: BLE001 - resmi olmayan kaynak; kupon yine kurulur (Kupon 2/3 nedeniyle birlikte)
            log.exception("Kalabalık verisi alınamadı")
            out["crowd"] = f"hata: {type(e).__name__}: {e}"
            progress(f"UYARI: Spor Toto kalabalık verisi alınamadı ({type(e).__name__}: {e})")
    if week is not None:
        with db.tx(con):
            out["coupon"] = update_coupon(con, week.cycle_no)
        out["week"] = week.cycle_no
    # Açık hafta kapanmış ama sonuç bekleyen kuponlar kilitlenir
    with db.tx(con):
        for r in con.execute("SELECT DISTINCT cycle_no FROM toto_coupon_sets WHERE locked=0").fetchall():
            if week is None or r["cycle_no"] != week.cycle_no:
                update_coupon(con, r["cycle_no"])
        out["settled"] = [s for c in results if (s := settle_coupon(con, c))]
    progress(f"Spor Toto: {out}")
    return out


# ---------------------------------------------------------------- görünüm

_NO_COUPON = "Program alındı ama kupon kurulamadı: kapanış geçmişti ya da güncelleme o saatte çalışmadı."
_NO_CROWD_LEGACY = "Bu hafta için kalabalık kuponu yok (kupon, üç kupon düzeninden önce kurulmuştu)."


def toto_view(con: sqlite3.Connection) -> dict[str, Any]:
    pool = _pool(con)
    w = con.execute("SELECT * FROM toto_weeks ORDER BY cycle_no DESC LIMIT 1").fetchone()
    week = dict(w) if w else None
    slots: list[dict[str, Any]] = []
    crowd: dict[str, Any] | None = None
    if w is not None and week is not None:
        week["dividends"] = json.loads(week["dividends"]) if week["dividends"] else None
        rows = {r["kind"]: r for r in con.execute("SELECT * FROM toto_coupon_sets WHERE cycle_no=?", (w["cycle_no"],))}
        res = {e["event_no"]: e for e in con.execute(
            "SELECT event_no, result, winner FROM toto_events WHERE cycle_no=?", (w["cycle_no"],))}
        base_payload = json.loads(rows["olasilik"]["payload"]) if "olasilik" in rows else None
        crowd_status = (base_payload or {}).get("crowd_status")
        for kind in KINDS:
            title, desc = KIND_INFO[kind]
            r = rows.get(kind)
            coupon = None
            reason = None
            if r is not None:
                coupon = {**json.loads(r["payload"]), "locked": bool(r["locked"]), "updated_at": r["updated_at"],
                          "status": r["status"], "hits": r["hits"], "prize": r["prize"],
                          "winning_columns": json.loads(r["winning_columns"]) if r["winning_columns"] else None}
                coupon.setdefault("kind", kind)
                coupon.setdefault("title", title)
                coupon.setdefault("description", desc)
                coupon.setdefault("expected_prize", r["expected_prize"])
                for ev in coupon["events"]:
                    x = res.get(ev["event_no"])
                    ev["result"], ev["winner"] = (x["result"], x["winner"]) if x else (None, None)
                    ev.setdefault("crowd", None)
            elif kind == "olasilik" or base_payload is None:
                reason = _NO_COUPON
            else:
                reason = (crowd_status or {}).get("reason") or _NO_CROWD_LEGACY
            slots.append({"kind": kind, "title": title, "description": desc, "coupon": coupon, "reason": reason})
        crows = con.execute("SELECT * FROM toto_crowd WHERE cycle_no=? ORDER BY event_no", (w["cycle_no"],)).fetchall()
        cw = con.execute("SELECT * FROM toto_crowd_weeks WHERE cycle_no=?", (w["cycle_no"],)).fetchone()
        crowd = {
            "available": len(crows) == 15,
            "reason": None if len(crows) == 15 else (crowd_status or {}).get("reason")
            or "Bu hafta için kalabalık (oynanma oranı) verisi yok.",
            "fetched_at": max((r["fetched_at"] for r in crows), default=None),
            "tk_name": cw["tk_name"] if cw else None, "source": "totokazan.com (resmi değil)",
            "events": [{"event_no": r["event_no"], "1": r["p1"], "0": r["px"], "2": r["p2"]} for r in crows],
        }
    hist_rows = {r["kind"]: r for r in con.execute(
        """SELECT kind, COUNT(*) n, AVG(hits) avg_hits, MAX(hits) best, SUM(cost) cost, SUM(prize) prize
           FROM toto_coupon_sets WHERE status='settled' GROUP BY kind""")}
    by_kind = {k: {"settled": h["n"] if h else 0, "avg_hits": h["avg_hits"] if h else None, "best_hits": h["best"] if h else None,
                   "total_cost": (h["cost"] or 0.0) if h else 0.0, "total_prize": (h["prize"] or 0.0) if h else 0.0}
               for k in KINDS for h in [hist_rows.get(k)]}
    return {
        "week": week, "coupons": slots, "crowd": crowd,
        "weekly_cost": sum(s["coupon"]["cost"] for s in slots if s["coupon"] is not None),
        "pool": {"column_price": pool["column_price"], "max_column": pool["max_column"], "source": pool["source"],
                 "budget": TOTO_BUDGET_TL, "weekly_budget": TOTO_BUDGET_TL * len(KINDS)},
        "history": {"by_kind": by_kind, "total_cost": sum(v["total_cost"] for v in by_kind.values()),
                    "total_prize": sum(v["total_prize"] for v in by_kind.values())},
        "generated_at": _iso(datetime.now(timezone.utc)),
    }
