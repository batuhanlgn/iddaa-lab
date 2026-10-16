"""Kupon motoru (Codex ile ortak karar, docs/03-04; kullanıcı tercihleriyle güncellendi, 15 Eki 2026).

- Seçim olasılığı: muhafazakâr harman p_safe = min(skor matrisi harmanı, pazar içi harman).
- Tüm pazarlar ve oyuncu tahminleri seçilebilir; backtest'te doğrulanmamış pazar aileleri seçimde etiketlenir.
- Öneriler modelin maça bakışıyla uyumludur: düşük olasılıklı sürpriz seçimler (değer görünse de) seçilmez.
- Maç başına tek seçim; MBS kuralı uygulanır; kupon olasılığı "bağımsızlık varsayımıyla" hesaplanır.
- Değer koşulu sağlanmazsa kupon üretilmez ("bugün uygun değer kuponu yok").
- Üretilen kuponlar zaman damgasıyla arşivlenir ve sonuçlanınca 1 sanal birimle ileriye dönük ROI izlenir.
"""
from __future__ import annotations

import itertools
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from . import db
from .config import (
    SINGLE_MIN_ODDS, SURPRISE_MAX_EDGE, SURPRISE_MAX_ODDS, SURPRISE_MIN_EDGE, SURPRISE_MIN_EV, SURPRISE_MIN_ODDS,
    SURPRISE_MIN_P, SYSTEM_MIN_ODDS,
    ALLOW_UNVALIDATED_VALUE_COUPONS, COUPON_MIN_PROB, MIN_SELECTION_ODDS, PICK_CS_MIN_ODDS, PICK_CS_MIN_P,
    PICK_GOALS_MIN_ODDS, PICK_GOALS_MIN_P, PICK_MS_MIN_ODDS, PICK_MS_MIN_P, PLAYER_PICK_MAX_P, PLAYER_PICK_MIN_P,
    PLAYER_PICK_MIN_START, VALUE_EV_THRESHOLD, VALUE_MAX_MODEL_MARKET_RATIO, VALUE_MAX_ODDS, VALUE_MIN_ODDS,
)
from .model import markets as mk


@dataclass
class Selection:
    match_id: str
    iddaa_event_id: int
    home: str
    away: str
    league_name: str
    date_utc: str
    market_key: str
    key: str
    label: str
    family: str
    line: str | None
    outcome_no: int
    outcome_name: str
    odd: float
    p_model: float
    p_market: float
    p_blend: float
    ev: float | None
    mbs: int
    confidence: str
    model_version: str = ""
    family_validated: bool = True
    has_market: bool = True     # False: oyuncu tahmini, iddaa'da oranı yok (odd = model adil oranı)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_predictions(con: sqlite3.Connection, days: float, min_lead_minutes: int = 10) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows = con.execute(
        """SELECT p.payload FROM predictions p
           JOIN matches m ON m.id = p.match_id
           WHERE m.state='pre' AND m.date_utc >= ? AND m.date_utc <= ?
             AND p.created_at = (SELECT MAX(created_at) FROM predictions p2 WHERE p2.match_id = p.match_id)
           ORDER BY m.date_utc""",
        (_iso(now + timedelta(minutes=min_lead_minutes)), _iso(now + timedelta(days=days))),
    ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


ODDS_MAX_AGE = timedelta(hours=3)


def _fresh(fetched_at: str | None) -> bool:
    if not fetched_at:
        return False
    t = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    return datetime.now(timezone.utc) - t <= ODDS_MAX_AGE


def candidates(preds: list[dict[str, Any]], require_confidence: bool = True, require_fresh: bool = True) -> list[Selection]:
    out: list[Selection] = []
    for p in preds:
        if not p.get("covered") or not p.get("iddaa"):
            continue
        conf = p["model"]["confidence"]
        if require_confidence and conf in ("düşük", "yok"):
            continue
        for m in p["iddaa"]["markets"]:
            if require_fresh and not _fresh(m.get("fetched_at")):
                continue
            for o in m["outcomes"]:
                if o.get("p_blend") is None or o.get("ev") is None:
                    continue
                out.append(Selection(
                    match_id=p["match"]["id"], iddaa_event_id=p["iddaa"]["event_id"],
                    home=p["match"]["home"]["name"], away=p["match"]["away"]["name"],
                    league_name=p["match"]["league_name"], date_utc=p["match"]["date_utc"],
                    market_key=m["market_key"], key=m["key"], label=m["label"], family=m["family"], line=m["line"],
                    outcome_no=o["no"], outcome_name=o["name"], odd=o["odd"], p_model=o["p_model"],
                    p_market=o["p_market"], p_blend=float(o.get("p_safe", o["p_blend"])), ev=o["ev"],
                    mbs=int(m.get("mbs") or 1), confidence=conf, model_version=str(p.get("model_version", "")),
                    family_validated=bool(m.get("family_validated")),
                ))
    return out


