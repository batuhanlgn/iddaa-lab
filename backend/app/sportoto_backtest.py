"""Spor Toto kupon mantığının geçmiş haftalarda sınanması (walk-forward, geleceği görmeden).

Her hafta için model, kuponun kilitlendiği andan (kapanış − TOTO_LOCK_MINUTES) önce sonucu bilinen maçlarla yeniden
eğitilir; toto maçları ESPN maçlarıyla eşleştirilir (sportoto._best_match), olasılıklar canlıdaki öncelik sırasıyla
(harman > model > piyasa > eşit) üretilir ve kupon canlıdaki optimize() ile kurulur. iddaa'nın geçmiş oranı olmadığı
için "piyasa" football-data kapanış oranıdır (MS + 2.5 Alt/Üst, scout_backtest ile aynı eşleştirme).

Kolon sayısı bugünkü bütçe/kolon bedeliyle sabittir (3000 TL / 10 TL = 300 kolon); geçmiş haftada aynı kolon sayısı o
haftanın kolon bedeliyle oynanmış sayılır. İkramiye: kademe başına kazanan kolon × (o kademenin havuzu, bizim
kolonlarımızla paylaşılmış). Kıyas: yalnız piyasa, yalnız model ve rastgele sıralama (aynı kolon sayısı, aynı optimize).

Kolon bedeli geçmişi resmi bir arşivden alınamadı: COLUMN_PRICE_SCHEDULE kaynaklarıyla birlikte elle tutulur;
iddaa appconfig (her indirmede açık haftaya yazılır) ve totokazan hafta listesi bunu doğrular, çelişen hafta dışlanır.
"""
from __future__ import annotations

import json
import logging
import math
import random
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Protocol

from . import db
from .config import TOTO_BUDGET_TL, TOTO_DEFAULT_MAX_COLUMN, TOTO_LOCK_MINUTES
from .model import markets as mk
from .model.pipeline import fit_all, load_params, predict_match
from .scout_backtest import _fd_index, _find_fd, _market_rows
from .sources import footballdata as fd
from .sources import sportoto as src
from .sources.http import FetchError, PoliteClient
from .sportoto import OUTCOMES, TIERS, _best_match, _pool, hit_distribution, optimize, split_event_name, winning_columns

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

SCHEMA_SQL = """
-- Spor Toto geçmişi (backtest): biten hafta bir kez indirilir; havuz = kademenin dağıtılan toplamı (devirde devreden)
CREATE TABLE IF NOT EXISTS toto_hist_weeks (
    cycle_no INTEGER PRIMARY KEY,
    program_name TEXT,
    payin_begin_utc TEXT,
    payin_end_utc TEXT,
    dividends TEXT,                   -- JSON [{tier, winners, amount, pool, pool_known}]
    status TEXT NOT NULL,             -- settled | missing (API'de bülten yok)
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS toto_hist_events (
    cycle_no INTEGER NOT NULL,
    event_no INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    competition TEXT,
    kickoff_utc TEXT,
    result TEXT,
    winner TEXT,                      -- 1 | 0 | 2 (90 dakika)
    PRIMARY KEY (cycle_no, event_no)
);
-- Kolon bedeli gözlemleri (kaynak başına): iddaa_appconfig (açık haftada okunan) | totokazan
CREATE TABLE IF NOT EXISTS toto_hist_prices (
    cycle_no INTEGER NOT NULL,
    source TEXT NOT NULL,
    price REAL NOT NULL,
    note TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (cycle_no, source)
);
"""

DATE_FILTER_URL = f"{src.SPORTOTO_BASE}/SporToto/dateFilter"
TOTOKAZAN_WEEKS_URL = "https://totokazan.com/api/weeks/"

