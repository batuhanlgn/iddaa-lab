"""Spor Toto kalabalık kuponları: oynanma oranlarına göre beklenen ikramiyeyi en büyüten kupon.

Haftada üç kupon (her biri ≤ bütçe, ≤ kolon sınırı):
  olasilik     sportoto.optimize: 15 bilme olasılığını en büyüten (bugünkü mantık)
  kalabalik    beklenen ikramiyeyi en büyüten: az oynanan ama makul sonuçlar değerlidir (favori tutsa da ikramiye bölünür)
  kalabalik_2  aynı amaç, kalabalik ile ORTAK KOLONU YOK (en az bir maçta işaret kümeleri ayrık)

Kalabalık verisi totokazan.com'dan (resmi değil): maç başı oynanma yüzdesi r_j(o). Hafta, sıra (position = event_no),
takım adı benzerliği (kısaltmalar dahil) ve tarih penceresiyle döngüye eşlenir; biten haftada 15 sonucun hepsi resmi
sonuçla aynı olmalıdır.

Beklenen ikramiye modeli
  * Sonuç y ~ p_ev (maçlar bağımsız), p_ev ∝ p^a · r^(1−a): p bizim olasılığımız (event_probs), r oynanma oranı.
    Tek tek maçlarda p, r'den iyi (log-kayıp 0,994 / 1,027; harman ağırlığı a ≈ 1 en iyi). Ama ortak dağılımda bizim
    model, kalabalığı şaşırtan sonuçları gerçekte olduğundan sık sanıyor: gerçekleşen sonucun PB_12'sinin model
    dağılımındaki yüzdeliği (PIT) 29 haftada ortalama 0,68 (kalibre: 0,5); a = 0,4'te 0,50. a her hafta yalnız önceki
    haftalardan, ortalama PIT'i 0,5'e en yakın değer olarak seçilir (estimate_blend; 6 haftadan az geçmişte 0,5).
    p_ev yalnız beklenen ikramiye ve kalabalık kuponlarının araması içindir; gösterilen olasılıklar ve Kupon 1 p ile.
  * Kalabalığın bir kolonu her maçta bağımsız, r_j ile işaretlenir. y verildiğinde kalabalıkta tam k doğru kolon sayısı
    X_k ~ Poisson(λ_k), λ_k = N · max(PB_k(r(y)), PB_k^min); PB_k: Poisson-binom (q_j = r_j(y_j)) tam k doğru olasılığı.
  * Kazanan kolonumuzun payı Havuz_k · E[1/(1+X_k)] = Havuz_k · (1 − e^{−λ_k}) / λ_k (Poisson). Bu seçildi çünkü 15 ve 14
    kademesinde λ küçük olabilir; 1/(1+λ) eklentisi orada payı belirgin biçimde küçük gösterir. Kendi kazanan kolonlarımızın
    birbiriyle paylaşması ihmal edilir (W_15 ≤ 1; 12–14'te λ yüzler/binler, etkisi yok).
  * Beklenen ikramiye = E_y[ Σ_k W_k(S, y) · A_k(y) ], A_k(y) = Havuz_k · h(λ_k(y)); W_k kupondaki tam k doğru kolon sayısı
    (sportoto.winning_columns polinomu). Önem örneklemeli Monte Carlo (sabit tohum, aynı örnekler tüm adaylarda); arama
    MC_SAMPLES örnekle, bildirilen değer aramadan bağımsız EVAL_SAMPLES örnekle (aynı örneklerle bildirmek seçim yanlılığı
    yüzünden değeri 6–20 kat şişiriyordu).
  * Kuyruk sınırı (PB_k^min): bağımsız kalabalık modeli, şimdiye dek görülenden çok daha sürprizli sonuçlarda neredeyse
    hiç ortak kazanan öngörmez; bunu doğrulayacak veri yoktur. Sınır olmadan Kupon 2'nin beklenen ikramiyesinin çoğu
    haftada ~%100'ü, PB_12'si gerçekleşen en sürprizli haftanınkinden küçük sonuçlardan geliyordu. PB_k^min önceki
    haftalarda gerçekleşen sonuçların en küçük PB_k değeridir (sızıntısız). Gerçekleşen sonuçlarda model ödemesi gerçeğe
    yakındır (etkin N'nin gerçekleşen / tahmin medyanı ≈ 1,2).
  * Değer, her maçın terimine göre doğrusaldır: W(S) polinomundan j. maçın terimi bölünüp (kalan polinom tam sayı; tepeden
    bölme kesin) 7 işaret kümesinin hepsi O(1)'de, iki maçlık takaslar 3×3 sonuç ağırlığıyla hesaplanır.
  * Seçim: arama örneklemine aşırı uyum (tek şanslı örnek) yüzünden adaylar aramadan bağımsız örneklemle seçilir
    (optimize_crowd); yerel arama hamleyi iki bağımsız arama örnekleminde birden değer artıyorsa kabul eder. Kupon 1 de
    adaydır: Kupon 2 bağımsız örneklemde Kupon 1'den kötü olamaz.
  * Backtest (16 Eki 2026, 333–361. haftalar, 26 hafta, run_crowd_backtest): getiri Kupon 1 +%11, Kupon 2 −%9, Kupon 3
    −%16; gerçekleşen / beklenen ikramiye 0,66 / 0,17 / 0,18. Kupon 2 ve 3'ün ikramiyesinin çoğu üç kuponun da 14 bildiği
    tek haftadan (359). En az 12 doğru: beklenen 2,5 / 2,4 hafta, gerçekleşen 4 / 3. Kalabalık kuponlarının beklenen
    ikramiyesi hâlâ iyimser kabul edilmelidir; Kupon 1'i geçtiklerine dair kanıt yok.

N ve havuz tahmini (SIZINTISIZ: yalnız kilit anından önce sonucu belli olmuş önceki haftalar, en çok HISTORY_WEEKS)
  * totokazan'ın "kolonOynatildi" alanı resmi toplam değil (kendi platformu: ~1 milyon; resmi ikramiye fonu ~15–25 milyon
    kolona karşılık gelir). Bu yüzden N "etkin kalabalık kolon" olarak resmi kazanan sayılarından geri çözülür:
    N_t = Σ_k kazanan_k / Σ_k PB_k(r_t(y_t)) (12–15 havuzlanmış oran), N = son haftaların medyanı. Böylece model,
    kalabalığın bağımsızlık varsayımındaki sapmayı ortalamada 12 kademesinde kalibre eder.
  * Havuz_k: önceki haftaların taban havuzlarının medyanı (sportoto_backtest.tier_pools; kolon bedeli farkına göre
    ölçeklenir). Resmi toplam kolon bilinmediği için havuz payı (havuz / (N·bedel)) yerine doğrudan havuz kullanılır.
    15 kademesinin tabanı = havuz − önceki haftadan devreden. Bu haftanın 15 havuzuna, önceki hafta 15 bilen yoksa onun
    15 havuzu (devir) eklenir.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Protocol

import numpy as np

from . import db
from .config import TOTO_LOCK_MINUTES
from .matching import norm, similarity
from .model import markets as mk
from .sources import sportoto as src
from .sources import totokazan as tk
from .sources.http import FetchError
from .sportoto import KIND_INFO, KINDS, OUTCOMES, TIERS, hit_distribution, optimize, split_event_name
from .sportoto_backtest import _store_hist_week, column_price, settle, summarize, tier_pools

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

MC_SAMPLES = 12000            # arama örnekleri (örneklem başına) (sabit tohum + hafta no; tüm adaylarda aynı örnekler)
EVAL_SAMPLES = 60000          # bildirilen beklenen ikramiye: aramadan BAĞIMSIZ örneklerle (seçim yanlılığı olmasın)
MC_SEED = 20261016
EVAL_SEED_OFFSET = 7919
BLEND_GRID = tuple(i / 10 for i in range(11))   # harman ağırlığı a adayları: p^a · r^(1−a)
BLEND_PRIOR = 0.5             # yeterli geçmiş yokken: iki kaynağa eşit ağırlık (geometrik ortalama)
BLEND_MIN_WEEKS = 6
PIT_SAMPLES = 4000
IS_ALPHA = 0.5                # önem örneklemesi: g = (1 − α)·p + α·t, t ∝ p·(p / r)^β (az oynanan sonuçlar sık örneklenir)
IS_BETA = 2.0
HISTORY_WEEKS = 6             # N / havuz tahmininde kullanılan en çok önceki hafta
MIN_HISTORY_WEEKS = 3         # bundan az geçmiş haftayla kalabalık kuponu kurulmaz
BACKFILL_WEEKS = HISTORY_WEEKS + 2   # canlıda resmi sonucu (havuzlarıyla) eksikse indirilen son hafta sayısı
MIN_NAME_MATCHES = 13         # totokazan haftası: 15 sıradan en az bu kadarında takım adları tutmalı
RESULT_GRACE = timedelta(hours=3)    # son maçın başlamasından bu kadar sonra haftanın sonucu belli sayılır
TK_WINDOW_BEFORE = timedelta(days=3)  # totokazan haftasının oluşturulma zamanı: satış açılışından en çok bu kadar önce
TK_WINDOW_AFTER = timedelta(days=1)
UNMATCHED_RETRY = timedelta(hours=24)
K3_SEARCHES = 3               # Kupon 3: başlangıç değeri en iyi bu kadar "ayrık maç" adayı için tam yerel arama
SEARCH_RUNS = 2               # bağımsız arama örneklemi (hamle ikisinde birden değer artırmalı)
SWAP_ROUNDS = 2               # Kupon 3 adayı Kupon 2'yi geçerse yer değiştirme turu
MAX_ITER = 80
MASKS = (1, 2, 4, 3, 5, 6, 7)        # bit i <-> OUTCOMES[i] ("1", "0", "2"); 7 işaret kümesi
_IN = np.array([[(m >> o) & 1 for o in range(3)] for m in MASKS], dtype=np.float64)   # (7, 3) üyelik
_SZ = _IN.sum(1)                                                                        # (7,) küme boyu
_C = np.stack([_IN * (_SZ[:, None] - 1) + (1 - _IN) * _SZ[:, None], _IN], axis=2)      # (7, 3, 2): x^0 / x^1 katsayısı
_MIDX = {m: i for i, m in enumerate(MASKS)}
_TIER_IDX = np.array(TIERS[::-1])    # 12, 13, 14, 15
_LOW = 9                             # tutulan en düşük derece
_TOP = 16 - _LOW                     # tutulan katsayı sayısı (derece 9..15)
_T0 = 12 - _LOW                      # 12 kademesinin sütunu


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def mask_of(sel: list[str]) -> int:
    return sum(1 << OUTCOMES.index(o) for o in sel)


def sel_of(mask: int) -> list[str]:
    return [o for i, o in enumerate(OUTCOMES) if mask >> i & 1]


def _size(mask: int) -> int:
    return bin(mask).count("1")


class JsonGetter(Protocol):
    def get_json(self, url: str, params: dict[str, str] | None = None) -> Awaitable[Any]: ...


# ---------------------------------------------------------------- totokazan haftası <-> döngü eşleştirme

def _abbr_ok(short: str, full: str) -> bool:
    """Kısaltmalı ad ("M. City", "T. Hotspur", "S.P. City") uzun adla uyumlu mu: baş harfler sırayla uzun adın
    kelimelerinin baş harfi, tam kelimeler uzun adın bir kelimesinin başı/parçası olmalı."""
    st, ft = norm(short).split(), norm(full).split()
    if not st or not ft:
        return False
    i = 0
    for t in st:
        if t.endswith(".") and len(t) <= 3:
            while i < len(ft) and not ft[i].startswith(t[0]):
                i += 1
            if i >= len(ft):
                return False
            i += 1
            continue
        j = next((k for k in range(i, len(ft)) if ft[k].startswith(t) or t.startswith(ft[k])
                  or (len(t) >= 4 and t in ft[k]) or similarity(t, ft[k]) >= 0.8), None)
        if j is None:
            return False
        i = j + 1
    return True


def fixture_consistent(event_name: str, fx: tk.TkFixture) -> bool:
    for h, a in split_event_name(event_name):
        sh, sa = similarity(h, fx.home), similarity(a, fx.away)
        if (sh >= 0.62 and sa >= 0.62) or (max(sh, sa) >= 0.9 and min(sh, sa) >= 0.35) or max(sh, sa) >= 0.8:
            return True
        ah, aa = _abbr_ok(fx.home, h), _abbr_ok(fx.away, a)
        if (ah and aa) or (ah and sa >= 0.5) or (aa and sh >= 0.5):
            return True
    return False


@dataclass
class WeekCheck:
    ok: bool
    n_names: int
    reason: str | None


def check_week(tkw: tk.TkWeek, events: list[dict[str, Any]]) -> WeekCheck:
    """totokazan haftası bu döngünün 15 maçıyla tutarlı mı. events: [{event_no, event_name, winner}]."""
    by_no = {int(e["event_no"]): e for e in events}
    positions = [f.position for f in tkw.fixtures]
    if sorted(positions) != list(range(1, 16)) or sorted(by_no) != list(range(1, 16)):
        return WeekCheck(False, 0, "15 maç / sıra eksik")
    if any(f.pct is None for f in tkw.fixtures):
        return WeekCheck(False, 0, "oynanma yüzdesi eksik")
    n = sum(fixture_consistent(str(by_no[f.position]["event_name"]), f) for f in tkw.fixtures)
    if n < MIN_NAME_MATCHES:
        return WeekCheck(False, n, f"takım adları tutmuyor ({n}/15)")
    clash = [f.position for f in tkw.fixtures if f.result and by_no[f.position].get("winner")
             and f.result != by_no[f.position]["winner"]]
    if clash:
        return WeekCheck(False, n, f"sonuçlar resmi sonuçla farklı (sıra {clash})")
    return WeekCheck(True, n, None)


def _cycle_events(con: sqlite3.Connection, cycle_no: int) -> list[dict[str, Any]]:
    rows = con.execute("SELECT event_no, event_name, winner FROM toto_hist_events WHERE cycle_no=? ORDER BY event_no",
                       (cycle_no,)).fetchall()
    if len(rows) != 15:
        rows = con.execute("SELECT event_no, event_name, winner FROM toto_events WHERE cycle_no=? ORDER BY event_no",
                           (cycle_no,)).fetchall()
    return [dict(r) for r in rows]


def _candidates(con: sqlite3.Connection, created_at: str | None) -> list[int]:
    ts = src.tr_to_utc_iso(str(created_at or "").replace(" ", "T")) if created_at else None
    if ts is None:
        return []
    t = _dt(ts)
    out = set()
    for tbl in ("toto_weeks", "toto_hist_weeks"):
        for r in con.execute(f"SELECT cycle_no, payin_begin_utc b, payin_end_utc e FROM {tbl} WHERE payin_end_utc IS NOT NULL"):
            if r["b"] and _dt(r["b"]) - TK_WINDOW_BEFORE <= t <= _dt(r["e"]) + TK_WINDOW_AFTER:
                out.add(int(r["cycle_no"]))
    return sorted(out)


def map_week(con: sqlite3.Connection, tkw: tk.TkWeek, candidates: list[int]) -> tuple[int | None, WeekCheck]:
    """Adaylar içinde tutarlı olan tek döngü (en çok ad eşleşen; eşitlikte belirsiz -> eşleşmez)."""
    oks: list[tuple[int, WeekCheck]] = []
    last = WeekCheck(False, 0, "aday hafta yok (tarih penceresi)")
    for c in candidates:
        chk = check_week(tkw, _cycle_events(con, c))
        if chk.ok:
            oks.append((c, chk))
        elif chk.n_names >= last.n_names:
            last = chk
    if not oks:
        return None, last
    oks.sort(key=lambda x: -x[1].n_names)
    if len(oks) > 1 and oks[0][1].n_names == oks[1][1].n_names:
        return None, WeekCheck(False, oks[0][1].n_names, f"belirsiz eşleşme: {[c for c, _ in oks]}")
    return oks[0]


def _store_crowd(con: sqlite3.Connection, cycle_no: int, tkw: tk.TkWeek, n_names: int, fetched_at: str) -> None:
    for f in tkw.fixtures:
        assert f.pct is not None
        o = f.odds if f.odds and all(v > 1.01 for v in f.odds.values()) else None
        con.execute(
            """INSERT INTO toto_crowd(cycle_no, event_no, p1, px, p2, o1, ox, o2, fetched_at) VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(cycle_no, event_no) DO UPDATE SET p1=excluded.p1, px=excluded.px, p2=excluded.p2,
               o1=excluded.o1, ox=excluded.ox, o2=excluded.o2, fetched_at=excluded.fetched_at""",
            (cycle_no, f.position, f.pct["1"], f.pct["0"], f.pct["2"], o["1"] if o else None, o["0"] if o else None,
             o["2"] if o else None, fetched_at),
        )
    con.execute(
        """INSERT INTO toto_crowd_weeks(cycle_no, tk_week_id, tk_name, status, platform_columns, n_name_matches,
                                        source_fetched_at, fetched_at) VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(cycle_no) DO UPDATE SET tk_week_id=excluded.tk_week_id, tk_name=excluded.tk_name,
             status=excluded.status, platform_columns=excluded.platform_columns, n_name_matches=excluded.n_name_matches,
             source_fetched_at=excluded.source_fetched_at, fetched_at=excluded.fetched_at""",
        (cycle_no, tkw.id, tkw.name, "settled" if tkw.status == "settled" else "open", tkw.platform_columns, n_names,
         tkw.fetched_at, fetched_at),
    )


async def backfill_results(con: sqlite3.Connection, client: JsonGetter, open_cycle: int | None) -> str:
    """Son BACKFILL_WEEKS haftanın resmi sonucu (kademe havuzlarıyla) toto_hist_* tablolarında yoksa indirilir: N/havuz
    tahmini ve totokazan eşleştirmesi bunlara dayanır. Biten hafta bir kez yazılır."""
    if open_cycle is None:
        return "açık hafta yok"
    have = {r["cycle_no"] for r in con.execute("SELECT cycle_no FROM toto_hist_weeks WHERE status IN ('settled','missing')")}
    todo = [c for c in range(open_cycle - BACKFILL_WEEKS, open_cycle) if c not in have]
    fetched_at = _iso(datetime.now(timezone.utc))
    n = 0
    for c in todo:
        try:
            payload = await client.get_json(f"{src.SPORTOTO_BASE}/SporToto/result", {"gameCycleNo": str(c)})
        except FetchError as e:
            if e.status in (400, 404):
                continue
            raise
        w = src.parse_week(payload or {})
        pools = tier_pools(payload or {}) if w is not None else None
        if w is not None and pools is not None and all(e.winner for e in w.events):
            with db.tx(con):
                _store_hist_week(con, w, pools, fetched_at)
            n += 1
    return f"{n}/{len(todo)} hafta sonucu eklendi"


async def ingest_crowd(con: sqlite3.Connection, client: JsonGetter, open_cycle: int | None) -> dict[str, Any]:
    """totokazan: açık hafta her çağrıda (oynanma yüzdesi canlı değişir), biten haftalar bir kez (son yüzdeler)."""
    now = datetime.now(timezone.utc)
    fetched_at = _iso(now)
    items = await tk.fetch_list(client)
    done = {r["tk_week_id"] for r in con.execute("SELECT tk_week_id FROM toto_crowd_weeks WHERE status='settled'")}
    unmatched: dict[str, Any] = db.meta_get(con, "toto_crowd_unmatched") or {}
    stats: Counter[str] = Counter()
    for it in items:
        tid, status = int(it["id"]), str(it.get("status") or "")
        if status not in ("open", "settled") or (status == "settled" and tid in done):
            continue
        um = unmatched.get(str(tid))
        if status == "settled" and um and now - _dt(um["at"]) < UNMATCHED_RETRY:
            stats["skipped_unmatched"] += 1
            continue
        tkw = await tk.fetch_week(client, tid)
        if tkw is None:
            unmatched[str(tid)] = {"reason": "hafta ayrıntısı okunamadı", "at": fetched_at, "name": it.get("name")}
            continue
        cands = ([open_cycle] if open_cycle is not None else []) if status == "open" else _candidates(con, tkw.created_at)
        cycle, chk = map_week(con, tkw, cands)
        if cycle is None:
            unmatched[str(tid)] = {"reason": chk.reason, "at": fetched_at, "name": tkw.name}
            stats["unmatched"] += 1
            continue
        with db.tx(con):
            _store_crowd(con, cycle, tkw, chk.n_names, fetched_at)
        unmatched.pop(str(tid), None)
        stats[status] += 1
    with db.tx(con):
        db.meta_set(con, "toto_crowd_unmatched", unmatched)
    return dict(stats)


async def refresh_crowd(con: sqlite3.Connection, client: JsonGetter, open_cycle: int | None,
                        progress: Progress) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["backfill"] = await backfill_results(con, client, open_cycle)
    except FetchError as e:
        out["backfill"] = f"hata: {e.status}"
        progress(f"UYARI: Spor Toto geçmiş sonuçları alınamadı ({e})")
    out["crowd"] = await ingest_crowd(con, client, open_cycle)
    return out


# ---------------------------------------------------------------- N / havuz tahmini

@dataclass
class Market:
    n_columns: float                     # etkin kalabalık kolon sayısı
    pools: dict[int, float]              # kademe -> tahmini havuz (TL; 15 devir dahil)
    carry: float                         # 15 kademesine önceki haftadan devreden
    basis: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    pb_floor: dict[int, float] = field(default_factory=dict)   # kademe -> PB_k alt sınırı (en sürprizli gerçekleşen hafta)
    floor_weeks: int = 0
    blend_a: float = 1.0                 # beklenen ikramiyede sonuç olasılığı: p^a · r^(1−a) (1 = yalnız bizim olasılık)
    blend_weeks: int = 0

    def to_json(self) -> dict[str, Any]:
        return {"n_columns": self.n_columns, "pools": {str(k): v for k, v in self.pools.items()}, "carry": self.carry,
                "n_weeks": len(self.basis), "basis": self.basis, "notes": self.notes,
                "pb_floor": {str(k): v for k, v in self.pb_floor.items()}, "floor_weeks": self.floor_weeks,
                "blend_a": self.blend_a, "blend_weeks": self.blend_weeks}


def crowd_probs(con: sqlite3.Connection, cycle_no: int) -> tuple[list[dict[str, float]] | None, str | None]:
    rows = con.execute("SELECT * FROM toto_crowd WHERE cycle_no=? ORDER BY event_no", (cycle_no,)).fetchall()
    if [r["event_no"] for r in rows] != list(range(1, 16)):
        return None, None
    return [{"1": r["p1"], "0": r["px"], "2": r["p2"]} for r in rows], max(r["fetched_at"] for r in rows)


def week_n_eff(q_winner: list[float], winners: dict[int, int]) -> float | None:
    """Resmi kazanan sayılarından etkin kalabalık kolon sayısı: Σ_k kazanan_k / Σ_k PB_k (k = 12..15)."""
    d = hit_distribution(q_winner)
    den = sum(d[k] for k in TIERS if k < len(d))
    return sum(winners.get(k, 0) for k in TIERS) / den if den > 0 else None


def _divs(row: sqlite3.Row | None) -> dict[int, dict[str, Any]] | None:
    if row is None or row["dividends"] is None:
        return None
    return {int(p["tier"]): p for p in json.loads(row["dividends"])}


def _finished_by(con: sqlite3.Connection, cycle_no: int, as_of: datetime) -> bool:
    r = con.execute("SELECT MAX(kickoff_utc) k, COUNT(*) n, SUM(winner IS NOT NULL) w FROM toto_hist_events WHERE cycle_no=?",
                    (cycle_no,)).fetchone()
    return bool(r and r["n"] == 15 and r["w"] == 15 and r["k"] and _dt(r["k"]) + RESULT_GRACE <= as_of)


def _carry_out(con: sqlite3.Connection, cycle_no: int) -> float | None:
    """Haftanın 15 kademesinden bir sonrakine devreden (kazanan yoksa havuzun tamamı); bilinmiyorsa None."""
    d = _divs(con.execute("SELECT dividends FROM toto_hist_weeks WHERE cycle_no=? AND status='settled'", (cycle_no,)).fetchone())
    if d is None or 15 not in d:
        return None
    t = d[15]
    if int(t["winners"]) > 0:
        return 0.0
    return float(t["pool"]) if t.get("pool_known") else None


def blend_probs(probs: list[dict[str, float]], crowd: list[dict[str, float]], a: float) -> list[dict[str, float]]:
    """p^a · r^(1−a), maç başı normalize."""
    b = _norm3(probs, floor=1e-6) ** a * _norm3(crowd, floor=1e-4) ** (1 - a)
    b /= b.sum(1, keepdims=True)
    return [dict(zip(OUTCOMES, map(float, row))) for row in b]


def _pb12(r: np.ndarray, y: np.ndarray) -> np.ndarray:
    q = r[np.arange(r.shape[0])[None, :], y]
    d = np.zeros((len(y), r.shape[0] + 1))
    d[:, 0] = 1.0
    for j in range(r.shape[0]):
        nd = d * (1 - q[:, j:j + 1])
        nd[:, 1:] += d[:, :-1] * q[:, j:j + 1]
        d = nd
    return d[:, 12]


def week_pit(probs: list[dict[str, float]], crowd: list[dict[str, float]], winners: list[str], seed: int) -> list[float]:
    """Her harman ağırlığı a için: gerçekleşen sonucun kalabalık sürprizi (PB_12) modelin öngördüğü dağılımın hangi
    yüzdeliğinde (PIT). Kalibre bir modelde haftalar boyunca ortalama 0,5 olur; 0,5'ten büyükse model kalabalığı şaşırtan
    sonuçları gerçekte olduğundan sık sanıyor (kalabalık kuponunun beklenen ikramiyesi şişer)."""
    r = _norm3(crowd, floor=1e-4)
    yr = np.array([[OUTCOMES.index(w) for w in winners]])
    real = float(_pb12(r, yr)[0])
    rng = np.random.default_rng(seed)
    u = rng.random((PIT_SAMPLES, len(probs)))
    out = []
    for a in BLEND_GRID:
        b = _norm3(blend_probs(probs, crowd, a))
        y = (u[:, :, None] >= np.cumsum(b, axis=1)[None, :, :2]).sum(2)
        out.append(float((_pb12(r, y) <= real).mean()))
    return out


def _past_probs(con: sqlite3.Connection, cycle_no: int, bt_weeks: dict[int, dict[str, Any]] | None,
                tk_odds: dict[int, sqlite3.Row]) -> tuple[list[dict[str, float]] | None, str]:
    """Geçmiş haftanın kilit anındaki olasılıkları: canlı Kupon 1 yükü (kilitli) ya da Spor Toto backtest'inin
    walk-forward olasılıkları ('veri yok' maçta totokazan'ın iddaa oranı, marjsız)."""
    r = con.execute("SELECT payload FROM toto_coupon_sets WHERE cycle_no=? AND kind='olasilik' AND locked=1",
                    (cycle_no,)).fetchone()
    if r is not None:
        evs = json.loads(r["payload"])["events"]
        if len(evs) == 15:
            return [e["probs"] for e in evs], "canli"
    w = (bt_weeks or {}).get(cycle_no)
    if w is None or len(w["events"]) != 15:
        return None, ""
    return backtest_probs(w["events"], tk_odds)[0], "backtest"


def backtest_probs(events: list[dict[str, Any]], tk_odds: dict[int, sqlite3.Row]) -> tuple[list[dict[str, float]], list[str]]:
    probs, sources = [], []
    for e in events:
        o = tk_odds.get(e["event_no"])
        if e["source"] == "yok" and o is not None and o["o1"] and o["ox"] and o["o2"]:
            probs.append(dict(zip(OUTCOMES, mk.devig([o["o1"], o["ox"], o["o2"]]))))
            sources.append("piyasa_tk")
        else:
            probs.append(dict(e["probs"]))
            sources.append(e["source"])
    return probs, sources


def estimate_blend(con: sqlite3.Connection, cycle_no: int, as_of: datetime) -> tuple[float, int]:
    """Harman ağırlığı a: önceki haftalarda (sonucu as_of'tan önce belli) ortalama PIT'i 0,5'e en yakın a. PIT değerleri
    hafta başına bir kez hesaplanıp meta 'toto_crowd_pit' içinde saklanır."""
    cache: dict[str, Any] = db.meta_get(con, "toto_crowd_pit") or {}
    bt = db.meta_get(con, "toto_backtest")
    bt_weeks = {int(w["cycle_no"]): w for w in (bt or {}).get("weeks", [])}
    pits: list[list[float]] = []
    changed = False
    for r in con.execute("SELECT cycle_no FROM toto_crowd_weeks WHERE status='settled' AND cycle_no < ? ORDER BY cycle_no",
                         (cycle_no,)).fetchall():
        c = int(r["cycle_no"])
        if not _finished_by(con, c, as_of):
            continue
        tk_odds = {x["event_no"]: x for x in con.execute("SELECT * FROM toto_crowd WHERE cycle_no=?", (c,))}
        probs, src_name = _past_probs(con, c, bt_weeks, tk_odds)
        if probs is None:
            continue
        hit = cache.get(str(c))
        if hit is None or hit.get("src") != src_name or len(hit.get("pit", [])) != len(BLEND_GRID):
            crowd, _ = crowd_probs(con, c)
            winners = [e["winner"] for e in con.execute(
                "SELECT winner FROM toto_hist_events WHERE cycle_no=? ORDER BY event_no", (c,))]
            if crowd is None or len(winners) != 15:
                continue
            hit = {"src": src_name, "pit": week_pit(probs, crowd, winners, MC_SEED + c)}
            cache[str(c)] = hit
            changed = True
        pits.append(hit["pit"])
    if changed:
        if con.in_transaction:   # update_coupon işlem içinde çağırır
            db.meta_set(con, "toto_crowd_pit", cache)
        else:
            with db.tx(con):
                db.meta_set(con, "toto_crowd_pit", cache)
    if len(pits) < BLEND_MIN_WEEKS:
        return BLEND_PRIOR, len(pits)
    means = np.array(pits).mean(0)
    return float(BLEND_GRID[int(np.argmin(np.abs(means - 0.5)))]), len(pits)


def estimate_market(con: sqlite3.Connection, cycle_no: int, as_of: datetime, price: float) -> tuple[Market | None, str | None]:
    """Bu haftanın N ve kademe havuzları; yalnız cycle_no'dan önceki ve sonucu as_of'tan önce belli olmuş haftalar."""
    observed: dict[int, dict[str, float]] = {}
    for pr in con.execute("SELECT cycle_no, source, price FROM toto_hist_prices"):
        observed.setdefault(int(pr["cycle_no"]), {})[pr["source"]] = float(pr["price"])
    rows = con.execute(
        """SELECT w.cycle_no, w.dividends FROM toto_hist_weeks w JOIN toto_crowd_weeks cw ON cw.cycle_no=w.cycle_no
           WHERE w.status='settled' AND cw.status='settled' AND w.cycle_no < ? ORDER BY w.cycle_no DESC""", (cycle_no,)
    ).fetchall()
    basis: list[dict[str, Any]] = []
    realized_pb: list[list[float]] = []
    for r in rows:
        c = int(r["cycle_no"])
        if not _finished_by(con, c, as_of):
            continue
        crowd, _ = crowd_probs(con, c)
        divs = _divs(r)
        if crowd is None or divs is None or any(k not in divs for k in TIERS):
            continue
        winners_by_ev = {e["event_no"]: e["winner"] for e in con.execute(
            "SELECT event_no, winner FROM toto_hist_events WHERE cycle_no=?", (c,))}
        q = [crowd[i][winners_by_ev[i + 1]] for i in range(15)]
        d = hit_distribution(q)
        realized_pb.append([d[k] for k in TIERS])
        if len(basis) >= HISTORY_WEEKS:
            continue                                   # yalnız PB alt sınırı için (tüm önceki haftalar)
        winners = {k: int(divs[k]["winners"]) for k in TIERS}
        n_eff = week_n_eff(q, winners)
        if n_eff is None or n_eff <= 0:
            continue
        p_c, _why = column_price(c, observed.get(c, {}))
        scale = price / p_c if p_c else 1.0
        base: dict[int, float] = {}
        for k in (12, 13, 14):
            if divs[k].get("pool_known") and winners[k] > 0:   # kazanansız kademede havuz devirle karışır
                base[k] = float(divs[k]["pool"]) * scale
        carry_in = _carry_out(con, c - 1)
        if carry_in is not None and divs[15].get("pool_known") and float(divs[15]["pool"]) - carry_in > 0:
            base[15] = (float(divs[15]["pool"]) - carry_in) * scale
        basis.append({"cycle_no": c, "n_eff": n_eff, "winners": {str(k): v for k, v in winners.items()},
                      "base_pools": {str(k): v for k, v in base.items()}, "price": p_c})
    if len(basis) < MIN_HISTORY_WEEKS:
        return None, (f"N/havuz tahmini için en az {MIN_HISTORY_WEEKS} geçmiş hafta gerekir (kalabalık verisi ve resmi "
                      f"sonucu olan: {len(basis)})")
    pools: dict[int, float] = {}
    for k in TIERS:
        vals = [b["base_pools"][str(k)] for b in basis if str(k) in b["base_pools"]]
        if not vals:
            return None, f"{k} kademesi havuz geçmişi yok"
        pools[k] = float(statistics.median(vals))
    notes: list[str] = []
    prev = cycle_no - 1
    carry = 0.0
    if _finished_by(con, prev, as_of):
        co = _carry_out(con, prev)
        if co is None:
            notes.append(f"{prev}. haftanın 15 devri bilinmiyor; devir 0 alındı")
        else:
            carry = co
    else:
        notes.append(f"{prev}. haftanın sonucu kilit anında belli değil; devir 0 alındı")
    pools[15] += carry
    n = float(statistics.median(b["n_eff"] for b in basis))
    floor = {k: float(min(pb[i] for pb in realized_pb)) for i, k in enumerate(TIERS)}
    a, a_weeks = estimate_blend(con, cycle_no, as_of)
    if a_weeks < BLEND_MIN_WEEKS:
        notes.append(f"harman ağırlığı için geçmiş az ({a_weeks} hafta): a = {BLEND_PRIOR}")
    return Market(n_columns=n, pools=pools, carry=carry, basis=basis, notes=notes, pb_floor=floor,
                  floor_weeks=len(realized_pb), blend_a=a, blend_weeks=a_weeks), None


# ---------------------------------------------------------------- beklenen ikramiye motoru

def _norm3(rows: list[dict[str, float]], floor: float = 0.0) -> np.ndarray:
    a = np.array([[max(float(r[o]), floor) for o in OUTCOMES] for r in rows], dtype=np.float64)
    return a / a.sum(1, keepdims=True)


class PrizeModel:
    """Sonuç örnekleri (ağırlıklı) üzerinde kuponun beklenen ikramiyesi. Örnekler Monte Carlo (from_samples) ya da tam
    sayım (from_outcomes, testler için) olabilir."""

    def __init__(self, y: np.ndarray, w: np.ndarray, crowd: list[dict[str, float]], market: Market) -> None:
        self.y = np.ascontiguousarray(y.astype(np.int64))   # (M, 15) sonuç indisleri (OUTCOMES sırası)
        self.w = w / w.sum()                         # (M,) ağırlık
        self.n = y.shape[1]
        if self.n != 15:
            raise ValueError("Spor Toto kuponu 15 maç ister")
        r = _norm3(crowd, floor=1e-4)
        q = r[np.arange(self.n)[None, :], self.y]    # kalabalık kolonunun j. maçı bilme olasılığı
        d = np.zeros((len(self.y), self.n + 1))
        d[:, 0] = 1.0
        for j in range(self.n):
            qj = q[:, j:j + 1]
            nd = d * (1 - qj)
            nd[:, 1:] += d[:, :-1] * qj
            d = nd
        self.pb = d[:, _TIER_IDX]                    # (M, 4) PB_12..PB_15
        floor = np.array([market.pb_floor.get(int(k), 0.0) for k in _TIER_IDX])
        lam = market.n_columns * np.maximum(self.pb, floor[None, :])
        h = np.where(lam > 1e-12, -np.expm1(-lam) / np.maximum(lam, 1e-300), 1.0)
        # (4, M): katsayı-öncelikli düzen (satırlar bitişik; tepeden bölme satır satır ilerler)
        self.A = np.ascontiguousarray((np.array([market.pools[int(k)] for k in _TIER_IDX])[None, :] * h).T)
        self.ybits = (1 << self.y).astype(np.int64)
        self._hits: dict[tuple[int, int], np.ndarray] = {}

    @classmethod
    def from_samples(cls, probs: list[dict[str, float]], crowd: list[dict[str, float]], market: Market,
                     samples: int = MC_SAMPLES, seed: int = MC_SEED) -> "PrizeModel":
        """Önem örneklemesi (savunmalı karışım): ikramiyenin büyük kısmı kalabalığın az oynadığı sonuçların tuttuğu seyrek
        örneklerden gelir; düz Monte Carlo'da bunlar çok az düşer ve arama gürültüye uyar. Ağırlık w = Π p / g ≤ 2^15;
        aynı sayıda örnekte Kupon 2 değerinin standart sapması ~6 kat küçüldü (16 Eki 2026 haftasında ölçüldü)."""
        p = _norm3(probs)
        r = _norm3(crowd, floor=1e-4)
        t = p * (p / r) ** IS_BETA
        t /= t.sum(1, keepdims=True)
        g = (1 - IS_ALPHA) * p + IS_ALPHA * t
        rng = np.random.default_rng(seed)
        u = rng.random((samples, len(probs)))
        cum = np.cumsum(g, axis=1)
        y = (u[:, :, None] >= cum[None, :, :2]).sum(2)
        cols = np.arange(len(probs))[None, :]
        w = np.prod(p[cols, y] / g[cols, y], axis=1)
        return cls(y, w, crowd, market)

    @classmethod
    def from_outcomes(cls, y: np.ndarray, probs: list[dict[str, float]], crowd: list[dict[str, float]],
                      market: Market) -> "PrizeModel":
        p = _norm3(probs)
        w = np.prod(p[np.arange(y.shape[1])[None, :], y], axis=1)
        return cls(y, w, crowd, market)

    # --- polinom işlemleri: yalnız üst katsayılar tutulur (sütun t = derece LOW + t; 12..15 kademesi ve iki maç bölmesi
    # için derece ≥ 10 yeterli). Katsayı = tam o kadar doğru kolon sayısı (tam sayı, float64'te kesin).
    def _hit(self, j: int, mask: int) -> np.ndarray:
        """(M,) 1.0 / 0.0: j. maçın sonucu işaret kümesinde mi (önbellekli)."""
        key = (j, mask)
        h = self._hits.get(key)
        if h is None:
            h = ((self.ybits[:, j] & mask) != 0).astype(np.float64)
            self._hits[key] = h
        return h

    def poly(self, masks: list[int]) -> np.ndarray:
        """(TOP, M): üst katsayılar (satır t = derece LOW + t). Iska sayısı u = 1/x üzerinden: her terim x·(isabette
        1 + (s − 1)u, ıskada s·u); u^m katsayısı yalnız daha küçük m'lere bağlı olduğundan m < TOP'ta kesmek kesindir."""
        c = np.zeros((_TOP, len(self.y)))
        c[0] = 1.0
        for j, m in enumerate(masks):
            h = self._hit(j, m)
            nxt = h * c
            nxt[1:] += (_size(m) - h) * c[:-1]
            c = nxt
        return c[::-1].copy()

    def divide(self, p: np.ndarray, j: int, mask: int) -> np.ndarray:
        """p / (j. maçın terimi): isabette (x + s − 1), ıskada s. Bölüm tam sayı katsayılı olduğundan tepeden bölme
        kesindir ve yalnız üst katsayıları kullanır."""
        s = _size(mask)
        a = float(s - 1)
        q = np.empty_like(p)
        q[_TOP - 1] = 0.0
        if a == 0.0:
            q[:_TOP - 1] = p[1:]
        else:
            for t in range(_TOP - 2, -1, -1):
                np.multiply(q[t + 1], -a, out=q[t])
                q[t] += p[t + 1]
        base = p * (1.0 / s)
        q -= base
        q *= self._hit(j, mask)
        q += base
        return q

    def value_of_poly(self, p: np.ndarray) -> float:
        return float((self.A * p[_T0:]).sum(0) @ self.w)

    def value(self, masks: list[int]) -> float:
        return self.value_of_poly(self.poly(masks))

    def by_tier(self, masks: list[int]) -> dict[int, float]:
        v = (self.A * self.poly(masks)[_T0:]) @ self.w
        return {int(k): float(x) for k, x in zip(_TIER_IDX, v)}

    def estimate(self, masks: list[int]) -> tuple[dict[int, float], float]:
        """Kademe başına beklenen ikramiye ve toplamın standart hatası (öz-normalize önem örneklemesi)."""
        per = self.A * self.poly(masks)[_T0:]
        v = per @ self.w
        tot = per.sum(0)
        se = float(np.sqrt(np.sum(self.w ** 2 * (tot - float(tot @ self.w)) ** 2)))
        return {int(k): float(x) for k, x in zip(_TIER_IDX, v)}, se

    def single_values(self, rest: np.ndarray, j: int) -> np.ndarray:
        """j. maçta 7 işaret kümesinin her biri için kupon değeri (diğer maçlar sabit). rest = poly / terim_j."""
        b1 = (self.A * rest[_T0 - 1:_TOP - 1]).sum(0)
        b0 = (self.A * rest[_T0:]).sum(0)
        w1 = np.bincount(self.y[:, j], weights=self.w * b1, minlength=3)
        w0 = np.bincount(self.y[:, j], weights=self.w * b0, minlength=3)
        return (_C[:, :, 1] * w1[None, :] + _C[:, :, 0] * w0[None, :]).sum(1)

    def pair_values(self, rest2: np.ndarray, j: int, l: int) -> np.ndarray:
        """(7, 7): j ve l maçlarının işaret kümesi çiftleri için kupon değeri. rest2 = poly / terim_j / terim_l."""
        idx = 3 * self.y[:, j] + self.y[:, l]
        dm = np.stack([np.bincount(idx, weights=self.w * (self.A * rest2[_T0 - m:_TOP - m]).sum(0),
                                   minlength=9).reshape(3, 3) for m in range(3)])
        e = np.empty((2, 2, 3, 3))
        for a in range(2):
            for b in range(2):
                e[a, b] = dm[a + b]
        return np.einsum("xoa,ypb,abop->xy", _C, _C, e)


def search(models: PrizeModel | list[PrizeModel], start: list[int], max_cols: int,
           allowed: list[tuple[int, ...]] | None = None) -> tuple[list[int], float]:
    """Yerel arama: önce tek maç değişikliği (7 küme), iyileşme yoksa iki maç takası; kolon ≤ max_cols.

    Birden çok (bağımsız) örneklem verilirse hamle yalnız HEPSİNDE değeri artırıyorsa kabul edilir ve en küçük artışı en
    büyük olan seçilir: tek bir şanslı örneğe uyan hamleler böylece elenir. Dönen değer örneklemlerin ortalamasıdır."""
    ms = models if isinstance(models, list) else [models]
    n = len(start)
    allow = [np.array([m in (allowed[j] if allowed else MASKS) for m in MASKS]) for j in range(n)]
    cur = list(start)
    ps = [m.poly(cur) for m in ms]
    vals = np.array([m.value_of_poly(p) for m, p in zip(ms, ps)])
    for _ in range(MAX_ITER):
        cols = math.prod(_size(x) for x in cur)
        tol = float(np.max(np.abs(vals))) * 1e-9 + 1e-9
        best_g, best_mv = tol, None
        rests = [[m.divide(p, j, cur[j]) for j in range(n)] for m, p in zip(ms, ps)]
        for j in range(n):
            ok = allow[j] & (cols // _size(cur[j]) * _SZ <= max_cols)
            ok[_MIDX[cur[j]]] = False
            if not ok.any():
                continue
            gain = np.min([m.single_values(rests[i][j], j) - vals[i] for i, m in enumerate(ms)], axis=0)
            k = int(np.argmax(np.where(ok, gain, -np.inf)))
            if gain[k] > best_g:
                best_g, best_mv = float(gain[k]), [(j, MASKS[k])]
        if best_mv is None:
            for j in range(n):
                for l in range(j + 1, n):
                    base = cols // (_size(cur[j]) * _size(cur[l]))
                    ok = allow[j][:, None] & allow[l][None, :] & (base * _SZ[:, None] * _SZ[None, :] <= max_cols)
                    ok[_MIDX[cur[j]], :] = False   # tek maç değişiklikleri zaten denendi
                    ok[:, _MIDX[cur[l]]] = False
                    if not ok.any():
                        continue
                    gain = np.min([m.pair_values(m.divide(rests[i][j], l, cur[l]), j, l) - vals[i]
                                   for i, m in enumerate(ms)], axis=0)
                    k = int(np.argmax(np.where(ok, gain, -np.inf)))
                    xi, yi = divmod(k, len(MASKS))
                    if gain[xi, yi] > best_g:
                        best_g, best_mv = float(gain[xi, yi]), [(j, MASKS[xi]), (l, MASKS[yi])]
        if best_mv is None:
            break
        for j, m in best_mv:
            cur[j] = m
        ps = [m.poly(cur) for m in ms]
        vals = np.array([m.value_of_poly(p) for m, p in zip(ms, ps)])
    return cur, float(vals.mean())


def common_columns(a: list[int], b: list[int]) -> int:
    return math.prod(_size(x & y) for x, y in zip(a, b))


def _tilted(probs: list[dict[str, float]], crowd: list[dict[str, float]]) -> list[dict[str, float]]:
    """İkinci başlangıç: olasılık × (olasılık / oynanma) ile eğilmiş, normalize."""
    out = []
    for p, r in zip(probs, crowd):
        v = {o: p[o] * min(p[o] / max(r[o], 1e-3), 4.0) for o in OUTCOMES}
        s = sum(v.values())
        out.append({o: x / s for o, x in v.items()})
    return out


def crowd_models(probs: list[dict[str, float]], crowd: list[dict[str, float]], market: Market,
                 seed: int, samples: int | None = None) -> tuple[list[PrizeModel], PrizeModel]:
    """SEARCH_RUNS bağımsız arama örneklemi + aramadan bağımsız değerlendirme örneklemi."""
    n = samples or MC_SAMPLES
    searches = [PrizeModel.from_samples(probs, crowd, market, samples=n, seed=seed + 104729 * i)
                for i in range(SEARCH_RUNS)]
    return searches, PrizeModel.from_samples(probs, crowd, market, samples=EVAL_SAMPLES, seed=seed + EVAL_SEED_OFFSET)


def _disjoint_best(searches: list[PrizeModel], evaluator: PrizeModel, best2: list[int],
                   max_cols: int) -> tuple[list[int], float]:
    """Kupon 2 ile ortak kolonu olmayan en iyi kupon: her j0 için j0'da Kupon 2'nin işaretlerinden ayrık küme zorunlu.
    Adaylar: 15 tek-maç başlangıcı + başlangıç kazancı en iyi K3_SEARCHES tanesinden yerel arama; seçim bağımsız örneklemle."""
    ps = [m.poly(best2) for m in searches]
    vals2 = [m.value_of_poly(p) for m, p in zip(searches, ps)]
    cols2 = math.prod(_size(m) for m in best2)
    starts: list[tuple[float, int, list[int]]] = []
    for j0 in range(len(best2)):
        allowed_j0 = [m for m in MASKS if m & best2[j0] == 0]
        if not allowed_j0:
            continue
        gain = np.min([m.single_values(m.divide(p, j0, best2[j0]), j0) - v for m, p, v in zip(searches, ps, vals2)], axis=0)
        feas = [(float(gain[_MIDX[m]]), m) for m in allowed_j0 if cols2 // _size(best2[j0]) * _size(m) <= max_cols]
        if not feas:
            continue
        g, m = max(feas)
        st = list(best2)
        st[j0] = m
        starts.append((g, j0, st))
    if not starts:
        raise ValueError("Kupon 3 kurulamadı: her maçta üç sonuç işaretli")
    starts.sort(key=lambda x: -x[0])
    cands3 = [st for _g, _j0, st in starts]
    for _g, j0, st in starts[:K3_SEARCHES]:
        allowed = [MASKS] * len(best2)
        allowed[j0] = tuple(m for m in MASKS if m & best2[j0] == 0)
        cands3.append(search(searches, st, max_cols, allowed)[0])
    return max(((c, evaluator.value(c)) for c in cands3), key=lambda x: x[1])


def optimize_crowd(searches: list[PrizeModel], evaluator: PrizeModel, probs: list[dict[str, float]],
                   crowd: list[dict[str, float]], base: list[list[str]], max_cols: int) -> tuple[list[int], float, list[int], float]:
    """Kupon 2 (beklenen ikramiye en büyük) ve Kupon 3 (Kupon 2 ile ortak kolon 0, beklenen ikramiye en büyük).

    Beklenen ikramiye seyrek, çok büyük ödemelerden gelir; arama örneklemindeki tek bir şanslı örneğe uyan kupon
    bağımsız örneklemde Kupon 1'den bile kötü çıkabiliyordu (16 Eki 2026 haftası: arama değeri 11.800 TL, bağımsız
    değer 275 TL, değerin %44'ü tek örnekten). Bu yüzden adaylar (Kupon 1, eğilmiş başlangıç, her arama örnekleminin
    yerel arama sonucu; Kupon 3 için 15 "ayrık maç" başlangıcı ve en iyilerinden arama) aramadan bağımsız örneklemle
    karşılaştırılır; en iyisi seçilir. Yerel arama da hamleyi yalnız iki arama örnekleminde birden değer artıyorsa kabul
    eder. Dönüş değerleri bağımsız örneklemdeki beklenen ikramiyedir."""
    k1 = [mask_of(s) for s in base]
    tilted = [mask_of(s) for s in optimize(_tilted(probs, crowd), max_cols)]
    cands2 = [k1, tilted, search(searches, k1, max_cols)[0], search(searches, tilted, max_cols)[0]]
    best2, v2 = max(((c, evaluator.value(c)) for c in cands2), key=lambda x: x[1])
    best3, v3 = _disjoint_best(searches, evaluator, best2, max_cols)
    # Kupon 3 adayı Kupon 2'den iyiyse o da bir Kupon 2 adayıdır: yer değiştir, Kupon 3'ü yeniden kur
    for _ in range(SWAP_ROUNDS):
        if v3 <= v2:
            break
        best2, v2 = best3, v3
        best3, v3 = _disjoint_best(searches, evaluator, best2, max_cols)
    return best2, v2, best3, v3


# ---------------------------------------------------------------- kupon yükleri (canlı)

def _diff_notes(base_ev: list[dict[str, Any]], picks: list[list[str]], probs: list[dict[str, float]],
                crowd: list[dict[str, float]]) -> list[dict[str, Any]]:
    out = []
    for ev, sel, p, r in zip(base_ev, picks, probs, crowd):
        if set(sel) == set(ev["picks"]):
            continue
        added = [o for o in OUTCOMES if o in sel and o not in ev["picks"]]
        removed = [o for o in OUTCOMES if o not in sel and o in ev["picks"]]
        out.append({"event_no": ev["event_no"], "from": [o for o in OUTCOMES if o in ev["picks"]], "to": sel,
                    "added": [{"o": o, "p": p[o], "crowd": r[o]} for o in added],
                    "removed": [{"o": o, "p": p[o], "crowd": r[o]} for o in removed]})
    return out


def _why(kind: str, diffs: list[dict[str, Any]], exp: float, exp_base: float | None) -> str:
    if not diffs:
        return "Kupon 1 ile aynı işaretler: kalabalığa göre daha değerli bir değişiklik bulunamadı."
    add = [a for d in diffs for a in d["added"]]
    rem = [a for d in diffs for a in d["removed"]]
    parts = [f"Kupon 1'den {len(diffs)} maçta farklı."]
    if add:
        parts.append("Eklenen işaretler ortalama %{:.0f} oynanıyor, olasılıkları ortalama %{:.0f}.".format(
            100 * sum(a["crowd"] for a in add) / len(add), 100 * sum(a["p"] for a in add) / len(add)))
    if rem:
        parts.append("Çıkarılanlar ortalama %{:.0f} oynanıyor (olasılık %{:.0f}).".format(
            100 * sum(a["crowd"] for a in rem) / len(rem), 100 * sum(a["p"] for a in rem) / len(rem)))
    if exp_base is not None and exp_base > 0:
        parts.append(f"Beklenen ikramiye Kupon 1'in {exp / exp_base:.2f} katı.")
    if kind == "kalabalik_2":
        parts.append("Kupon 2 ile ortak kolonu yok.")
    return " ".join(parts)


def coupon_from_masks(base: dict[str, Any], kind: str, masks: list[int], model: PrizeModel | None,
                      crowd: list[dict[str, float]] | None) -> dict[str, Any]:
    """Kupon 1 yükünden (olasılıklar, maç bilgisi) başka işaretlerle kupon yükü."""
    title, desc = KIND_INFO[kind]
    picks = [sel_of(m) for m in masks]
    events = []
    for ev, sel, i in zip(base["events"], picks, range(len(picks))):
        cover = sum(ev["probs"][o] for o in sel)
        e = {**ev, "picks": sel, "cover": cover, "kind": {1: "banko", 2: "çift", 3: "üçlü"}[len(sel)]}
        e["crowd"] = crowd[i] if crowd else None
        events.append(e)
    covers = [e["cover"] for e in events]
    dist = hit_distribution(covers)
    n = len(events)
    columns = math.prod(len(s) for s in picks)
    out = {**base, "kind": kind, "title": title, "description": desc, "events": events, "columns": columns,
           "cost": columns * base["column_price"], "p15": dist[n] if n == 15 else 0.0,
           "p_at_least": {str(k): sum(dist[k:]) for k in TIERS if k <= n}, "expected_hits": sum(covers)}
    if model is not None:
        bt, se = model.estimate(masks)
        out["expected_prize"] = sum(bt.values())
        out["expected_prize_se"] = se
        out["expected_prize_by_tier"] = {str(k): v for k, v in bt.items()}
    else:
        out["expected_prize"] = None
        out["expected_prize_se"] = None
        out["expected_prize_by_tier"] = None
    return out


def build_crowd_coupons(con: sqlite3.Connection, cycle_no: int, base: dict[str, Any], as_of: datetime,
                        max_cols: int) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Kupon 1 yükü (base) üzerinden Kupon 2 ve 3. Dönüş: ({kind: yük} — olasilik dahil, kalabalık alanlarıyla), neden."""
    crowd, crowd_at = crowd_probs(con, cycle_no)
    if crowd is None:
        return {}, "Bu hafta için kalabalık (oynanma oranı) verisi yok: totokazan erişilemedi ya da hafta eşleşmedi."
    if len(base["events"]) != 15:
        return {}, "Programda 15 maç yok."
    market, why = estimate_market(con, cycle_no, as_of, base["column_price"])
    if market is None:
        return {}, why
    probs = [e["probs"] for e in base["events"]]
    p_ev = blend_probs(probs, crowd, market.blend_a)
    searches, model = crowd_models(p_ev, crowd, market, MC_SEED + cycle_no)
    k1 = [mask_of(e["picks"]) for e in base["events"]]
    s2, _v2, s3, _v3 = optimize_crowd(searches, model, p_ev, crowd, [e["picks"] for e in base["events"]], max_cols)
    cw = con.execute("SELECT * FROM toto_crowd_weeks WHERE cycle_no=?", (cycle_no,)).fetchone()
    crowd_meta = {"fetched_at": crowd_at, "tk_week_id": cw["tk_week_id"] if cw else None,
                  "tk_name": cw["tk_name"] if cw else None, "source": "totokazan.com (resmi değil)"}
    common = {"market": market.to_json(), "crowd_source": crowd_meta, "mc_samples": MC_SAMPLES, "eval_samples": EVAL_SAMPLES}
    c1 = coupon_from_masks(base, "olasilik", k1, model, crowd)
    c2 = coupon_from_masks(base, "kalabalik", s2, model, crowd)
    c3 = coupon_from_masks(base, "kalabalik_2", s3, model, crowd)
    for c in (c1, c2, c3):
        c.update(common)
    e1 = c1["expected_prize"]
    for c in (c2, c3):
        c["diffs"] = _diff_notes(base["events"], [e["picks"] for e in c["events"]], probs, crowd)
        c["why"] = _why(c["kind"], c["diffs"], c["expected_prize"], e1)
    c3["common_columns_with_kalabalik"] = common_columns(s2, s3)
    return {"olasilik": c1, "kalabalik": c2, "kalabalik_2": c3}, None


# ---------------------------------------------------------------- backtest

def _realized_by_tier(won: dict[int, int], pools: list[dict[str, Any]]) -> dict[str, float]:
    by = {p["tier"]: p for p in pools}
    out = {}
    for k, n in won.items():
        p = by.get(k)
        if n > 0 and p is not None and p["pool_known"]:
            out[str(k)] = p["pool"] * n / (p["winners"] + n)
    return out


def run_crowd_backtest(con: sqlite3.Connection, progress: Progress, *, samples: int | None = None) -> dict[str, Any]:
    """Üç kupon, kalabalık verisi olan ve sonuçlanmış haftalarda walk-forward: olasılıklar Spor Toto backtest'inin 'canlı'
    harmanı (meta toto_backtest; model her hafta kilitten önceki maçlarla eğitildi), N/havuz yalnız önceki haftalardan,
    değerlendirme o haftanın gerçek ikramiye tablosuyla (sportoto_backtest.settle ile aynı paylaşım)."""
    bt = db.meta_get(con, "toto_backtest")
    if not bt or not bt.get("weeks"):
        raise RuntimeError("Kalabalık backtest'i: önce Spor Toto backtest'i (toto_backtest) çalışmalı")
    max_cols = int(bt["columns"])
    crowd_weeks = {r["cycle_no"] for r in con.execute("SELECT cycle_no FROM toto_crowd_weeks WHERE status='settled'")}
    rows: dict[str, list[dict[str, Any]]] = {k: [] for k in KINDS}
    weeks_out: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    n_tk_fallback = 0
    for w in bt["weeks"]:
        c = int(w["cycle_no"])
        if c not in crowd_weeks:
            continue
        crowd, _ = crowd_probs(con, c)
        if crowd is None:
            excluded.append({"cycle_no": c, "reason": "kalabalık verisi eksik"})
            continue
        as_of = _dt(w["payin_end_utc"]) - timedelta(minutes=TOTO_LOCK_MINUTES)
        market, why = estimate_market(con, c, as_of, float(w["column_price"]))
        if market is None:
            excluded.append({"cycle_no": c, "reason": why})
            continue
        odds = {r["event_no"]: r for r in con.execute("SELECT * FROM toto_crowd WHERE cycle_no=?", (c,))}
        probs, sources = backtest_probs(w["events"], odds)
        n_tk_fallback += sources.count("piyasa_tk")
        p_ev = blend_probs(probs, crowd, market.blend_a)
        winners = [e["winner"] for e in w["events"]]
        searches, model = crowd_models(p_ev, crowd, market, MC_SEED + c, samples=samples)
        k1 = [mask_of(s) for s in optimize(probs, max_cols)]
        s2, _v2, s3, _v3 = optimize_crowd(searches, model, p_ev, crowd, [sel_of(m) for m in k1], max_cols)
        assert common_columns(s2, s3) == 0
        wk: dict[str, Any] = {"cycle_no": c, "program_name": w.get("program_name"), "column_price": w["column_price"],
                              "market": {"n_columns": market.n_columns, "pools": {str(k): v for k, v in market.pools.items()},
                                         "carry": market.carry, "n_weeks": len(market.basis), "blend_a": market.blend_a,
                                         "blend_weeks": market.blend_weeks},
                              "n_by_source": dict(Counter(sources)), "coupons": {}}
        # gerçekleşen etkin N (kalibrasyon için; tahminde kullanılmaz)
        divs = {p["tier"]: p for p in w["pools"]}
        wk["realized_n_eff"] = week_n_eff([crowd[i][winners[i]] for i in range(15)],
                                          {k: int(divs[k]["winners"]) for k in TIERS if k in divs})
        for kind, masks in (("olasilik", k1), ("kalabalik", s2), ("kalabalik_2", s3)):
            picks = [sel_of(m) for m in masks]
            res = settle(picks, winners, w["pools"], float(w["column_price"]))
            bt_tier = model.by_tier(masks)
            covers = [sum(p[o] for o in s) for p, s in zip(probs, picks)]
            dist = hit_distribution(covers)
            won = {int(k): v for k, v in res["winning_columns"].items()}
            row = {**res, "expected_prize": sum(bt_tier.values()),
                   "expected_by_tier": {str(k): v for k, v in bt_tier.items()},
                   "realized_by_tier": _realized_by_tier(won, w["pools"]), "p15": dist[15],
                   "p12": sum(dist[12:]), "expected_hits": sum(covers), "picks": picks}
            rows[kind].append(row)
            wk["coupons"][kind] = {k: row[k] for k in ("hits", "columns", "cost", "prize", "expected_prize", "p15", "p12",
                                                       "winning_columns")}
        weeks_out.append(wk)
        progress(f"Kalabalık backtest: hafta {c} · " + " · ".join(
            f"{k} {wk['coupons'][k]['hits']}/15 {wk['coupons'][k]['prize']:.0f} TL (bekl. {wk['coupons'][k]['expected_prize']:.0f})"
            for k in KINDS))

    def kind_summary(rs: list[dict[str, Any]]) -> dict[str, Any]:
        s = summarize(rs)
        if not rs:
            return s
        exp = sum(r["expected_prize"] for r in rs)
        s.update({
            "expected_prize": exp, "expected_roi": exp / s["cost"] - 1.0 if s["cost"] else None,
            "realized_over_expected": s["prize"] / exp if exp > 0 else None,
            "expected_by_tier": {str(k): sum(r["expected_by_tier"].get(str(k), 0.0) for r in rs) for k in TIERS},
            "realized_by_tier": {str(k): sum(r["realized_by_tier"].get(str(k), 0.0) for r in rs) for k in TIERS},
            "p12_expected_weeks": sum(r["p12"] for r in rs), "p15_expected_weeks": sum(r["p15"] for r in rs),
            "avg_columns": sum(r["columns"] for r in rs) / len(rs),
        })
        return s

    kinds = {k: kind_summary(v) for k, v in rows.items()}
    all_rows = [r for k in KINDS for r in rows[k]]
    total_cost = sum(r["cost"] for r in all_rows)
    total_prize = sum(r["prize"] for r in all_rows)
    n_est = [(w["market"]["n_columns"], w["realized_n_eff"]) for w in weeks_out if w["realized_n_eff"]]
    result = {
        "created_at": _iso(datetime.now(timezone.utc)),
        "window": {"from_cycle": weeks_out[0]["cycle_no"] if weeks_out else None,
                   "to_cycle": weeks_out[-1]["cycle_no"] if weeks_out else None, "n_weeks": len(weeks_out)},
        "columns": max_cols, "mc_samples": samples or MC_SAMPLES, "kinds": kinds,
        "combined": {"cost": total_cost, "prize": total_prize, "roi": total_prize / total_cost - 1.0 if total_cost else None},
        "n_estimate": {"median_ratio_realized_over_est": statistics.median(r / e for e, r in n_est) if n_est else None,
                       "n": len(n_est)},
        "excluded": excluded, "tk_odds_fallback_events": n_tk_fallback, "weeks": weeks_out,
        "notes": [
            "Olasılıklar Spor Toto backtest'inin 'canlı' harmanıdır (model her hafta kilitten önceki maçlarla eğitildi); "
            "ESPN/football-data verisi olmayan maçlarda (canlıda iddaa oranı kullanılır) totokazan'ın iddaa oranı marjsız "
            "kullanıldı; bu oran maç saatine yakın okunmuştur (hafif iyimserlik). Üç kupon aynı olasılıklarla kuruldu.",
            "Oynanma oranı olarak haftanın SON yüzdeleri kullanıldı (canlıda kilit anındaki değer kullanılır); kapanışa "
            "kadar oranlar birkaç puan oynayabilir.",
            "N (etkin kalabalık kolon) ve havuzlar yalnız önceki haftalardan (en çok 6, medyan); 15 havuzuna önceki "
            "haftanın devri eklendi. Gerçekleşen ikramiye o haftanın resmi kazanan sayıları ve havuzlarıyla hesaplandı.",
            "Beklenen ikramiyede sonuç olasılığı bizim olasılık ile oynanma oranının geometrik harmanıdır (ağırlık a yalnız "
            "önceki haftalardan; ilk 6 haftada 0,5); kalabalığın kazanan sayısı geçmişte gerçekleşen en sürprizli haftanın "
            "altında tahmin edilmez. Bildirilen beklenen değer aramadan bağımsız örneklerle hesaplandı.",
            "İkramiye çok seyrek ve ağır kuyruklu (14–15 bilme); 30 civarı haftada ROI farkları büyük ölçüde şanstır. "
            "Beklenen / gerçekleşen oranı modelin kalibrasyonu için kaba bir göstergedir.",
            "totokazan resmi kaynak değildir; oynanma yüzdesinin hangi kupon tabanından hesaplandığı bilinmiyor.",
        ],
    }
    progress("Kalabalık backtest: " + " · ".join(
        f"{k} ROI={kinds[k].get('roi')} bekl.ROI={kinds[k].get('expected_roi')}" for k in KINDS))
    with db.tx(con):
        db.meta_set(con, "toto_crowd_backtest", result)
    return result


async def fetch_crowd_history(con: sqlite3.Connection, progress: Progress, client: JsonGetter | None = None) -> dict[str, Any]:
    """Haftalık backtest işinde: biten tüm totokazan haftalarının oynanma yüzdeleri (bir kez)."""
    from .sources.http import PoliteClient

    r = con.execute("SELECT MAX(cycle_no) c FROM toto_weeks").fetchone()
    open_cycle = int(r["c"]) if r and r["c"] is not None else None
    own = client is None
    cl: Any = client or PoliteClient()
    try:
        out = await ingest_crowd(con, cl, open_cycle)
    finally:
        if own:
            await cl.__aexit__(None, None, None)
    progress(f"Kalabalık verisi: {out}")
    return out