PLAYER_PROPS = (("sot1", "p_sot_1", "Oyuncu 1+ isabetli şut"), ("sot2", "p_sot_2", "Oyuncu 2+ isabetli şut"),
                ("shots3", "p_shots_3", "Oyuncu 3+ şut"), ("goal", "p_goal", "Oyuncu gol atar"))


def model_pick(p: dict[str, Any]) -> Selection | None:
    """Modelin maça bakışını yansıtan tek öneri (bülten, maç sayfası ve yüksek olasılık kuponu aynı kuralı kullanır).

    1) Net favori (model ≥ %50) ve oran ≥ 1.25 -> Maç Sonucu.  Ağır favori (oran < 1.25) -> handikap (favori -1).
    2) Favori net değil -> favoriyi kapsayan çifte şans (≥ %70).
    3) Aksi halde gol pazarları (2.5 Alt/Üst, KG) içinde modelin en emin olduğu (≥ %55).
    Seçim ölçütü model olasılığıdır (sayfada görünen); EV ayrıca gösterilir.
    """
    sels = candidates([p], require_confidence=False, require_fresh=False)
    if not sels:
        return None

    def find(key: str, name: str, line: str | None = None) -> Selection | None:
        return next((c for c in sels if c.key == key and c.outcome_name == name and (line is None or c.line == line)), None)

    ms = [c for c in (find("ms", n) for n in ("1", "0", "2")) if c is not None]
    if ms:
        fav = max(ms, key=lambda c: c.p_model)
        if fav.p_model >= PICK_MS_MIN_P and fav.outcome_name != "0":
            if fav.odd >= PICK_MS_MIN_ODDS:
                return fav
            # ağır favori: handikaplı (favori 1 farkla değil, 2+ farkla kazanmalı) — sov ev sahibine eklenen gol
            hnd = find("hnd", "1", "-1") if fav.outcome_name == "1" else find("hnd", "2", "1")
            if hnd is not None and hnd.p_model >= PICK_MS_MIN_P and hnd.odd >= PICK_MS_MIN_ODDS:
                return hnd
            return fav
        cs_name = {"1": "1 ve 0", "2": "0 ve 2", "0": "1 ve 0" if ms[0].p_model >= ms[-1].p_model else "0 ve 2"}[fav.outcome_name]
        cs = find("cs", cs_name)
        if cs is not None and cs.p_model >= PICK_CS_MIN_P and cs.odd >= PICK_CS_MIN_ODDS:
            return cs
    goals = [c for c in sels if (c.key == "au" and c.line == "2.5") or c.key == "kg"]
    goals = [c for c in goals if c.p_model >= PICK_GOALS_MIN_P and c.odd >= PICK_GOALS_MIN_ODDS]
    return max(goals, key=lambda c: c.p_model) if goals else None


def player_candidates(preds: list[dict[str, Any]]) -> list[Selection]:
    """Simülasyondan oyuncu tahminleri. iddaa bülteninde oyuncu pazarı yok: oran = model adil oranı (1/p), EV yok."""
    out: list[Selection] = []
    for p in preds:
        sim = p.get("sim")
        if not p.get("covered") or not sim or p["model"]["confidence"] in ("düşük", "yok"):
            continue
        for side in ("home", "away"):
            for pl in sim["teams"][side]["players"]:
                if pl["p_start"] < PLAYER_PICK_MIN_START or pl["flags"]:
                    continue
                for code, field, label in PLAYER_PROPS:
                    prob = float(pl[field])
                    if not (PLAYER_PICK_MIN_P <= prob <= PLAYER_PICK_MAX_P):
                        continue
                    out.append(Selection(
                        match_id=p["match"]["id"], iddaa_event_id=int((p.get("iddaa") or {}).get("event_id") or 0),
                        home=p["match"]["home"]["name"], away=p["match"]["away"]["name"],
                        league_name=p["match"]["league_name"], date_utc=p["match"]["date_utc"],
                        market_key=f"oyuncu:{pl['player_id']}:{code}", key="oyuncu", label=label, family="oyuncu",
                        line=None, outcome_no=0, outcome_name=pl["name"], odd=round(1.0 / prob, 2), p_model=prob,
                        p_market=prob, p_blend=prob, ev=None, mbs=1, confidence=p["model"]["confidence"],
                        model_version=str(p.get("model_version", "")), family_validated=True, has_market=False,
                    ))
    return out