# Kolon bedeli tarifesi: (ilk hafta, son hafta | None = bugüne dek, TL, kaynak). Aralık dışı hafta = bilinmiyor.
# 10 TL: "23 Mart 2025'te açılacak 34. Hafta programı itibarıyla 10 TL" (forum alıntısı, arama özeti; resmi duyuru
#   bulunamadı) — 34. hafta = döngü 281 (payinBegin 2025-03-23 21:30; 2024/25 19. haftası = döngü 266, 18.414.489 TL
#   devir haberiyle doğrulandı); şikayetvar 18-26 Mart 2025 "4 liradan 10 liraya"; iddaa appconfig bugün 10;
#   totokazan 2026 Mart sonrası haftalar 10.00.
# 4 TL: şikayetvar 2 Ağu 2024 "2 TL kolon bedelinin %100 zamla 4 TL'ye çıkartılması" ve Mart 2025 "4 liradan".
#   Yürürlük haftası doğrulanamadı (247 ya da 248) -> 249'dan başlatıldı.
# 2 TL (6 Ağu 2023 = döngü 195'ten, resmi duyuru haberleri) bitişi doğrulanamadığı için tarifede yok.
COLUMN_PRICE_SCHEDULE: tuple[tuple[int, int | None, float, str], ...] = (
    (249, 280, 4.0, "şikayetvar 02.08.2024 (2→4 TL) ve 03.2025 (4→10 TL) kullanıcı kayıtları; resmi duyuru yok"),
    (281, None, 10.0, "34. hafta (23.03.2025) itibarıyla 10 TL; şikayetvar 03.2025; iddaa appconfig; totokazan"),
)
TRAIN_DAYS = 120              # yerel veritabanının ilk bu kadar günü yalnız eğitim içindir (pencere sonra başlar)
MISSING_AFTER_DAYS = 14       # kapanışından bu kadar sonra hâlâ bülteni olmayan hafta "missing" işaretlenir
N_RANDOM = 200                # rastgele strateji tekrar sayısı
RANDOM_SEED = 20261016
_CARRY_TIER = {"1": 15, "2": 14, "3": 13, "4": 12}   # nextDrawExpectedWins.winClass -> kademe
_TK_MATCH_BEFORE = timedelta(days=2)                 # totokazan haftası satış açılmadan en çok bu kadar önce açılır
# football-data takım adı -> ESPN adı (benzerlikle eşleşmeyenler; canlıda iddaa oranı bu maçlarda da vardır)
WELL_COVERED_MAX_NO_DATA = 3  # "veri yok" maç sayısı en çok bu kadar olan hafta kapsamlı sayılır
_COVER_BINS = (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001)
STRATEGIES = ("canli", "piyasa", "model")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class JsonGetter(Protocol):
    def get_json(self, url: str, params: dict[str, str] | None = None) -> Awaitable[Any]: ...


# ---------------------------------------------------------------- kolon bedeli

def scheduled_price(cycle_no: int) -> tuple[float, str] | None:
    for lo, hi, price, source in COLUMN_PRICE_SCHEDULE:
        if cycle_no >= lo and (hi is None or cycle_no <= hi):
            return price, source
    return None


def column_price(cycle_no: int, observed: dict[str, float]) -> tuple[float | None, str]:
    """Haftanın kolon bedeli ve dayanağı. appconfig gözlemi kesindir; yoksa tarife, başka gözlem tarifeyle çelişirse
    hafta dışlanır (None)."""
    if "iddaa_appconfig" in observed:
        return observed["iddaa_appconfig"], "iddaa_appconfig"
    sched = scheduled_price(cycle_no)
    if sched is None:
        return None, "bilinmiyor"
    price, _ = sched
    clash = {k: v for k, v in observed.items() if abs(v - price) > 1e-9}
    if clash:
        return None, "çelişki: " + ", ".join(f"{k}={v:g}" for k, v in sorted(clash.items()))
    return price, "tarife" + "".join(f"+{k}" for k in sorted(observed))