def combine(sels: list[Selection]) -> dict[str, Any]:
    odds = float(np.prod([s.odd for s in sels])) if sels else 0.0
    prob = float(np.prod([s.p_blend for s in sels])) if sels else 0.0
    mbs_needed = max((s.mbs for s in sels), default=1)
    warnings: list[str] = []
    if len({s.match_id for s in sels}) != len(sels):
        warnings.append("Aynı maçtan birden fazla seçim: olasılıklar bağımsız değildir, iddaa da kabul etmeyebilir")
    if len(sels) < mbs_needed:
        warnings.append(f"MBS kuralı: bu seçimlerle en az {mbs_needed} maçlık kupon gerekir")
    if any(not s.has_market for s in sels):
        warnings.append("Oyuncu seçimleri iddaa bülteninde yok: oran model adil oranıdır, beklenen değer hesaplanmaz")
    if any(not s.family_validated for s in sels):
        warnings.append("Bazı seçimler backtest'te doğrulanmamış pazar ailelerinden")
    return {
        "selections": [asdict(s) for s in sels],
        "total_odds": odds,
        "prob": prob,
        "ev": (prob * odds - 1.0) if sels and all(s.has_market for s in sels) else None,
        "mbs_required": mbs_needed,
        "mbs_ok": len(sels) >= mbs_needed,
        "independence_assumed": True,
        "warnings": warnings,
    }


def _at_least(ps: list[float], k: int) -> float:
    """Poisson-binom: bağımsız seçimlerde en az k tanesinin tutma olasılığı."""
    dist = [1.0]
    for p in ps:
        nd = [0.0] * (len(dist) + 1)
        for i, v in enumerate(dist):
            nd[i] += v * (1 - p)
            nd[i + 1] += v * p
        dist = nd
    return float(sum(dist[k:]))


def combine_system(sels: list[Selection], k: int) -> dict[str, Any]:
    """Sistem k/n: n seçimden k'lık tüm kombinasyonlar ayrı birer kupon (her biri 1 birim)."""
    base = combine(sels)
    n = len(sels)
    combos = []
    exp_return = 0.0
    for idx in itertools.combinations(range(n), k):
        o = float(np.prod([sels[i].odd for i in idx]))
        pr = float(np.prod([sels[i].p_blend for i in idx]))
        combos.append({"idx": list(idx), "odds": o, "prob": pr})
        exp_return += o * pr
    cost = float(len(combos))
    has_market = all(s.has_market for s in sels)
    base.update({
        "total_odds": sum(c["odds"] for c in combos),       # hepsi tutarsa toplam getiri
        "prob": _at_least([s.p_blend for s in sels], k),     # en az bir kombinasyonun tutma olasılığı
        "ev": (exp_return / cost - 1.0) if has_market and cost else None,
        "mbs_required": max((s.mbs for s in sels), default=1),
        "mbs_ok": all(s.mbs <= k for s in sels),
        "system": {"k": k, "n": n, "combos": combos, "cost": cost, "expected_return": exp_return,
                   "min_win_odds": min(c["odds"] for c in combos) if combos else 0.0},
    })
    if not base["mbs_ok"]:
        base["warnings"].append(f"MBS kuralı: {k}'lı kombinasyonlar bazı seçimlerin MBS'sini sağlamıyor")
    return base


def _best_per_match(cands: list[Selection], score) -> list[Selection]:
    best: dict[str, Selection] = {}
    for c in cands:
        if c.match_id not in best or score(c) > score(best[c.match_id]):
            best[c.match_id] = c
    return sorted(best.values(), key=score, reverse=True)


MAX_SAME_MARKET = 2  # çeşitlilik: bir kuponda aynı pazar türünden en fazla 2 seçim (ortak model hatasına karşı)


def _mix_ok(sels: list[Selection] | tuple[Selection, ...]) -> bool:
    counts: dict[str, int] = {}
    for s in sels:
        counts[s.key] = counts.get(s.key, 0) + 1
    return all(v <= MAX_SAME_MARKET for v in counts.values())


def _fit_mbs(ranked: list[Selection], size: int) -> list[Selection]:
    """Sıralı adaylardan tam 'size' seçim; her seçimin MBS'si kupon boyuna sığmalı ve aynı pazar türünden en fazla
    MAX_SAME_MARKET seçim olmalı. Sağlanamazsa boş liste (geçersiz/kısmi kupon üretilmez)."""
    chosen: list[Selection] = []
    for s in ranked:
        if len(chosen) >= size:
            break
        if s.mbs <= size and _mix_ok([*chosen, s]):
            chosen.append(s)
    return chosen if len(chosen) == size else []


def _best_size(ranked: list[Selection], sizes: tuple[int, ...]) -> list[Selection]:
    for size in sizes:
        sel = _fit_mbs(ranked, size)
        if sel:
            return sel
    return []


def _plausible(c: Selection) -> bool:
    """Model-piyasa ayrışması makul mü (aşırı ayrışma çoğunlukla modelin bilmediği bilgi demektir)."""
    return VALUE_MIN_ODDS <= c.odd <= VALUE_MAX_ODDS and c.p_model <= VALUE_MAX_MODEL_MARKET_RATIO * c.p_market


def _istanbul_day_start_utc() -> datetime:
    """İstanbul (UTC+3, yaz saati yok) gün başlangıcının UTC karşılığı."""
    now_tr = datetime.now(timezone.utc) + timedelta(hours=3)
    return now_tr.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3)


def _blend_status(con: sqlite3.Connection) -> tuple[bool, str]:
    b = db.meta_get(con, "blend_calibration") or {}
    if isinstance(b, dict) and b.get("validated"):
        return True, ""
    n = int(b.get("n", 0)) if isinstance(b, dict) else 0
    req = int(b.get("required", 0)) if isinstance(b, dict) else 0
    if isinstance(b, dict) and b.get("status") == "dogrulanamadi":
        return False, "Model-piyasa harmanı ayrı dilimde piyasadan iyi çıkmadı: değer iddiası yapılmıyor."
    return False, (
        f"Değer iddiası için harmanın ileriye dönük doğrulanması gerekiyor: {n}/{req or '–'} sonuçlanmış, oranı arşivli maç. "
        "Arşiv her güncellemede büyüyor."
    )


def live_odds(con: sqlite3.Connection) -> dict[tuple[int, str, int], float]:
    """Şu an satışta olan (aktif, canlı olmayan) etkinliklerin güncel oranları."""
    rows = con.execute(
        """SELECT o.event_id, o.market_key, o.outcome_no, o.odd FROM odds_current o
           JOIN iddaa_events e ON e.id=o.event_id WHERE e.active=1 AND e.is_live=0"""
    ).fetchall()
    return {(int(r["event_id"]), r["market_key"], int(r["outcome_no"])): float(r["odd"]) for r in rows}


def _still_offered(c: Selection, live: dict[tuple[int, str, int], float]) -> bool:
    cur = live.get((c.iddaa_event_id, c.market_key, c.outcome_no))
    return cur is not None and abs(cur - c.odd) < 1e-9


def _current_weight(con: sqlite3.Connection) -> float:
    from .model.pipeline import _blend_weight

    return _blend_weight(con)[0]


def scout_approved(con: sqlite3.Connection, preds: list[dict[str, Any]]) -> dict[tuple[str, str, str], Selection]:
    """Scout hükmü "öneri" olan maçların önerilen seçimi: (maç, pazar anahtarı, sonuç) -> aday seçim."""
    from .context import cached_context  # geç içe aktarma: context -> scout -> coupons

    out: dict[tuple[str, str, str], Selection] = {}
    for p in preds:
        if not p.get("covered") or not p.get("iddaa"):
            continue
        pick = ((cached_context(con, p)["scout"] or {}).get("verdict") or {}).get("pick")
        if not pick:
            continue
        sel = next((c for c in candidates([p], require_confidence=False, require_fresh=False)
                    if c.market_key == pick["market_key"] and c.outcome_name == pick["selection"]), None)
        if sel is not None:
            out[(sel.match_id, sel.market_key, sel.outcome_name)] = sel
    return out