def tier_pools(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Sonuç yükünden kademe havuzları. Kazanan yoksa havuz = ilan edilen tutar, o da 0 ise devreden tutar
    (nextDrawExpectedWins); bilinmiyorsa pool_known=False."""
    d = payload.get("data") or {}
    if not d.get("dividends"):
        return None
    carry = {_CARRY_TIER[str(x.get("winClass"))]: float(x.get("amount") or 0.0)
             for x in d.get("nextDrawExpectedWins") or [] if str(x.get("winClass")) in _CARRY_TIER}
    out = []
    for x in d["dividends"]:
        tier = src._TIER_BY_ORDINAL.get(int(x.get("ordinalNumber", 0)))
        if tier is None:
            continue
        winners = int(src.tr_number(x.get("winners")) or 0)
        amount = src.tr_number(x.get("amount")) or 0.0
        pool = winners * amount if winners > 0 else (amount if amount > 0 else carry.get(tier, 0.0))
        out.append({"tier": tier, "winners": winners, "amount": amount, "pool": pool, "pool_known": pool > 0})
    return out


def coupon_prize(won: dict[int, int], pools: list[dict[str, Any]]) -> tuple[float, bool]:
    """Kazanan kolonlarımızın ikramiyesi: kademe havuzu (resmi kazananlar + bizim kolonlarımız) arasında paylaşılır.
    İkinci değer: kazandığımız bir kademenin havuzu bilinmiyor muydu."""
    by_tier = {p["tier"]: p for p in pools}
    total, unknown = 0.0, False
    for tier, n in won.items():
        p = by_tier.get(tier)
        if n <= 0:
            continue
        if p is None or not p["pool_known"]:
            unknown = True
            continue
        total += p["pool"] * n / (p["winners"] + n)
    return total, unknown


# ---------------------------------------------------------------- indirme

def _store_hist_week(con: sqlite3.Connection, w: src.TotoWeek, pools: list[dict[str, Any]], fetched_at: str) -> None:
    con.execute(
        """INSERT INTO toto_hist_weeks(cycle_no, program_name, payin_begin_utc, payin_end_utc, dividends, status, fetched_at)
           VALUES(?,?,?,?,?,'settled',?) ON CONFLICT(cycle_no) DO UPDATE SET program_name=excluded.program_name,
           payin_begin_utc=excluded.payin_begin_utc, payin_end_utc=excluded.payin_end_utc, dividends=excluded.dividends,
           status='settled', fetched_at=excluded.fetched_at""",
        (w.cycle_no, w.program_name, w.payin_begin_utc, w.payin_end_utc, json.dumps(pools, ensure_ascii=False), fetched_at),
    )
    for e in w.events:
        con.execute(
            """INSERT OR REPLACE INTO toto_hist_events(cycle_no, event_no, event_name, competition, kickoff_utc, result, winner)
               VALUES(?,?,?,?,?,?,?)""",
            (w.cycle_no, e.event_no, e.event_name, e.competition, e.kickoff_utc, e.result, e.winner),
        )


def map_totokazan(items: list[dict[str, Any]], weeks: list[tuple[int, str | None, str]]) -> dict[int, float]:
    """totokazan haftaları -> döngü no: oluşturulma zamanı (TR yerel) satış penceresine [açılış − 2 gün, kapanış]
    düşen tek hafta. weeks: (cycle_no, payin_begin_utc, payin_end_utc)."""
    out: dict[int, float] = {}
    for it in items:
        ts = src.tr_to_utc_iso(str(it.get("created_at") or "").replace(" ", "T"))
        try:
            price = float(it["column_price"])  # "10.00": noktalı ondalık (Türkçe biçim değil)
        except (KeyError, TypeError, ValueError):
            continue
        if ts is None:
            continue
        t = _dt(ts)
        hits = [c for c, b, e in weeks if b and _dt(b) - _TK_MATCH_BEFORE <= t <= _dt(e)]
        if len(hits) == 1:
            out[hits[0]] = price
    return out


async def fetch_toto_history(con: sqlite3.Connection, progress: Progress, *, since: str | None = None,
                             client: JsonGetter | None = None) -> dict[str, Any]:
    """Geçmiş Spor Toto haftalarını (15 maç + sonuç + ikramiye havuzları) ve kolon bedeli gözlemlerini indirir.
    since ("YYYY-MM-DD"): bu tarihten sonra kapanan haftalar; verilmezse yerel maç verisinin başlangıcından 7 gün önce.
    Biten (settled/missing) haftalar yeniden istenmez. client: get_json'lı nesne (test/ham kayıt için)."""
    con.executescript(SCHEMA_SQL)
    if since is None:
        r = con.execute("SELECT MIN(date_utc) d FROM matches WHERE completed=1").fetchone()
        since = (_dt(r["d"]) - timedelta(days=7)).strftime("%Y-%m-%d") if r and r["d"] else "2000-01-01"
    now = datetime.now(timezone.utc)
    fetched_at = _iso(now)
    own = client is None
    cl: Any = client or PoliteClient()
    stats: Counter[str] = Counter()
    try:
        dfl = await cl.get_json(DATE_FILTER_URL)
        cycles = sorted({int(x["gameCycleNo"]): x.get("payinEndDate") for x in (dfl or {}).get("data") or []}.items())
        done = {r["cycle_no"] for r in con.execute("SELECT cycle_no FROM toto_hist_weeks WHERE status IN ('settled','missing')")}
        # dateFilter tarihleri hafta sonuçlarındakiyle bire bir değil (±1 hafta); süzgeç için bir hafta pay bırakılır
        todo = [c for c, end in cycles if c not in done and (src.tr_to_utc_iso(end) or "9999") >= since]
        progress(f"Toto geçmişi: {len(cycles)} hafta listede, {len(todo)} indirilecek ({since} sonrası)")
        for i, c in enumerate(todo):
            try:
                payload = await cl.get_json(f"{src.SPORTOTO_BASE}/SporToto/result", {"gameCycleNo": str(c)})
            except FetchError as e:
                if e.status not in (400, 404):
                    raise
                payload = {}
            w = src.parse_week(payload or {})
            pools = tier_pools(payload or {}) if w is not None else None
            with db.tx(con):
                if w is not None and pools is not None and all(e.winner for e in w.events):
                    _store_hist_week(con, w, pools, fetched_at)
                    stats["settled"] += 1
                else:
                    end = src.tr_to_utc_iso(dict(cycles).get(c))
                    if end is not None and _dt(end) < now - timedelta(days=MISSING_AFTER_DAYS):
                        con.execute(
                            """INSERT INTO toto_hist_weeks(cycle_no, status, fetched_at) VALUES(?, 'missing', ?)
                               ON CONFLICT(cycle_no) DO UPDATE SET status='missing', fetched_at=excluded.fetched_at""",
                            (c, fetched_at))
                        stats["missing"] += 1
                    else:
                        stats["pending"] += 1
            if (i + 1) % 25 == 0:
                progress(f"Toto geçmişi: {i + 1}/{len(todo)} hafta")
        # Kolon bedeli: canlı ayar açık haftaya yazılır (zamanla gerçek geçmiş birikir); totokazan doğrulama içindir
        cfg_raw = await cl.get_json(src.APPCONFIG_URL)
        pool = (((cfg_raw or {}).get("data") or {}).get("globalConfig") or {}).get("soccerPool") or {}
        open_week = src.parse_week(await cl.get_json(f"{src.SPORTOTO_BASE}/SporToto") or {})
        with db.tx(con):
            if pool.get("columnPrice") and open_week is not None:
                con.execute("INSERT OR REPLACE INTO toto_hist_prices VALUES(?, 'iddaa_appconfig', ?, ?, ?)",
                            (open_week.cycle_no, float(pool["columnPrice"]), "contentv2 appconfig soccerPool.columnPrice",
                             fetched_at))
                stats["price_appconfig"] += 1
        try:
            tk = await cl.get_json(TOTOKAZAN_WEEKS_URL)
            items = ((tk or {}).get("data") or {}).get("items") or []
        except FetchError as e:
            log.warning("totokazan hafta listesi alınamadı: %s", e)
            progress(f"Toto geçmişi: totokazan alınamadı ({e.status})")
            items = []
        weeks = [(r["cycle_no"], r["payin_begin_utc"], r["payin_end_utc"]) for r in con.execute(
            "SELECT cycle_no, payin_begin_utc, payin_end_utc FROM toto_hist_weeks WHERE status='settled'")]
        if open_week is not None:
            weeks.append((open_week.cycle_no, open_week.payin_begin_utc, open_week.payin_end_utc))
        mapped = map_totokazan(items, weeks)
        with db.tx(con):
            for c, price in mapped.items():
                con.execute("INSERT OR REPLACE INTO toto_hist_prices VALUES(?, 'totokazan', ?, ?, ?)",
                            (c, price, "totokazan.com/api/weeks column_price (resmi değil)", fetched_at))
        stats["price_totokazan"] = len(mapped)
    finally:
        if own:
            await cl.__aexit__(None, None, None)
    out = {**stats, "requests": getattr(cl, "requests", None)}
    progress(f"Toto geçmişi: {out}")
    return out


# ---------------------------------------------------------------- olasılıklar

def live_probs(p: dict[str, Any] | None, market_q: dict[str, float] | None) -> dict[str, Any]:
    """sportoto.event_probs ile aynı öncelik: harman (model + piyasa) > model > piyasa (marjsız) > eşit.
    Canlıdaki iddaa oranının yerine market_q (football-data kapanışı, marjsız) geçer."""
    out: dict[str, Any] = {"source": "yok", "probs": {o: 1 / 3 for o in OUTCOMES}, "model": None, "market": None}
    if p is not None and p.get("covered"):
        ms_model = next((m for m in p.get("markets") or [] if m["key"] == "ms"), None)
        if ms_model:
            out["model"] = {o["name"]: o["p_model"] for o in ms_model["outcomes"]}
        ms_iddaa = next((m for m in (p.get("iddaa") or {}).get("markets") or [] if m["key"] == "ms"), None)
        if ms_iddaa:
            outs = {o["name"]: o for o in ms_iddaa["outcomes"]}
            if all(k in outs for k in OUTCOMES):
                out["market"] = {k: outs[k]["p_market"] for k in OUTCOMES}
                if all(outs[k].get("p_blend") is not None for k in OUTCOMES):
                    s = sum(outs[k]["p_blend"] for k in OUTCOMES)
                    out.update(source="harman", probs={k: outs[k]["p_blend"] / s for k in OUTCOMES})
                    return out
        if out["model"] and all(k in out["model"] for k in OUTCOMES):
            out.update(source="model", probs=dict(out["model"]))
            return out
    if market_q is not None:
        out.update(source="piyasa", probs=dict(market_q), market=dict(market_q))
    return out


def _uniform() -> dict[str, float]:
    return {o: 1 / 3 for o in OUTCOMES}


# ---------------------------------------------------------------- değerlendirme

def settle(picks: list[list[str]], winners: list[str], pools: list[dict[str, Any]], columns_price: float) -> dict[str, Any]:
    cols = math.prod(len(s) for s in picks)
    won = winning_columns(picks, winners)
    prize, unknown = coupon_prize(won, pools)
    return {"hits": sum(1 for s, w in zip(picks, winners) if w in s), "columns": cols, "cost": cols * columns_price,
            "winning_columns": {str(k): v for k, v in won.items()}, "prize": prize, "pool_unknown": unknown}


def summarize(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    """weeks: [{hits, cost, prize, pool_unknown}] -> strateji özeti."""
    n = len(weeks)
    if n == 0:
        return {"n_weeks": 0}
    cost = sum(w["cost"] for w in weeks)
    prize = sum(w["prize"] for w in weeks)
    hits = [w["hits"] for w in weeks]
    dist = Counter(hits)
    return {
        "n_weeks": n, "cost": cost, "prize": prize, "net": prize - cost, "roi": prize / cost - 1.0 if cost else None,
        "avg_hits": sum(hits) / n, "median_hits": statistics.median(hits),
        "weeks_12plus": sum(h >= 12 for h in hits), "weeks_13plus": sum(h >= 13 for h in hits),
        "weeks_14plus": sum(h >= 14 for h in hits), "weeks_15": sum(h >= 15 for h in hits),
        "prize_weeks": sum(w["prize"] > 0 for w in weeks), "max_prize": max(w["prize"] for w in weeks),
        "hit_distribution": {str(k): dist[k] for k in sorted(dist)},
        "pool_unknown_weeks": sum(bool(w.get("pool_unknown")) for w in weeks),
    }


def _cover_bins(rows: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in zip(_COVER_BINS, _COVER_BINS[1:]):
        sel = [(c, h) for c, h in rows if lo <= c < hi]
        if sel:
            out.append({"lo": lo, "hi": min(hi, 1.0), "n": len(sel), "pred": sum(c for c, _ in sel) / len(sel),
                        "obs": sum(h for _, h in sel) / len(sel)})
    return out


def _prob_scores(rows: list[tuple[dict[str, float], str]]) -> dict[str, Any]:
    """Olasılık doğruluğu: log kaybı, Brier, en olası sonucun ortalama olasılığı ve tutma oranı."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    ll = br = top_p = top_hit = 0.0
    for p, w in rows:
        ll -= math.log(max(p[w], 1e-12))
        br += sum((p[o] - (o == w)) ** 2 for o in OUTCOMES)
        top = max(OUTCOMES, key=lambda o: p[o])
        top_p += p[top]
        top_hit += top == w
    return {"n": n, "logloss": ll / n, "brier": br / n, "top_pred": top_p / n, "top_hit": top_hit / n}


def calibration(weeks: list[dict[str, Any]]) -> dict[str, Any]:
    """Canlı mantık: işaretli sonuçların kapsama olasılığı vs gerçekleşen; kaynak başına olasılık doğruluğu;
    aynı maçlarda model / piyasa / harman karşılaştırması; ≥k isabet olasılığı vs gerçekleşen."""
    cover_rows: list[tuple[float, bool]] = []
    by_src: dict[str, list[tuple[dict[str, float], str]]] = defaultdict(list)
    both: dict[str, list[tuple[dict[str, float], str]]] = defaultdict(list)
    for w in weeks:
        for e in w["events"]:
            cover_rows.append((e["cover"], e["winner"] in e["picks"]))
            by_src[e["source"]].append((e["probs"], e["winner"]))
            if e.get("model") and e.get("market"):
                both["model"].append((e["model"], e["winner"]))
                both["piyasa"].append((e["market"], e["winner"]))
                if e["source"] == "harman":
                    both["harman"].append((e["probs"], e["winner"]))
    n = len(weeks)
    p_at = {str(k): sum(w["p_at_least"].get(str(k), 0.0) for w in weeks) for k in TIERS}
    obs_at = {str(k): sum(w["hits"] >= k for w in weeks) for k in TIERS}
    return {
        "expected_hits": sum(w["expected_hits"] for w in weeks) / n if n else None,
        "actual_hits": sum(w["hits"] for w in weeks) / n if n else None,
        "cover_bins": _cover_bins(cover_rows),
        "by_source": {k: _prob_scores(v) for k, v in by_src.items()},
        "same_matches": {k: _prob_scores(v) for k, v in both.items()},
        "p_at_least_expected_weeks": p_at, "p_at_least_observed_weeks": obs_at,
    }


def _fd_alias(r: sqlite3.Row) -> sqlite3.Row | dict[str, Any]:
    if r["home"] in fd.TEAM_ALIASES or r["away"] in fd.TEAM_ALIASES:
        d = dict(r)
        d["home"], d["away"] = fd.canonical_team(d["home"]), fd.canonical_team(d["away"])
        return d
    return r


def _week_out(w: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in w.items() if k != "_inputs"}


def run_toto_backtest(con: sqlite3.Connection, progress: Progress, *, n_random: int = N_RANDOM,
                      seed: int = RANDOM_SEED, train_days: int = TRAIN_DAYS) -> dict[str, Any]:
    con.executescript(SCHEMA_SQL)
    pool = _pool(con)
    max_cols = min(int(TOTO_BUDGET_TL // pool["column_price"]), int(pool.get("max_column", TOTO_DEFAULT_MAX_COLUMN)))
    r = con.execute("SELECT MIN(date_utc) lo, MAX(date_utc) hi FROM matches WHERE completed=1").fetchone()
    if r is None or r["lo"] is None:
        raise RuntimeError("Toto backtest: yerel veritabanında sonuçlanmış maç yok")
    start = _dt(r["lo"]) + timedelta(days=train_days)
    data_end = r["hi"]
    weeks_rows = con.execute(
        "SELECT * FROM toto_hist_weeks WHERE status='settled' AND payin_end_utc >= ? ORDER BY cycle_no", (_iso(start),)
    ).fetchall()
    if not weeks_rows:
        raise RuntimeError("Toto backtest: pencerede indirilmiş hafta yok (önce fetch_toto_history)")
    observed: dict[int, dict[str, float]] = defaultdict(dict)
    for pr in con.execute("SELECT cycle_no, source, price FROM toto_hist_prices"):
        observed[pr["cycle_no"]][pr["source"]] = float(pr["price"])
    missing = [x["cycle_no"] for x in con.execute(
        "SELECT cycle_no FROM toto_hist_weeks WHERE status='missing' AND cycle_no BETWEEN ? AND ?",
        (weeks_rows[0]["cycle_no"], weeks_rows[-1]["cycle_no"]))]
    params = load_params(con)
    lo_all = min(w["payin_end_utc"] for w in weeks_rows)
    fd_idx = {k: [_fd_alias(x) for x in v] for k, v in _fd_index(
        con, _iso(_dt(lo_all) - timedelta(days=3)), _iso(datetime.now(timezone.utc) + timedelta(days=10))).items()}
    progress(f"Toto backtest: {len(weeks_rows)} hafta ({weeks_rows[0]['cycle_no']}–{weeks_rows[-1]['cycle_no']}), "
             f"{max_cols} kolon")

    have = {w["cycle_no"] for w in weeks_rows} | set(missing)
    gaps = [c for c in range(weeks_rows[0]["cycle_no"], weeks_rows[-1]["cycle_no"] + 1) if c not in have]
    excluded: list[dict[str, Any]] = [{"cycle_no": c, "reason": "API'de bülten yok"} for c in missing]
    excluded += [{"cycle_no": c, "reason": "hafta listesinde ve API'de yok"} for c in gaps]
    weeks: list[dict[str, Any]] = []
    cov: Counter[str] = Counter()
    comp_cov: dict[str, Counter[str]] = defaultdict(Counter)
    for wr in weeks_rows:
        c = wr["cycle_no"]
        evs = con.execute("SELECT * FROM toto_hist_events WHERE cycle_no=? ORDER BY event_no", (c,)).fetchall()
        kos = [e["kickoff_utc"] for e in evs if e["kickoff_utc"]]
        if len(evs) != 15 or any(not e["winner"] for e in evs):
            excluded.append({"cycle_no": c, "reason": "15 maç/sonuç eksik"})
            continue
        if max(kos) > data_end:
            excluded.append({"cycle_no": c, "reason": "yerel maç verisi haftanın sonuna ulaşmıyor"})
            continue
        price, basis = column_price(c, observed.get(c, {}))
        if price is None:
            excluded.append({"cycle_no": c, "reason": f"kolon bedeli {basis}"})
            continue
        as_of = _dt(wr["payin_end_utc"]) - timedelta(minutes=TOTO_LOCK_MINUTES)
        fm = fit_all(con, as_of=as_of, params=params, with_aux=False)
        lo = _iso(_dt(min(kos)) - timedelta(hours=3))
        hi = _iso(_dt(max(kos)) + timedelta(hours=3))
        espn_rows = con.execute(
            """SELECT m.*, th.name hn, ta.name an,
                      COALESCE(m.ft90_home, CASE WHEN m.extra_time=0 THEN m.home_goals END) hg,
                      COALESCE(m.ft90_away, CASE WHEN m.extra_time=0 THEN m.away_goals END) ag
               FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
               WHERE m.date_utc BETWEEN ? AND ?""",
            (lo, hi),
        ).fetchall()
        events = []
        for e in evs:
            cands = split_event_name(e["event_name"])
            em, h, a = _best_match(cands, e["kickoff_utc"], espn_rows, "date_utc", "hn", "an")
            fd = _find_fd(em, fd_idx) if em is not None and em["hg"] is not None else None  # type: ignore[arg-type]
            market_q = dict(zip(OUTCOMES, mk.devig([float(fd["o1"]), float(fd["ox"]), float(fd["o2"])]))) if fd else None
            p = None
            agree = None
            if em is not None:
                # Kilit anında resmi ilk 11'ler bilinmez: kadro ayarı devre dışı (player_match'e denk gelmeyen kimlik)
                row = dict(em)
                row["id"] = f"toto-bt:{em['id']}"
                p = predict_match(con, fm, row, with_sim=False,  # type: ignore[arg-type]
                                  market_rows=_market_rows(fd, em["date_utc"]) if fd else None)
                if em["hg"] is not None:
                    agree = ("1" if em["hg"] > em["ag"] else "0" if em["hg"] == em["ag"] else "2") == e["winner"]
            info = live_probs(p, market_q)
            model_p = info["model"] if info["model"] and all(k in info["model"] for k in OUTCOMES) else None
            events.append({
                "event_no": e["event_no"], "event_name": e["event_name"], "competition": e["competition"],
                "kickoff_utc": e["kickoff_utc"], "result": e["result"], "winner": e["winner"],
                "espn_match_id": em["id"] if em is not None else None, "league": em["league"] if em is not None else None,
                "fd": fd is not None, "espn_result_agrees": agree, "source": info["source"], "probs": info["probs"],
                "model": model_p, "market": info["market"],
                "_alt": {"piyasa": market_q or _uniform(), "model": model_p or _uniform()},
            })
            cov[info["source"]] += 1
            cov["espn"] += em is not None
            cov["fd"] += fd is not None
            cov["agree"] += agree is True
            cov["agree_n"] += agree is not None
            cc = comp_cov[e["competition"] or "?"]
            cc["n"] += 1
            cc[info["source"]] += 1
        winners = [e["winner"] for e in events]
        pools = json.loads(wr["dividends"])
        picks = optimize([e["probs"] for e in events], max_cols)
        covers = [sum(e["probs"][o] for o in s) for e, s in zip(events, picks)]
        dist = hit_distribution(covers)
        res = settle(picks, winners, pools, price)
        for e, s, cv in zip(events, picks, covers):
            e["picks"], e["cover"] = s, cv
        strat = {"canli": res}
        for name in ("piyasa", "model"):
            pk = optimize([e["_alt"][name] for e in events], max_cols)
            strat[name] = settle(pk, winners, pools, price)
        weeks.append({
            "cycle_no": c, "program_name": wr["program_name"], "payin_end_utc": wr["payin_end_utc"],
            "column_price": price, "price_basis": basis, **res, "expected_hits": sum(covers),
            "p_at_least": {str(k): sum(dist[k:]) for k in TIERS}, "p15": dist[15],
            "n_by_source": dict(Counter(e["source"] for e in events)),
            "pools": pools, "strategies": strat,
            "events": events,
        })
        progress(f"Toto backtest: hafta {c} · {res['hits']}/15 · ikramiye {res['prize']:.0f} TL · "
                 f"kaynak {dict(Counter(e['source'] for e in events))}")

    # Rastgele sıralama: her maça rastgele (Dirichlet(1,1,1)) olasılık -> aynı optimize; tekrar başına toplamlar
    rng = random.Random(seed)
    rand_runs: list[dict[str, Any]] = []
    rand_week_prize = [0.0] * len(weeks)
    rand_week_hits = [0.0] * len(weeks)
    for _ in range(n_random):
        rows = []
        for i, w in enumerate(weeks):
            probs = []
            for _e in w["events"]:
                g = [-math.log(1.0 - rng.random()) for _o in OUTCOMES]
                s = sum(g)
                probs.append({o: x / s for o, x in zip(OUTCOMES, g)})
            pk = optimize(probs, max_cols)
            st = settle(pk, [e["winner"] for e in w["events"]], w["pools"], w["column_price"])
            rows.append(st)
            rand_week_prize[i] += st["prize"] / n_random
            rand_week_hits[i] += st["hits"] / n_random
        rand_runs.append(summarize(rows))
    for i, w in enumerate(weeks):
        w["strategies"]["rastgele"] = {"hits": rand_week_hits[i], "prize": rand_week_prize[i], "cost": w["cost"]}
        for e in w["events"]:
            e.pop("_alt", None)

    def rand_summary() -> dict[str, Any]:
        if not rand_runs:
            return {"n_weeks": 0}
        keys = ("prize", "roi", "avg_hits", "weeks_12plus", "weeks_13plus", "weeks_14plus", "weeks_15", "prize_weeks")
        out: dict[str, Any] = {"n_weeks": len(weeks), "n_runs": len(rand_runs), "cost": rand_runs[0]["cost"]}
        for k in keys:
            vals = sorted(float(x[k]) for x in rand_runs)
            out[k] = sum(vals) / len(vals)
            out[f"{k}_p05"] = vals[int(0.05 * len(vals))]
            out[f"{k}_p50"] = vals[len(vals) // 2]
            out[f"{k}_p95"] = vals[min(len(vals) - 1, int(0.95 * len(vals)))]
        out["net"] = out["prize"] - out["cost"]
        return out

    strategies: dict[str, Any] = {}
    segments: dict[str, Any] = {}
    prices = sorted({w["column_price"] for w in weeks})
    for name in STRATEGIES:
        rows = [w["strategies"][name] for w in weeks]
        strategies[name] = summarize(rows)
        segments[name] = {f"{p:g} TL": summarize([rw for rw, w in zip(rows, weeks) if w["column_price"] == p])
                          for p in prices}
        well = [w.get("n_by_source", {}).get("yok", 0) <= WELL_COVERED_MAX_NO_DATA for w in weeks]
        segments[name]["kapsamli"] = summarize([rw for rw, ok in zip(rows, well) if ok])
        segments[name]["veri_az"] = summarize([rw for rw, ok in zip(rows, well) if not ok])
    strategies["rastgele"] = rand_summary()
    canli_prize = strategies["canli"].get("prize", 0.0)
    strategies["rastgele"]["share_runs_below_canli"] = (
        sum(x["prize"] < canli_prize for x in rand_runs) / len(rand_runs) if rand_runs else None)
    strategies["rastgele"]["share_runs_no_prize"] = (
        sum(x["prize"] == 0 for x in rand_runs) / len(rand_runs) if rand_runs else None)
    n_ev = sum(1 for w in weeks for _ in w["events"])
    coverage = {
        "n_events": n_ev,
        "share": {k: cov[k] / n_ev for k in ("harman", "model", "piyasa", "yok")} if n_ev else {},
        "counts": {k: cov[k] for k in ("harman", "model", "piyasa", "yok", "espn", "fd")},
        "espn_matched": cov["espn"] / n_ev if n_ev else None,
        "fd_matched": cov["fd"] / n_ev if n_ev else None,
        "espn_result_agreement": cov["agree"] / cov["agree_n"] if cov["agree_n"] else None,
        "by_competition": {k: dict(v) for k, v in sorted(comp_cov.items(), key=lambda x: -x[1]["n"])},
    }
    ranked = sorted(weeks, key=lambda w: (-w["prize"], -w["hits"]))
    result = {
        "created_at": _iso(datetime.now(timezone.utc)),
        "window": {"from_cycle": weeks[0]["cycle_no"] if weeks else None, "to_cycle": weeks[-1]["cycle_no"] if weeks else None,
                   "from": weeks[0]["payin_end_utc"] if weeks else None, "to": weeks[-1]["payin_end_utc"] if weeks else None,
                   "n_weeks": len(weeks), "train_start": r["lo"], "train_days": train_days},
        "budget": TOTO_BUDGET_TL, "price_today": pool["column_price"], "columns": max_cols,
        "price_schedule": [{"from_cycle": lo_, "to_cycle": hi_, "price": p_, "source": s_}
                           for lo_, hi_, p_, s_ in COLUMN_PRICE_SCHEDULE],
        "excluded": excluded, "coverage": coverage, "strategies": strategies, "segments": segments,
        "calibration": calibration(weeks),
        "best_weeks": [{"cycle_no": w["cycle_no"], "program_name": w["program_name"], "hits": w["hits"],
                        "prize": w["prize"], "cost": w["cost"]} for w in ranked[:5]],
        "worst_weeks": [{"cycle_no": w["cycle_no"], "program_name": w["program_name"], "hits": w["hits"],
                         "prize": w["prize"], "cost": w["cost"]} for w in sorted(weeks, key=lambda w: w["hits"])[:5]],
        "weeks": [_week_out(w) for w in weeks],
        "notes": [
            "Model her hafta kupon kilidinden (kapanış − 60 dk) önce sonucu bilinen maçlarla yeniden eğitildi; model "
            "hiperparametreleri ve harman ağırlığı bugünkü ayardır.",
            "Piyasa: football-data kapanış ortalaması (MS + 2.5 Alt/Üst); canlıda kilit anındaki iddaa oranı kullanılır. "
            "Kapanış oranı kilit anından daha bilgilidir (piyasa ve harman lehine hafif iyimserlik).",
            "Resmi ilk 11'e göre kadro ayarı kapalı: kilit anında (ilk maçtan ~65 dk önce) ilk 11'ler açıklanmamıştır.",
            "İkramiye: kademe havuzu resmi kazananlar ile bizim kazanan kolonlarımız arasında paylaştırıldı; bizim "
            "yatırdığımız tutarın havuzu büyütmesi ihmal edildi (300 kolon, haftalık hasılatın binde birinden az).",
            "Kazananı olmayan kademede havuz = ilan edilen tutar ya da devreden tutar (nextDrawExpectedWins); ikisi de "
            "yoksa havuz bilinmiyor sayıldı (pool_unknown).",
            "Kolon bedeli resmi arşivden doğrulanamadı; tarife ve kaynakları price_schedule'da. ESPN'de olmayan ligler "
            "(ör. TFF 1. Lig, milli maçlar) 'veri yok' ile eşit olasılık aldı (canlıdaki gibi).",
        ],
    }
    progress(f"Toto backtest: canlı ROI={strategies['canli'].get('roi')} · piyasa={strategies['piyasa'].get('roi')} · "
             f"model={strategies['model'].get('roi')} · rastgele={strategies['rastgele'].get('roi')}")
    with db.tx(con):
        db.meta_set(con, "toto_backtest", result)
    return result