def generate(con: sqlite3.Connection, days: float = 3.0, archive: bool = False) -> dict[str, Any]:
    w_now = _current_weight(con)
    # Yalnızca güncel harman ağırlığıyla hesaplanmış tahminler (kalibrasyon sonrası eski tahminler kullanılmaz)
    preds = [p for p in latest_predictions(con, days) if abs(float((p.get("model") or {}).get("blend_weight", -1)) - w_now) < 1e-9]
    validated = db.meta_get(con, "family_validation") or {}
    blend_ok, blend_reason = _blend_status(con)
    experimental = not blend_ok and ALLOW_UNVALIDATED_VALUE_COUPONS
    value_on = blend_ok or experimental
    exp_note = (" DENEYSEL: model-piyasa harmanı henüz ileriye dönük doğrulanmadı; beklenen değer tahmini güvenilir değildir."
                if experimental else "")
    live = live_odds(con)
    # Kullanıcı tercihi (16 Eki 2026): kuponlara yalnız scout'un onayladığı seçimler girer (kanıtlar aynı yönde).
    approved = scout_approved(con, preds)
    scout_matches = {k[0] for k in approved}
    # Tahmin anındaki oran hâlâ bültende ve aynıysa aday olur (kalkmış/değişmiş oranla kupon yok)
    cands = [c for c in candidates(preds) if c.odd >= MIN_SELECTION_ODDS and _still_offered(c, live)
             and (c.match_id, c.market_key, c.outcome_name) in approved]
    kinds: list[dict[str, Any]] = []

    # 1) Değer kuponu: modelle uyumlu (olasılık ≥ %40), makul oranlı ve harmanlı EV'si eşiği geçen seçimler
    sel: list[Selection] = []
    reason: str | None = blend_reason or None
    if value_on:
        value = [c for c in cands if c.ev is not None and c.ev >= VALUE_EV_THRESHOLD and c.p_model * c.odd - 1 > 0
                 and c.p_blend >= COUPON_MIN_PROB and _plausible(c)]
        sel = _best_size(_best_per_match(value, lambda c: c.ev or 0.0), (3, 2, 1))
        reason = None if sel else "Bugün modelle uyumlu ve eşiği geçen değerli seçim yok. Zorla kupon üretilmedi."
    kinds.append({
        "kind": "deger", "title": "Değer kuponu",
        "description": f"Tüm pazarlardan, olasılığı ≥ %{COUPON_MIN_PROB * 100:.0f}, oranı {VALUE_MIN_ODDS:.2f}–{VALUE_MAX_ODDS:.2f} ve beklenen değeri ≥ %{VALUE_EV_THRESHOLD * 100:.0f} olan seçimler.{exp_note}",
        "experimental": experimental,
        "empty_reason": reason,
        **combine(sel),
    })

    # 2) Yüksek olasılık kuponu: maçların model önerileri (bültendekiyle aynı), en emin olunan 3 maç
    hp = [pk for pk in approved.values() if pk.odd >= MIN_SELECTION_ODDS and _still_offered(pk, live)]
    sel = _best_size(sorted(hp, key=lambda c: c.p_model, reverse=True), (3,))
    kinds.append({
        "kind": "olasilik", "title": "Yüksek olasılık kuponu", "experimental": False,
        "description": "Önerilerden modelin en emin olduğu 3 maç (net favori -> maç sonucu, değilse çifte şans ya da gol pazarı). Yüksek tutma olasılığı değer anlamına gelmez.",
        "empty_reason": None if sel else "Scout'un onayladığı, MBS'yi sağlayan 3 seçim yok.",
        **combine(sel),
    })

    # 3) Dengeli: modelle uyumlu seçimlerden, P(kupon) ≥ %25 olan en yüksek EV'li 2-3'lü kombinasyon
    best_combo: tuple[float, list[Selection]] = (-1e9, [])
    if value_on:
        pool = _best_per_match([c for c in cands if c.ev is not None and c.ev >= 0.0 and c.p_blend >= COUPON_MIN_PROB
                                and _plausible(c)], lambda c: c.ev or 0.0)[:14]
        for size in (2, 3):
            for combo in itertools.combinations(pool, size):
                if max(c.mbs for c in combo) > size or not _mix_ok(combo):
                    continue
                r = combine(list(combo))
                if r["prob"] >= 0.25 and r["ev"] is not None and r["ev"] > best_combo[0]:
                    best_combo = (r["ev"], list(combo))
    kinds.append({
        "kind": "dengeli", "title": "Dengeli kupon",
        "description": f"Olasılığı ≥ %{COUPON_MIN_PROB * 100:.0f} seçimlerden, kupon olasılığı ≥ %25 olan 2-3 maçlık en yüksek beklenen değerli kombinasyon.{exp_note}",
        "experimental": experimental,
        "empty_reason": (None if best_combo[1] else "Koşulları sağlayan kombinasyon yok.") if value_on else blend_reason,
        **combine(best_combo[1]),
    })

    # 4) Tekli: bültendeki önerilerden MBS 1 olan, oranı ≥ 1.50 ve modelin en emin olduğu tek seçim
    singles = sorted([c for c in hp if c.mbs <= 1 and c.odd >= SINGLE_MIN_ODDS], key=lambda c: c.p_model, reverse=True)
    sel = singles[:1]
    kinds.append({
        "kind": "tekli", "title": "Günün tekli seçimi", "experimental": False,
        "description": f"Tek maçlık kupon (MBS 1): model önerileri içinde oranı ≥ {SINGLE_MIN_ODDS:.2f} olan en emin seçim. Kesinti tek seferlik ödendiği için uzun kuponlardan çok daha sık tutar.",
        "empty_reason": None if sel else "MBS 1 olan uygun seçim yok.",
        **combine(sel),
    })

    # 5) Sistem kuponları: önerilerden, oranı ≥ 1.40 olan en emin seçimler; 2/3 ve 3/4
    sys_pool = sorted([c for c in hp if c.odd >= SYSTEM_MIN_ODDS], key=lambda c: c.p_model, reverse=True)
    for k_, n_ in ((2, 3), (3, 4)):
        chosen = _fit_mbs([c for c in sys_pool if c.mbs <= k_], n_)
        ok = len(chosen) == n_
        kinds.append({
            "kind": f"sistem_{k_}_{n_}", "title": f"Sistem {k_}/{n_}", "experimental": False,
            "description": (f"{n_} öneriden {k_}'li tüm kombinasyonlar ({len(list(itertools.combinations(range(n_), k_)))} kupon). "
                            f"Seçimlerin en az {k_} tanesi tutarsa kazanç var; bir seçim yatsa da kupon yanmaz."),
            "empty_reason": None if ok else "Yeterli uygun öneri yok.",
            **(combine_system(chosen, k_) if ok else combine([])),
        })

    # 6) Sürpriz: yüksek oranlı, modelin piyasadan belirgin daha fazla inandığı ama makul seçimler (2-3 maç)
    sur = [c for c in cands if c.ev is not None and SURPRISE_MIN_ODDS <= c.odd <= SURPRISE_MAX_ODDS
           and c.p_model >= SURPRISE_MIN_P and SURPRISE_MIN_EDGE * c.p_market <= c.p_model <= SURPRISE_MAX_EDGE * c.p_market
           and c.ev >= SURPRISE_MIN_EV]
    sel = _best_size(_best_per_match(sur, lambda c: c.ev or 0.0), (3, 2))
    kinds.append({
        "kind": "surpriz", "title": "Sürpriz kupon", "experimental": not blend_ok,
        "description": (f"Oranı {SURPRISE_MIN_ODDS:.2f}–{SURPRISE_MAX_ODDS:.2f} arası, modelin piyasadan en az %{(SURPRISE_MIN_EDGE - 1) * 100:.0f} "
                        "daha fazla inandığı seçimler. Tutma olasılığı düşüktür; küçük miktarla oynanmalı."),
        "empty_reason": None if sel else "Koşulları sağlayan sürpriz seçim yok.",
        **combine(sel),
    })

    # 7) Oyuncu kuponu: simülasyondan, farklı maçlardan en olası oyuncu tahminleri (adil oranla)
    ranked_players = _best_per_match([c for c in player_candidates(preds) if c.match_id in scout_matches],
                                     lambda c: c.p_blend)
    sel = ranked_players[:3] if len(ranked_players) >= 3 else []
    kinds.append({
        "kind": "oyuncu", "title": "Oyuncu kuponu", "experimental": False,
        "description": (f"Maç simülasyonundan isabetli şut / şut / gol tahminleri (ilk 11 olasılığı ≥ %{PLAYER_PICK_MIN_START * 100:.0f}, "
                        f"olasılık %{PLAYER_PICK_MIN_P * 100:.0f}–%{PLAYER_PICK_MAX_P * 100:.0f}). iddaa bülteninde oyuncu pazarı "
                        "olmadığından oranlar model adil oranıdır; oynamadan önce kendi sitende kontrol et."),
        "empty_reason": None if sel else "Uygun oyuncu tahmini yok.",
        **combine(sel),
    })

    for k in kinds:
        k["description"] = f"Yalnız scout'un onayladığı seçimler (kanıtlar aynı yönde). {k['description']}"
        k["scout_gated"] = True

    created = _iso(datetime.now(timezone.utc))
    # "Günün kuponu": her tür için İstanbul gününde ilk oluşturulan (boş olmayan) kupon kilitlenir ve gün boyu
    # gösterilir; oranlar/model her güncellemede biraz değişse de kupon değişmez, geçmişe günde tür başına tek kayıt düşer.
    day_start = _istanbul_day_start_utc()
    for i, k in enumerate(kinds):
        locked = con.execute(
            "SELECT id, created_at, payload FROM coupons WHERE kind=? AND created_at >= ? ORDER BY created_at LIMIT 1",
            (k["kind"], _iso(day_start)),
        ).fetchone()
        if locked is not None:
            stored = json.loads(locked["payload"])
            stored.pop("sig", None)
            kinds[i] = {**stored, "archived_id": locked["id"], "locked_at": locked["created_at"]}
            continue
        if not archive or not k["selections"] or not k["mbs_ok"]:
            continue
        sig = sorted((s_["match_id"], s_["market_key"], s_["outcome_no"]) for s_ in k["selections"])
        stake = float(k["system"]["cost"]) if k.get("system") else 1.0
        with db.tx(con):
            cur = con.execute(
                "INSERT INTO coupons(created_at, kind, stake, total_odds, prob, ev, payload) VALUES(?,?,?,?,?,?,?)",
                (created, k["kind"], stake, k["total_odds"], k["prob"], k["ev"] if k["ev"] is not None else 0.0,
                 json.dumps({**k, "sig": sig}, ensure_ascii=False)),
            )
        k["archived_id"] = cur.lastrowid
        k["locked_at"] = created
    return {
        "created_at": created,
        "days": days,
        "n_matches_considered": len(preds),
        "n_candidates": len(cands),
        "family_validation": validated,
        "blend_validated": blend_ok,
        "coupons": kinds,
    }


def evaluate_custom(con: sqlite3.Connection, picks: list[dict[str, Any]]) -> dict[str, Any]:
    """Kullanıcının kendi seçtiği (maç, pazar, sonuç) listesini değerlendirir."""
    preds = {p["match"]["id"]: p for p in latest_predictions(con, days=14, min_lead_minutes=0)}
    sels: list[Selection] = []
    missing: list[str] = []
    for pk in picks:
        p = preds.get(str(pk.get("match_id")))
        if not p or not p.get("iddaa"):
            missing.append(str(pk.get("match_id")))
            continue
        found = None
        live = live_odds(con)
        for c in candidates([p], require_confidence=False, require_fresh=True):
            if not _still_offered(c, live):
                continue
            if c.market_key == pk.get("market_key") and c.outcome_no == int(pk.get("outcome_no", -1)):
                found = c
        if found is None:
            missing.append(f"{pk.get('match_id')}:{pk.get('market_key')}:{pk.get('outcome_no')}")
        else:
            sels.append(found)
    res = combine(sels)
    res["missing"] = missing
    return res


# ---------------------------------------------------------------- sonuçlandırma

def settle_selection(con: sqlite3.Connection, s: dict[str, Any]) -> str | None:
    m = con.execute("SELECT * FROM matches WHERE id=?", (s["match_id"],)).fetchone()
    if m is None:
        return None
    if m["state"] == "post" and not m["completed"]:
        return "void"  # ertelendi / iptal: iddaa kuralında oran 1.00 sayılır
    if s["key"] == "oyuncu":
        return _settle_player(con, m, s)
    if not m["completed"] or m["ft90_home"] is None:
        return None  # 90 dk skoru doğrulanmadan (ör. uzatmalı maç, özet yok) sonuçlandırılmaz
    if s["key"] == "korner_au":
        if m["extra_time"]:
            return None  # korner istatistiği uzatmayı da içerir; 90 dk değeri bilinmiyor
        rows = con.execute("SELECT corners FROM team_match_stats WHERE match_id=?", (m["id"],)).fetchall()
        if len(rows) != 2 or any(r["corners"] is None for r in rows):
            return None
        tot = sum(r["corners"] for r in rows)
        line = float(s["line"])
        return "won" if (s["outcome_name"] == "Üst" and tot > line) or (s["outcome_name"] == "Alt" and tot < line) else "lost"
    needs_ht = s["family"] == "iy" or s["key"] in ("iy", "iy2", "iy_cs", "iy_kg", "iy_au", "iyms", "cgy")
    if needs_ht and m["home_ht"] is None:
        return None
    X = np.array(int(m["ft90_home"]))
    Y = np.array(int(m["ft90_away"]))
    I = np.array(int(m["home_ht"] or 0))
    J = np.array(int(m["away_ht"] or 0))
    j = mk.Joint(np.array(1.0), X, Y, I, J)
    mask = mk.outcome_mask(s["key"], s["line"], s["outcome_name"], j)
    if mask is None:
        return None
    return "won" if bool(mask) else "lost"


_PLAYER_RULES = {"sot1": ("shots_on_target", 1), "sot2": ("shots_on_target", 2), "shots2": ("shots", 2),
                 "shots3": ("shots", 3), "goal": ("goals", 1)}


def _settle_player(con: sqlite3.Connection, m: sqlite3.Row, s: dict[str, Any]) -> str | None:
    if not m["completed"] or m["summary_status"] != "ok" or m["extra_time"]:
        return None  # oyuncu istatistiği yok ya da uzatmayı içeriyor
    _, pid, code = s["market_key"].split(":")
    col, need = _PLAYER_RULES[code]
    r = con.execute(f"SELECT minutes, {col} v FROM player_match WHERE match_id=? AND player_id=?", (m["id"], pid)).fetchone()
    if r is None or (r["minutes"] or 0) == 0:
        return "void"  # oyuncu oynamadı: iade
    if r["v"] is None:
        return None
    return "won" if int(r["v"]) >= need else "lost"


def settle(con: sqlite3.Connection) -> dict[str, int]:
    rows = con.execute("SELECT id, payload FROM coupons WHERE status='open'").fetchall()
    settled = 0
    now = _iso(datetime.now(timezone.utc))
    with db.tx(con):
        for r in rows:
            payload = json.loads(r["payload"])
            results = [settle_selection(con, s) for s in payload["selections"]]
            if any(x is None for x in results):
                if "lost" in results and not payload.get("system"):
                    con.execute("UPDATE coupons SET status='lost', settled_at=? WHERE id=?", (now, r["id"]))
                    settled += 1
                continue
            payload["selection_results"] = results
            if payload.get("system"):
                # her kombinasyon ayrı kupon: tümü tutarsa oran çarpımı, iade seçim 1.00 sayılır
                total = 0.0
                for cb in payload["system"]["combos"]:
                    rs = [results[i] for i in cb["idx"]]
                    if "lost" in rs:
                        continue
                    total += float(np.prod([payload["selections"][i]["odd"] if results[i] == "won" else 1.0 for i in cb["idx"]]))
                cost = float(payload["system"]["cost"])
                status = "void" if all(x == "void" for x in results) else ("won" if total > 0 else "lost")
                payout = total / cost if cost else 0.0   # birim başına getiri (stake = kombinasyon sayısı)
            else:
                status = "lost" if "lost" in results else ("void" if all(x == "void" for x in results) else "won")
                payout = 0.0
                if status == "won":
                    payout = float(np.prod([s["odd"] for s, x in zip(payload["selections"], results) if x == "won"]))
                if status == "void":
                    payout = 1.0
            payload["payout"] = payout
            con.execute("UPDATE coupons SET status=?, settled_at=?, payload=? WHERE id=?",
                        (status, now, json.dumps(payload, ensure_ascii=False), r["id"]))
            settled += 1
    return {"open": len(rows), "settled": settled}


def history(con: sqlite3.Connection, limit: int = 200) -> dict[str, Any]:
    rows = con.execute("SELECT * FROM coupons ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    items = []
    by_kind: dict[str, dict[str, float]] = {}
    for r in rows:
        p = json.loads(r["payload"])
        items.append({
            "id": r["id"], "created_at": r["created_at"], "kind": r["kind"], "status": r["status"],
            "settled_at": r["settled_at"], "total_odds": r["total_odds"], "prob": r["prob"], "ev": r["ev"],
            "stake": r["stake"], "payout": p.get("payout"), "selections": p["selections"],
            "selection_results": p.get("selection_results"), "experimental": bool(p.get("experimental")),
            "system": p.get("system"),
        })
        k = by_kind.setdefault(r["kind"], {"n": 0, "settled": 0, "won": 0, "staked": 0.0, "returned": 0.0, "expected_hits": 0.0})
        k["n"] += 1
        if r["status"] in ("won", "lost", "void"):
            k["settled"] += 1
            k["staked"] += r["stake"]
            k["returned"] += r["stake"] * float(p.get("payout") or 0.0)
            k["won"] += int(r["status"] == "won")
            k["expected_hits"] += r["prob"]
    for k in by_kind.values():
        k["roi"] = (k["returned"] - k["staked"]) / k["staked"] if k["staked"] else None
    return {"items": items, "summary": by_kind}


def dedupe_daily_coupons(con: sqlite3.Connection) -> int:
    """Eski sürümden kalan mükerrer kayıtlar: her tür için İstanbul gününün yalnızca ilk kuponu kalır (idempotent)."""
    rows = con.execute("SELECT id, kind, created_at, status FROM coupons ORDER BY created_at").fetchall()
    seen: set[tuple[str, str]] = set()
    drop: list[int] = []
    for r in rows:
        day = (datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) + timedelta(hours=3)).strftime("%Y-%m-%d")
        key = (r["kind"], day)
        if key in seen and r["status"] == "open":
            drop.append(int(r["id"]))
        seen.add(key)
    if drop:
        with db.tx(con):
            con.executemany("DELETE FROM coupons WHERE id=?", [(i,) for i in drop])
    return len(drop)


# geriye dönük ad
_settle_selection = settle_selection
