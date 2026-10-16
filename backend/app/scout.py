"""Scout raporu: maç başına kanıta dayalı, gerekçeli değerlendirme ve hüküm.

Tahmin yükü (pipeline.predict_match + api.match_detail eklemeleri), puan durumu, karşılıklı geçmiş, son form ve
(varsa) benzer oranlı geçmiş maçlar ayrı kanıt bölümlerine ayrılır. Her madde hangi tarafı desteklediğini
("home" | "away" | "draw" | "goals_over" | "goals_under" | "neutral") ve 0-1 arası ağırlığını taşır.

Hüküm kuralı:
- Öneri yalnızca bölümler aynı yönü gösterdiğinde verilir; çelişki, zayıf veri ya da yüksek risk varsa açık "pas".
- Öneri modelin kendi önerisiyle (coupons.model_pick) çelişmez: ya aynı seçimdir ya da aynı yönde daha temkinli
  karşılığıdır (handikap -> maç sonucu, maç sonucu -> çifte şans). Sonuç ekseni çelişkiliyse ve gol ekseninde güçlü
  uyum varsa modelin eşiklerini geçen bir gol pazarı (2.5 Alt/Üst, KG) önerilebilir.
- Model, piyasa ve simülasyon aynı veri ailesinden beslenir; bu yüzden en az bir BAĞIMSIZ bölümün (form, lig
  konumu, karşılıklı geçmiş) aynı yönü göstermesi şarttır.
Harici servis yok; her cümle veriden kurulur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from .config import LEAGUE_BY_SLUG, PICK_CS_MIN_ODDS, PICK_CS_MIN_P, PICK_GOALS_MIN_ODDS, PICK_GOALS_MIN_P
from .coupons import Selection, candidates, model_pick

SCOUT_VERSION = "scout-v1"

Side = Literal["home", "away", "draw", "goals_over", "goals_under", "neutral"]
SIDES: tuple[str, ...] = ("home", "away", "draw", "goals_over", "goals_under", "neutral")

# ---------------------------------------------------------------- eşikler (config.py'ye dokunmadan, yalnız scout için)

W_FLOOR = 0.25                  # eşiği geçen bir maddenin en düşük ağırlığı (ağırlık eşikte W_FLOOR, tam noktada 1)

# Güç dengesi
GUC_LAMBDA_DIFF_MIN = 0.25      # beklenen gol farkı bunun altındaysa güçler dengede
GUC_LAMBDA_DIFF_FULL = 1.20
GUC_FAV_MIN_P = 0.45            # favori sayılmak için MS olasılığı
GUC_FAV_MIN_MARGIN = 0.12       # favorinin rakip galibiyetine üstünlüğü
GUC_FAV_FULL_P = 0.70
GUC_DRAW_HIGH_P = 0.29          # beraberlik olasılığı bunun üstünde ve taraflar dengedeyse beraberlik sinyali
GUC_DRAW_BALANCE = 0.10
GOALS_OVER_P = 0.57             # 2.5 Üst olasılığı (model ya da piyasa) bunun üstündeyse bol gol sinyali
GOALS_UNDER_P = 0.43
GOALS_P_FULL = 0.20             # eşikten bu kadar uzakta ağırlık 1
KG_YES_P = 0.57                 # karşılıklı gol "var" olasılığı bunun üstündeyse bol gol, KG_NO_P altındaysa az gol
KG_NO_P = 0.43
KG_SCALE = 0.7                  # KG, 2.5 çizgisinden zayıf bir gol göstergesi: ağırlığı bu katla
LINEUP_ADJ_NOTABLE = 0.03       # resmi ilk 11 çarpanı 1'den en az bu kadar saparsa anlatılır
LINEUP_ADJ_FULL = 0.12

# Form
FORM_MIN_MATCHES = 4
FORM_PPG_DIFF_MIN = 0.50
FORM_PPG_DIFF_FULL = 1.60
FORM_VENUE_MIN_N = 2
FORM_VENUE_SCALE = 0.7          # iç saha/deplasman ayrımı küçük örneklem: ağırlık bu katla sınırlanır
FORM_GOALS_HIGH = 3.0
FORM_GOALS_LOW = 2.2
FORM_GOALS_FULL = 0.8
FORM_GOALS_SCALE = 0.6
FORM_WIN_STREAK = 3
FORM_LOSS_STREAK = 3
FORM_UNBEATEN = 5
FORM_WINLESS = 4
FORM_STREAK_WEIGHT = 0.3

# Lig konumu
LEAGUE_MIN_PLAYED = 5           # bundan az maçta tablo henüz oturmamış sayılır
LEAGUE_EARLY_FACTOR = 0.5
LEAGUE_PPG_DIFF_MIN = 0.35
LEAGUE_PPG_DIFF_FULL = 1.20
LEAGUE_GDPG_DIFF_MIN = 0.50
LEAGUE_GDPG_DIFF_FULL = 1.50
LEAGUE_GD_SCALE = 0.6
LEAGUE_GOALS_HIGH = 3.0
LEAGUE_GOALS_LOW = 2.3
LEAGUE_GOALS_FULL = 0.8
LEAGUE_GOALS_SCALE = 0.5
LEAGUE_ZONE_GAP = 3             # bölge çizgisine bu kadar puan yakınlık "hat mücadelesi" sayılır
LATE_SEASON_SHARE = 0.75        # oynanan maç / tahmini toplam maç bu orandan büyükse sezon sonu
MOTIVATION_WEIGHT = 0.25

# Karşılıklı geçmiş
H2H_MIN_MATCHES = 2
H2H_SIDE_MIN_MATCHES = 3
H2H_WIN_DIFF_MIN = 2
H2H_WIN_DIFF_FULL = 4
H2H_MAX_WEIGHT = 0.5            # eşleşme geçmişi zayıf kanıttır: ağırlığı tavanlı
H2H_STALE_DAYS = 3 * 365
H2H_STALE_FACTOR = 0.5
H2H_GOALS_HIGH = 3.0
H2H_GOALS_LOW = 2.0
H2H_GOALS_WEIGHT = 0.3

# Hücum/savunma profili ve oyuncular
PROFILE_SOT_SHARE_MIN = 0.58    # isabetli şut payı bunun üstündeyse o taraf baskın
PROFILE_SOT_SHARE_FULL = 0.72
PROFILE_START_MIN = 0.5
PROFILE_TOP_N = 2
KEY_MIN_MINUTES = 900           # kilit oyuncu adayı için görülen dakika
KEY_TOP_N = 3                   # takımın 90 dk başı gol katkısında ilk N
KEY_ABSENT_START = 0.25         # ilk 11 olasılığı bunun altındaysa "eksik" sayılır
KEY_ABSENCE_WEIGHT = 0.35
KEY_LONG_ABSENCE = 6            # bu kadar maçtır kadroda olmayan oyuncu gitmiş sayılır (takım zaten onsuz oynuyor)

# Piyasa
MARKET_FAV_MIN_P = 0.45
MARKET_FAV_MIN_MARGIN = 0.12
MARKET_FAV_FULL_P = 0.70
MARKET_GAP_WARN = 0.06          # model ile piyasa favori olasılığında bu farktan sonra "ayrışma" anlatılır
ODDS_MOVE_MIN = 0.03            # oran göreli değişimi
ODDS_MOVE_FULL = 0.12
ODDS_MOVE_MAX_WEIGHT = 0.5
SIMILAR_MIN_N = 30
SIMILAR_EDGE_MIN = 0.05         # benzer maçlardaki gerçekleşme - piyasa olasılığı
SIMILAR_EDGE_FULL = 0.15
SIMILAR_MAX_WEIGHT = 0.4

# Riskler (ağırlık = önem)
RISK_LOW_CONF = 1.0
RISK_MID_CONF = 0.5
RISK_CUP = 0.3
RISK_NEUTRAL = 0.25
RISK_THIN_FORM = 0.3
RISK_MARKET_GAP = 0.4
MARKET_GAP_RISK = 0.12
RISK_CONGESTION = 0.25
CONGESTION_DAYS = 3.5
RISK_EARLY_SEASON = 0.2
RISK_SIM_NOTE = 0.15
RISK_KEY_DOUBT = 0.2
RISK_CAP_TOTAL = 0.5            # toplam risk bunu geçerse güven en fazla "orta"
RISK_PAS_TOTAL = 1.0            # toplam risk bunu geçerse pas

# Hüküm
AGREE_MIN_NET = 0.2             # bölüm net desteği bu eşiği geçerse "aynı yönde", -eşik altındaysa "karşı"
SECTION_NET_CAP = 1.5
DRAW_AGAINST_FACTOR = 0.5       # maç sonucu seçiminde beraberlik sinyali karşı kanıt sayılır (yarım ağırlık)
DRAW_FOR_CS_FACTOR = 0.5        # çifte şansta beraberlik sinyali destek sayılır
DRAW_DOWNGRADE_TOTAL = 0.6      # orta güvende beraberlik sinyalleri bu toplamı geçerse MS yerine çifte şans
STRONG_MIN_AGREE = 4
STRONG_MIN_INDEPENDENT = 2
MEDIUM_MIN_AGREE = 3
MEDIUM_MIN_MARGIN = 2
CONFLICT_MIN_DISAGREE = 2
MIN_EVIDENCE_SECTIONS = 2       # model dışı veri taşıyan en az bu kadar bölüm olmalı
INDEPENDENT_SECTIONS = ("form", "lig", "h2h")
EVIDENCE_SECTIONS = ("guc", "form", "lig", "h2h", "profil", "piyasa")
GOALS_SECTIONS = ("guc", "form", "lig", "h2h", "piyasa")   # gol ekseninde sinyal üretebilen bölümler

TITLES = {
    "guc": "Güç dengesi", "form": "Form", "lig": "Lig konumu", "h2h": "Karşılıklı geçmiş",
    "profil": "Hücum/savunma profili", "piyasa": "Piyasa", "risk": "Riskler",
}
POS_TR = {"G": "kaleci", "D": "defans", "M": "orta saha", "F": "forvet"}
OPPOSITE: dict[str, str] = {"home": "away", "away": "home", "goals_over": "goals_under", "goals_under": "goals_over"}


# ---------------------------------------------------------------- küçük yardımcılar

@dataclass(frozen=True)
class _Ctx:
    match_id: str
    home_id: str
    away_id: str
    home: str
    away: str
    kickoff: datetime | None
    league: str
    league_name: str
    neutral: bool
    is_cup: bool

    def name(self, side: str) -> str:
        return self.home if side == "home" else self.away


def _item(text: str, side: Side, weight: float = 0.0) -> dict[str, Any]:
    w = 0.0 if side == "neutral" and weight <= 0 else min(max(float(weight), 0.0), 1.0)
    return {"text": text, "side": side, "weight": round(w, 3)}


def _strength(x: float, lo: float, full: float) -> float:
    """Eşik altı 0; eşikte W_FLOOR, 'full' noktasında 1 (doğrusal)."""
    if x < lo:
        return 0.0
    if full <= lo:
        return 1.0
    return W_FLOOR + (1.0 - W_FLOOR) * min(1.0, (x - lo) / (full - lo))


def _pct(p: float) -> str:
    return f"%{p * 100:.0f}"


def _dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _date_tr(d: datetime) -> str:
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def _join(xs: list[str]) -> str:
    xs = [x for x in xs if x]
    if not xs:
        return ""
    if len(xs) == 1:
        return xs[0]
    return ", ".join(xs[:-1]) + " ve " + xs[-1]


def _section(key: str, items: list[dict[str, Any]], available: bool, note: str | None = None) -> dict[str, Any]:
    return {"key": key, "title": TITLES[key], "available": available, "note": note, "items": items}


def _std_probs(payload: dict[str, Any], key: str, line: str | None = None) -> dict[str, float]:
    for m in payload.get("markets") or []:
        if m.get("key") == key and m.get("line") == line:
            return {o["name"]: float(o["p_model"]) for o in m.get("outcomes") or []}
    return {}


def _iddaa_market(payload: dict[str, Any], key: str, line: str | None = None) -> dict[str, Any] | None:
    for m in (payload.get("iddaa") or {}).get("markets") or []:
        if m.get("key") == key and m.get("line") == line:
            return m
    return None


def _side(s: str) -> Side:
    return cast(Side, s) if s in SIDES else "neutral"


def _ms_side(name: str) -> Side:
    return _side({"1": "home", "0": "draw", "2": "away"}.get(name, "neutral"))


# ---------------------------------------------------------------- 1) güç dengesi

def _section_guc(payload: dict[str, Any], c: _Ctx) -> dict[str, Any]:
    m = payload.get("model")
    if not payload.get("covered") or not m:
        return _section("guc", [], False, payload.get("coverage_note") or "Model bu maçı kapsamıyor.")
    items: list[dict[str, Any]] = []
    lh, la = float(m["lambda_home"]), float(m["lambda_away"])
    diff = lh - la
    venue = "tarafsız sahada" if c.neutral else "ev sahibi avantajı dahil"
    if abs(diff) >= GUC_LAMBDA_DIFF_MIN:
        side: Side = "home" if diff > 0 else "away"
        lead = c.name(side)
        ratio = max(lh, la) / max(min(lh, la), 1e-6)
        tone = "neredeyse iki katı" if ratio >= 1.8 else ("belirgin biçimde fazla" if ratio >= 1.4 else "biraz fazla")
        items.append(_item(
            f"Beklenen gol {c.home} {lh:.2f}, {c.away} {la:.2f} ({venue}): {lead} tarafının üretimi rakibin {tone}.",
            side, _strength(abs(diff), GUC_LAMBDA_DIFF_MIN, GUC_LAMBDA_DIFF_FULL)))
    else:
        items.append(_item(f"Beklenen goller birbirine çok yakın: {c.home} {lh:.2f}, {c.away} {la:.2f} ({venue}).", "neutral"))

    ms = _std_probs(payload, "ms")
    if ms:
        p1, p0, p2 = ms.get("1", 0.0), ms.get("0", 0.0), ms.get("2", 0.0)
        fav_side: Side = "home" if p1 >= p2 else "away"
        p_fav, p_oth = max(p1, p2), min(p1, p2)
        base = f"MS olasılıkları {c.home} {_pct(p1)}, beraberlik {_pct(p0)}, {c.away} {_pct(p2)}"
        if p_fav >= GUC_FAV_MIN_P and p_fav - p_oth >= GUC_FAV_MIN_MARGIN:
            items.append(_item(f"{base}; model {c.name(fav_side)} tarafında net.", fav_side,
                               _strength(p_fav, GUC_FAV_MIN_P, GUC_FAV_FULL_P)))
        elif p0 >= GUC_DRAW_HIGH_P and abs(p1 - p2) <= GUC_DRAW_BALANCE:
            items.append(_item(f"{base}; taraflar dengede, beraberlik ihtimali yüksek.", "draw",
                               _strength(p0, GUC_DRAW_HIGH_P, GUC_DRAW_HIGH_P + 0.06)))
        else:
            items.append(_item(f"{base}; belirgin bir favori yok.", "neutral"))

    au = _std_probs(payload, "au", "2.5")
    over = au.get("Üst")
    if over is not None:
        top = (payload.get("top_scores") or [None])[0]
        tail = f", en olası skor {top['home']}-{top['away']} ({_pct(float(top['p']))})" if top else ""
        tot = lh + la
        if over >= GOALS_OVER_P:
            items.append(_item(f"Toplam {tot:.1f} gol beklentisiyle 2.5 Üst {_pct(over)}{tail}.", "goals_over",
                               _strength(over, GOALS_OVER_P, GOALS_OVER_P + GOALS_P_FULL)))
        elif over <= GOALS_UNDER_P:
            items.append(_item(f"Toplam beklenti {tot:.1f} gol; 2.5 Alt {_pct(1 - over)}{tail}.", "goals_under",
                               _strength(1 - over, 1 - GOALS_UNDER_P, 1 - GOALS_UNDER_P + GOALS_P_FULL)))
        else:
            items.append(_item(f"Gol beklentisi ortada ({tot:.1f}); 2.5 Üst {_pct(over)}{tail}.", "neutral"))

    kg = _std_probs(payload, "kg").get("Var")
    if kg is not None:
        items.append(_kg_item(kg, f"Model karşılıklı gol için {_pct(kg)}", c))

    adj = m.get("lineup_adj") or {}
    if float(adj.get("beta") or 0.0) > 0:
        for s in ("home", "away"):
            f = float(adj.get(s) or 1.0)
            dev = f - 1.0
            if abs(dev) < LINEUP_ADJ_NOTABLE:
                continue
            ratio = adj.get(f"{s}_ratio")
            ratio_txt = f" (kadro hücum gücü olağanın {_pct(float(ratio))} kadarı)" if ratio else ""
            verb = "artırdı" if dev > 0 else "düşürdü"
            sup = _side(s if dev > 0 else OPPOSITE[s])
            items.append(_item(
                f"Resmi ilk 11, {c.name(s)} beklenen golünü {_pct(abs(dev))} {verb}{ratio_txt}.", sup,
                _strength(abs(dev), LINEUP_ADJ_NOTABLE, LINEUP_ADJ_FULL)))

    level = m.get("confidence", "yok")
    notes = m.get("confidence_notes") or []
    items.append(_item(f"Model güveni {level}" + (f": {'; '.join(notes)}." if notes else " — iki takımın da yeterli yakın dönem verisi var."),
                       "neutral"))
    return _section("guc", items, True)


def _kg_item(p_yes: float, lead: str, c: _Ctx) -> dict[str, Any]:
    if p_yes >= KG_YES_P:
        return _item(f"{lead}: iki takımın da gol bulması bekleniyor.", "goals_over",
                     KG_SCALE * _strength(p_yes, KG_YES_P, KG_YES_P + GOALS_P_FULL))
    if p_yes <= KG_NO_P:
        return _item(f"{lead}: taraflardan birinin gol bulamaması daha olası.", "goals_under",
                     KG_SCALE * _strength(1 - p_yes, 1 - KG_NO_P, 1 - KG_NO_P + GOALS_P_FULL))
    return _item(f"{lead}: karşılıklı golde net eğilim yok.", "neutral")


# ---------------------------------------------------------------- 2) form

@dataclass
class _Form:
    n: int
    w: int
    d: int
    l: int
    gf: int
    ga: int
    seq: list[str]                 # yeniden eskiye G/B/M
    venue_n: int
    venue_w: int
    venue_d: int
    venue_l: int
    btts: int
    clean: int
    last_date: datetime | None
    last_league: str

    @property
    def ppg(self) -> float:
        return (3 * self.w + self.d) / self.n if self.n else 0.0

    @property
    def venue_ppg(self) -> float:
        return (3 * self.venue_w + self.venue_d) / self.venue_n if self.venue_n else 0.0

    def record(self) -> str:
        return f"{self.w}G {self.d}B {self.l}M"

    def streak(self, cond: set[str]) -> int:
        k = 0
        for r in self.seq:
            if r not in cond:
                break
            k += 1
        return k


def _form_stats(rows: list[dict[str, Any]], team_id: str, at_home: bool) -> _Form:
    f = _Form(0, 0, 0, 0, 0, 0, [], 0, 0, 0, 0, 0, 0, None, "")
    for r in rows:
        hg, ag = r.get("home_goals"), r.get("away_goals")
        if hg is None or ag is None:
            continue
        is_home = bool(r["is_home"]) if "is_home" in r else str(r.get("home_id")) == team_id
        gf, ga = (int(hg), int(ag)) if is_home else (int(ag), int(hg))
        res = "G" if gf > ga else ("B" if gf == ga else "M")
        f.n += 1
        f.gf += gf
        f.ga += ga
        f.seq.append(res)
        f.w += res == "G"
        f.d += res == "B"
        f.l += res == "M"
        f.btts += gf > 0 and ga > 0
        f.clean += ga == 0
        if is_home == at_home:
            f.venue_n += 1
            f.venue_w += res == "G"
            f.venue_d += res == "B"
            f.venue_l += res == "M"
        if f.last_date is None:
            f.last_date = _dt(r.get("date_utc"))
            f.last_league = str(r.get("league") or "")
    return f


def _streak_items(f: _Form, side: str, c: _Ctx) -> list[dict[str, Any]]:
    name = c.name(side)
    opp: Side = "away" if side == "home" else "home"
    me = _side(side)
    wins, losses = f.streak({"G"}), f.streak({"M"})
    unbeaten, winless = f.streak({"G", "B"}), f.streak({"B", "M"})
    if wins >= FORM_WIN_STREAK:
        return [_item(f"{name} üst üste {wins} maçtır kazanıyor.", me, FORM_STREAK_WEIGHT)]
    if unbeaten >= FORM_UNBEATEN:
        won = f.seq[:unbeaten].count("G")
        return [_item(f"{name} {unbeaten} maçtır yenilmiyor ({won} galibiyet, {unbeaten - won} beraberlik).", me, FORM_STREAK_WEIGHT)]
    if losses >= FORM_LOSS_STREAK:
        return [_item(f"{name} son {losses} maçını kaybetti.", opp, FORM_STREAK_WEIGHT)]
    if winless >= FORM_WINLESS:
        return [_item(f"{name} {winless} maçtır kazanamıyor.", opp, FORM_STREAK_WEIGHT)]
    return []


def _section_form(form: dict[str, Any] | None, c: _Ctx) -> tuple[dict[str, Any], dict[str, _Form]]:
    form = form or {}
    fh = _form_stats(list(form.get("home") or []), c.home_id, at_home=True)
    fa = _form_stats(list(form.get("away") or []), c.away_id, at_home=False)
    stats = {"home": fh, "away": fa}
    if min(fh.n, fa.n) < FORM_MIN_MATCHES:
        thin = _join([f"{c.name(s)} {stats[s].n}" for s in ("home", "away") if stats[s].n < FORM_MIN_MATCHES])
        return _section("form", [], False, f"Son maç verisi yetersiz ({thin} maç; en az {FORM_MIN_MATCHES} gerekli)."), stats
    items: list[dict[str, Any]] = []
    diff = fh.ppg - fa.ppg
    n = min(fh.n, fa.n)
    if abs(diff) >= FORM_PPG_DIFF_MIN:
        side: Side = "home" if diff > 0 else "away"
        b, wv = (fh, fa) if diff > 0 else (fa, fh)
        bn, wn = c.name(side), c.name(OPPOSITE[side])
        if abs(diff) >= 1.2:
            txt = f"Form farkı belirgin: {bn} son {b.n} maçta {b.record()} ({b.ppg:.2f} puan/maç), {wn} ise {wv.record()} ({wv.ppg:.2f})."
        else:
            txt = f"{bn} daha formda: {b.record()}, {b.ppg:.2f} puan/maç; {wn} {wv.record()}, {wv.ppg:.2f}."
        items.append(_item(txt, side, _strength(abs(diff), FORM_PPG_DIFF_MIN, FORM_PPG_DIFF_FULL)))
    else:
        items.append(_item(f"Son {n} maçta formlar yakın: {c.home} {fh.record()} ({fh.ppg:.2f}), {c.away} {fa.record()} ({fa.ppg:.2f}).",
                           "neutral"))

    if not c.neutral and fh.venue_n >= FORM_VENUE_MIN_N and fa.venue_n >= FORM_VENUE_MIN_N:
        vd = fh.venue_ppg - fa.venue_ppg
        txt = (f"{c.home} iç sahadaki son {fh.venue_n} maçında {fh.venue_ppg:.2f} puan/maç "
               f"({fh.venue_w}G {fh.venue_d}B {fh.venue_l}M), {c.away} deplasmandaki {fa.venue_n} maçında {fa.venue_ppg:.2f}.")
        if abs(vd) >= FORM_PPG_DIFF_MIN:
            vs: Side = "home" if vd > 0 else "away"
            items.append(_item(txt, vs, FORM_VENUE_SCALE * _strength(abs(vd), FORM_PPG_DIFF_MIN, FORM_PPG_DIFF_FULL)))
        else:
            items.append(_item(txt, "neutral"))

    for s in ("home", "away"):
        items.extend(_streak_items(stats[s], s, c))

    tot_n = fh.n + fa.n
    avg_goals = (fh.gf + fh.ga + fa.gf + fa.ga) / tot_n
    btts = (fh.btts + fa.btts) / tot_n
    clean_txt = ""
    if fh.clean or fa.clean:
        clean_txt = f"; gol yemeden biten maç: {c.home} {fh.clean}, {c.away} {fa.clean}"
    txt = f"İki takımın son maçlarında maç başına {avg_goals:.1f} gol, karşılıklı gol oranı {_pct(btts)}{clean_txt}."
    if avg_goals >= FORM_GOALS_HIGH:
        items.append(_item(txt, "goals_over", FORM_GOALS_SCALE * _strength(avg_goals, FORM_GOALS_HIGH, FORM_GOALS_HIGH + FORM_GOALS_FULL)))
    elif avg_goals <= FORM_GOALS_LOW:
        items.append(_item(txt, "goals_under", FORM_GOALS_SCALE * _strength(-avg_goals, -FORM_GOALS_LOW, -FORM_GOALS_LOW + FORM_GOALS_FULL)))
    else:
        items.append(_item(txt, "neutral"))
    return _section("form", items, True), stats


# ---------------------------------------------------------------- 3) lig konumu

def _zone(note: dict[str, Any] | None) -> tuple[str, str] | None:
    """(tür, Türkçe ad). tür: 'top' (Avrupa/çıkış), 'bottom' (düşme), 'other'."""
    if not note or not note.get("description"):
        return None
    d = str(note["description"])
    low = d.lower()
    table = (
        ("relegation", "bottom", "küme düşme"), ("descenso", "bottom", "küme düşme"),
        ("champions league", "top", "Şampiyonlar Ligi"), ("europa league", "top", "Avrupa Ligi"),
        ("conference league", "top", "Konferans Ligi"), ("libertadores", "top", "Copa Libertadores"),
        ("sudamericana", "top", "Copa Sudamericana"), ("promotion", "top", "üst lige çıkış"),
        ("champion", "top", "şampiyonluk"), ("play-off", "other", "play-off"), ("playoff", "other", "play-off"),
    )
    for key, kind, tr in table:
        if key in low:
            return kind, tr
    return "other", d


def _section_lig(standings: dict[str, Any] | None, c: _Ctx) -> tuple[dict[str, Any], dict[str, Any]]:
    meta: dict[str, Any] = {"early": False}
    entries = list((standings or {}).get("entries") or [])
    if not entries:
        note = "Puan durumu yok." + (" Kupa/Avrupa maçında lig tablosu karşılaştırması anlamlı olmayabilir." if c.is_cup else "")
        return _section("lig", [], False, note), meta
    by_id = {str(e.get("team_id")): e for e in entries}
    eh, ea = by_id.get(c.home_id), by_id.get(c.away_id)
    if eh is None or ea is None:
        missing = _join([c.name(s) for s, e in (("home", eh), ("away", ea)) if e is None])
        return _section("lig", [], False, f"{missing} bu tabloda ({(standings or {}).get('group') or 'grup'}) yer almıyor."), meta
    ph, pa = int(eh.get("played") or 0), int(ea.get("played") or 0)
    if ph == 0 or pa == 0:
        return _section("lig", [], False, "Sezon yeni başladı: tabloda henüz oynanmış maç yok."), meta
    early = min(ph, pa) < LEAGUE_MIN_PLAYED
    meta["early"] = early
    scale = LEAGUE_EARLY_FACTOR if early else 1.0
    items: list[dict[str, Any]] = []
    pts_h, pts_a = int(eh.get("points") or 0), int(ea.get("points") or 0)
    rk_h, rk_a = eh.get("rank"), ea.get("rank")
    ppg_h, ppg_a = pts_h / ph, pts_a / pa
    diff = ppg_h - ppg_a
    n_teams = len(entries)
    played_txt = f" (oynanan maç {ph}–{pa})" if ph != pa else ""
    if abs(diff) >= LEAGUE_PPG_DIFF_MIN:
        side: Side = "home" if diff > 0 else "away"
        b, w = (eh, ea) if diff > 0 else (ea, eh)
        gap = abs(int(b.get("points") or 0) - int(w.get("points") or 0))
        txt = (f"Tabloda {c.name(side)} {b.get('rank')}. sırada {b.get('points')} puanla, {c.name(OPPOSITE[side])} "
               f"{w.get('rank')}. sırada {w.get('points')} puanla{played_txt}; aradaki fark {gap} puan, {n_teams} takımlı grupta.")
        items.append(_item(txt, side, scale * _strength(abs(diff), LEAGUE_PPG_DIFF_MIN, LEAGUE_PPG_DIFF_FULL)))
    else:
        items.append(_item(f"Tabloda yakınlar: {c.home} {rk_h}. ({pts_h} puan), {c.away} {rk_a}. ({pts_a} puan){played_txt}.", "neutral"))

    gd_h = int(eh.get("gd") if eh.get("gd") is not None else (eh.get("gf") or 0) - (eh.get("ga") or 0))
    gd_a = int(ea.get("gd") if ea.get("gd") is not None else (ea.get("gf") or 0) - (ea.get("ga") or 0))
    gdd = gd_h / ph - gd_a / pa
    gd_txt = (f"Averaj: {c.home} {gd_h:+d} ({eh.get('gf')}-{eh.get('ga')}), "
              f"{c.away} {gd_a:+d} ({ea.get('gf')}-{ea.get('ga')}).")
    if abs(gdd) >= LEAGUE_GDPG_DIFF_MIN:
        gs: Side = "home" if gdd > 0 else "away"
        items.append(_item(gd_txt, gs, scale * LEAGUE_GD_SCALE * _strength(abs(gdd), LEAGUE_GDPG_DIFF_MIN, LEAGUE_GDPG_DIFF_FULL)))
    else:
        items.append(_item(gd_txt, "neutral"))

    if all(e.get("gf") is not None and e.get("ga") is not None for e in (eh, ea)):
        gh = (int(eh["gf"]) + int(eh["ga"])) / ph
        ga_ = (int(ea["gf"]) + int(ea["ga"])) / pa
        avg = (gh + ga_) / 2
        txt = f"Lig maçlarında {c.home} maçlarında ortalama {gh:.1f}, {c.away} maçlarında {ga_:.1f} gol çıkıyor."
        if avg >= LEAGUE_GOALS_HIGH:
            items.append(_item(txt, "goals_over", scale * LEAGUE_GOALS_SCALE * _strength(avg, LEAGUE_GOALS_HIGH, LEAGUE_GOALS_HIGH + LEAGUE_GOALS_FULL)))
        elif avg <= LEAGUE_GOALS_LOW:
            items.append(_item(txt, "goals_under", scale * LEAGUE_GOALS_SCALE * _strength(-avg, -LEAGUE_GOALS_LOW, -LEAGUE_GOALS_LOW + LEAGUE_GOALS_FULL)))
        else:
            items.append(_item(txt, "neutral"))

    # Bölge notları ve hat mücadelesi
    bottom = [e for e in entries if (_zone(e.get("note")) or ("", ""))[0] == "bottom"]
    safe_line = min((int(e.get("points") or 0) for e in bottom), default=None)
    total_games = 2 * (n_teams - 1)
    late = total_games > 0 and min(ph, pa) >= LATE_SEASON_SHARE * total_games
    fighting: dict[str, bool] = {}
    for s, e in (("home", eh), ("away", ea)):
        z = _zone(e.get("note"))
        pts = int(e.get("points") or 0)
        if z is not None:
            kind, tr = z
            fighting[s] = kind in ("top", "bottom")
            items.append(_item(f"{c.name(s)} şu an {tr} bölgesinde ({e.get('rank')}.).", "neutral"))
        elif safe_line is not None and 0 <= pts - safe_line <= LEAGUE_ZONE_GAP:
            fighting[s] = True
            items.append(_item(f"{c.name(s)} düşme hattının yalnızca {pts - safe_line} puan üstünde: puan baskısı altında.", "neutral"))
        else:
            fighting[s] = False
    if late and fighting.get("home") != fighting.get("away"):
        mot: Side = "home" if fighting.get("home") else "away"
        items.append(_item(
            f"Sezonun son bölümünde {c.name(mot)} için masada daha çok şey var; {c.name(OPPOSITE[mot])} için tablo büyük ölçüde belli.",
            mot, MOTIVATION_WEIGHT))
    if early:
        items.append(_item(f"Tablo henüz oturmadı (en az {min(ph, pa)} maç oynandı); bu bölümün ağırlığı yarıya indirildi.", "neutral"))
    return _section("lig", items, True), meta


# ---------------------------------------------------------------- 4) karşılıklı geçmiş

def _section_h2h(h2h: list[dict[str, Any]] | None, c: _Ctx) -> dict[str, Any]:
    games = [g for g in (h2h or []) if g.get("home_goals") is not None and g.get("away_goals") is not None]
    if len(games) < H2H_MIN_MATCHES:
        note = "İki takım arasında yakın tarihli tamamlanmış maç yok." if not games else "Yalnızca 1 karşılaşma var; eğilim çıkarmak için az."
        items = []
        if games:
            items.append(_h2h_last_item(games[0], c))
        return _section("h2h", items, False, note)
    wh = wa = dr = 0
    goal_games: list[int] = []
    btts = 0
    for g in games:
        hg, ag = int(g["home_goals"]), int(g["away_goals"])
        if g.get("extra_time"):
            dr += 1          # uzatmaya giden maç 90 dakikada berabere bitmiştir; uzatma golleri gol ortalamasına alınmaz
            continue
        goal_games.append(hg + ag)
        btts += hg > 0 and ag > 0
        if hg == ag:
            dr += 1
            continue
        winner = str(g["home_id"]) if hg > ag else str(g["away_id"])
        if winner == c.home_id:
            wh += 1
        elif winner == c.away_id:
            wa += 1
    n = len(games)
    newest = _dt(games[0].get("date_utc"))
    stale = bool(newest and c.kickoff and (c.kickoff - newest).days > H2H_STALE_DAYS)
    factor = H2H_STALE_FACTOR if stale else 1.0
    items: list[dict[str, Any]] = []
    diff = wh - wa
    rec = (f"Son {n} karşılaşmada {c.home} {wh}, {c.away} {wa} galibiyet aldı, "
           + (f"{dr} maç berabere bitti" if dr else "beraberlik çıkmadı"))
    if n >= H2H_SIDE_MIN_MATCHES and abs(diff) >= H2H_WIN_DIFF_MIN:
        side: Side = "home" if diff > 0 else "away"
        items.append(_item(f"{rec}; eşleşmede üstünlük {c.name(side)} tarafında.", side,
                           factor * H2H_MAX_WEIGHT * _strength(abs(diff), H2H_WIN_DIFF_MIN, H2H_WIN_DIFF_FULL)))
    elif dr * 2 > n:
        items.append(_item(f"{rec}; bu eşleşme beraberliğe yatkın.", "draw", factor * H2H_MAX_WEIGHT * W_FLOOR * 2))
    else:
        items.append(_item(f"{rec}.", "neutral"))
    items.append(_h2h_last_item(games[0], c))
    if goal_games:
        avg = sum(goal_games) / len(goal_games)
        txt = f"Bu eşleşmede maç başına {avg:.1f} gol; {btts}/{len(goal_games)} maçta iki taraf da gol buldu."
        if avg >= H2H_GOALS_HIGH:
            items.append(_item(txt, "goals_over", factor * H2H_GOALS_WEIGHT))
        elif avg <= H2H_GOALS_LOW:
            items.append(_item(txt, "goals_under", factor * H2H_GOALS_WEIGHT))
        else:
            items.append(_item(txt, "neutral"))
    if stale and newest:
        items.append(_item(f"Son karşılaşma {newest.year} yılında; kadrolar değiştiği için bu bölümün ağırlığı düşürüldü.", "neutral"))
    return _section("h2h", items, True)


def _h2h_last_item(g: dict[str, Any], c: _Ctx) -> dict[str, Any]:
    d = _dt(g.get("date_utc"))
    when = _date_tr(d) if d else "tarih yok"
    comp = f", {g['league_name']}" if g.get("league_name") else ""
    et = " (uzatmalı)" if g.get("extra_time") else ""
    hn = g.get("home_name") or (c.home if str(g.get("home_id")) == c.home_id else c.away)
    an = g.get("away_name") or (c.away if str(g.get("away_id")) == c.away_id else c.home)
    return _item(f"Son karşılaşma ({when}{comp}): {hn} {g['home_goals']}-{g['away_goals']} {an}{et}.", "neutral")


# ---------------------------------------------------------------- 5) hücum/savunma profili ve oyuncular

_ABSENT_RE = re.compile(r"Son (\d+) maçta kadroda yok")


def _recent_absence(flags: list[str]) -> str | None:
    """Kısa süreli yokluk (sakatlık/ceza) metni; uzun yokluk (transfer/uzun sakatlık) ya da bayrak yoksa None."""
    for fl in flags:
        mt = _ABSENT_RE.search(str(fl))
        if mt and int(mt.group(1)) < KEY_LONG_ABSENCE:
            return f"son {mt.group(1)} maçta kadroda yok"
    return None


def _key_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Takımın 90 dk başı gol katkısında (şut × isabet × dönüşüm) ilk KEY_TOP_N, yeterli dakikası olanlar."""
    pool = [p for p in players if float(p.get("minutes_seen") or 0) >= KEY_MIN_MINUTES and p.get("pos_group") != "G"]
    pool.sort(key=lambda p: -float(p.get("rate_shots_p90") or 0) * float(p.get("rate_acc") or 0) * float(p.get("rate_conv") or 0))
    return pool[:KEY_TOP_N]


def _section_profil(payload: dict[str, Any], c: _Ctx) -> tuple[dict[str, Any], list[str]]:
    sim = payload.get("sim")
    doubts: list[str] = []
    if not sim or not sim.get("teams"):
        return _section("profil", [], False, "Şut/oyuncu simülasyonu yok (yardımcı şut modeli bu maç için kurulamadı)."), doubts
    teams = sim["teams"]
    th, ta = teams.get("home") or {}, teams.get("away") or {}
    items: list[dict[str, Any]] = []
    sh_h, sh_a = float((th.get("shots") or {}).get("mean") or 0), float((ta.get("shots") or {}).get("mean") or 0)
    so_h, so_a = float((th.get("shots_on_target") or {}).get("mean") or 0), float((ta.get("shots_on_target") or {}).get("mean") or 0)
    if so_h + so_a > 0:
        share = so_h / (so_h + so_a)
        txt = (f"Simülasyonda {c.home} ortalama {sh_h:.1f} şut / {so_h:.1f} isabetli, "
               f"{c.away} {sh_a:.1f} / {so_a:.1f} üretiyor (isabetli şut payı {_pct(share)}–{_pct(1 - share)}).")
        if share >= PROFILE_SOT_SHARE_MIN:
            items.append(_item(txt, "home", _strength(share, PROFILE_SOT_SHARE_MIN, PROFILE_SOT_SHARE_FULL)))
        elif share <= 1 - PROFILE_SOT_SHARE_MIN:
            items.append(_item(txt, "away", _strength(1 - share, PROFILE_SOT_SHARE_MIN, PROFILE_SOT_SHARE_FULL)))
        else:
            items.append(_item(txt, "neutral"))

    src = (sim.get("notes") or {}).get("lineup_source") or {}
    for s, t in (("home", th), ("away", ta)):
        players = list(t.get("players") or [])
        if not t.get("players_available", True) or not players:
            items.append(_item(f"{c.name(s)} için oyuncu düzeyinde tahmin yok (oyuncu detaylı maç verisi az).", "neutral"))
            continue
        top = sorted([p for p in players if float(p.get("p_start") or 0) >= PROFILE_START_MIN],
                     key=lambda p: -float(p.get("exp_sot") or 0))[:PROFILE_TOP_N]
        if top:
            parts = [f"{p['name']} ({POS_TR.get(str(p.get('pos_group')), 'oyuncu')}; 1+ isabetli şut {_pct(float(p['p_sot_1']))}, "
                     f"gol {_pct(float(p['p_goal']))})" for p in top]
            items.append(_item(f"{c.name(s)} hücumunda öne çıkanlar: {_join(parts)}.", "neutral"))
        opp: Side = "away" if s == "home" else "home"
        confirmed = src.get(s) == "resmi"
        for kp in _key_players(players):
            p_start = float(kp.get("p_start") or 0)
            if confirmed and kp.get("confirmed_starter") is not True:
                where = "yedek kulübesinde" if kp.get("confirmed_starter") is False else "maç kadrosunda değil"
                items.append(_item(f"{c.name(s)} için kilit hücum oyuncusu {kp['name']} resmi kadroda {where}.", opp, KEY_ABSENCE_WEIGHT))
            elif not confirmed:
                flags = [str(x) for x in kp.get("flags") or []]
                absent = _recent_absence(flags)
                if absent and p_start < KEY_ABSENT_START:
                    items.append(_item(f"{c.name(s)} için gol katkısı en yüksek isimlerden {kp['name']} muhtemelen yok ({absent}).",
                                       opp, KEY_ABSENCE_WEIGHT))
                    doubts.append(kp["name"])
                elif absent or any("kırmızı kart" in x for x in flags):
                    doubts.append(kp["name"])
    if src.get("home") == "resmi" or src.get("away") == "resmi":
        items.append(_item(f"Kadrolar: {c.home} {src.get('home', 'tahmini')}, {c.away} {src.get('away', 'tahmini')}.", "neutral"))
    return _section("profil", items, True), doubts


# ---------------------------------------------------------------- 6) piyasa

def _section_piyasa(payload: dict[str, Any], similar: dict[str, Any] | None, c: _Ctx) -> tuple[dict[str, Any], float | None]:
    ms_m = _iddaa_market(payload, "ms")
    if ms_m is None:
        return _section("piyasa", [], False, "Bu maç iddaa bülteninde yok ya da MS oranı açılmamış."), None
    outs = {o["name"]: o for o in ms_m.get("outcomes") or []}
    if not all(k in outs for k in ("1", "0", "2")):
        return _section("piyasa", [], False, "MS oranları eksik."), None
    items: list[dict[str, Any]] = []
    q = {k: float(outs[k]["p_market"]) for k in ("1", "0", "2")}
    p = {k: float(outs[k]["p_model"]) for k in ("1", "0", "2")}
    odds = f"{outs['1']['odd']:.2f} / {outs['0']['odd']:.2f} / {outs['2']['odd']:.2f}"
    mfav = "1" if q["1"] >= q["2"] else "2"
    pfav = "1" if p["1"] >= p["2"] else "2"
    gap = p[mfav] - q[mfav]
    fav_name = c.name(_ms_side(mfav))
    if pfav != mfav and abs(p["1"] - p["2"]) >= GUC_FAV_MIN_MARGIN:
        view = f"model ise {c.name(_ms_side(pfav))} tarafında ({_pct(p[pfav])}) — favoride ayrışma var"
    elif gap >= MARKET_GAP_WARN:
        view = f"model daha iyimser ({_pct(p[mfav])})"
    elif gap <= -MARKET_GAP_WARN:
        view = f"model daha temkinli ({_pct(p[mfav])})"
    else:
        view = f"model de aynı yerde ({_pct(p[mfav])})"
    txt = f"iddaa MS oranları {odds}: piyasa {fav_name} için {_pct(q[mfav])} fiyatlıyor, {view}."
    q_oth = q["2" if mfav == "1" else "1"]
    if q[mfav] >= MARKET_FAV_MIN_P and q[mfav] - q_oth >= MARKET_FAV_MIN_MARGIN:
        items.append(_item(txt, _ms_side(mfav), _strength(q[mfav], MARKET_FAV_MIN_P, MARKET_FAV_FULL_P)))
    elif q["0"] >= GUC_DRAW_HIGH_P and abs(q["1"] - q["2"]) <= GUC_DRAW_BALANCE:
        items.append(_item(txt.rstrip(".") + "; beraberlik de pahalı değil.", "draw", W_FLOOR))
    else:
        items.append(_item(txt, "neutral"))

    au_m = _iddaa_market(payload, "au", "2.5")
    if au_m is not None:
        ao = {o["name"]: o for o in au_m.get("outcomes") or []}
        if "Üst" in ao and "Alt" in ao:
            qo, po = float(ao["Üst"]["p_market"]), float(ao["Üst"]["p_model"])
            txt = f"2.5 gol çizgisi: Üst {ao['Üst']['odd']:.2f}, Alt {ao['Alt']['odd']:.2f}; piyasa Üst için {_pct(qo)}, model {_pct(po)}."
            if qo >= GOALS_OVER_P:
                items.append(_item(txt, "goals_over", _strength(qo, GOALS_OVER_P, GOALS_OVER_P + GOALS_P_FULL)))
            elif qo <= GOALS_UNDER_P:
                items.append(_item(txt, "goals_under", _strength(1 - qo, 1 - GOALS_UNDER_P, 1 - GOALS_UNDER_P + GOALS_P_FULL)))
            else:
                items.append(_item(txt, "neutral"))

    kg_m = _iddaa_market(payload, "kg")
    if kg_m is not None:
        ko = {o["name"]: o for o in kg_m.get("outcomes") or []}
        if "Var" in ko and "Yok" in ko:
            items.append(_kg_item(float(ko["Var"]["p_market"]),
                                  f"KG Var {ko['Var']['odd']:.2f} / Yok {ko['Yok']['odd']:.2f} oranları karşılıklı gole "
                                  f"{_pct(float(ko['Var']['p_market']))} veriyor", c))

    move = _odds_move(payload.get("odds_history_ms") or [], ms_m, c)
    if move is not None:
        items.append(move)

    if similar:
        items.extend(_similar_items(similar, q, c))
    # Ayrışma: favoriler aynıysa favori olasılık farkı, farklıysa iki galibiyet olasılığındaki en büyük fark
    market_gap = abs(p[mfav] - q[mfav]) if pfav == mfav else max(abs(p["1"] - q["1"]), abs(p["2"] - q["2"]))
    return _section("piyasa", items, True), market_gap


def _odds_move(hist: list[dict[str, Any]], ms_m: dict[str, Any], c: _Ctx) -> dict[str, Any] | None:
    no_to_name = {int(o["no"]): str(o["name"]) for o in ms_m.get("outcomes") or []}
    series: dict[int, list[tuple[str, float]]] = {}
    for h in hist:
        if h.get("odd") is None or h.get("outcome_no") is None:
            continue
        series.setdefault(int(h["outcome_no"]), []).append((str(h.get("fetched_at") or ""), float(h["odd"])))
    best: tuple[float, str, float, float, int] | None = None
    for no, xs in series.items():
        xs.sort()
        if len(xs) < 2 or no not in no_to_name:
            continue
        first, last = xs[0][1], xs[-1][1]
        rel = (last - first) / first
        if rel < 0 and (best is None or rel < best[0]):
            best = (rel, no_to_name[no], first, last, len(xs))
    if best is None or -best[0] < ODDS_MOVE_MIN:
        return None
    rel, name, first, last, n = best
    side = _ms_side(name)
    label = "beraberlik" if side == "draw" else c.name(side)
    return _item(f"Oran hareketi: {label} oranı {first:.2f} → {last:.2f} ({n} kayıt, {_pct(-rel)} düşüş); para bu tarafa akıyor.",
                 side, ODDS_MOVE_MAX_WEIGHT * _strength(-rel, ODDS_MOVE_MIN, ODDS_MOVE_FULL))


def _similar_items(similar: dict[str, Any], q: dict[str, float], c: _Ctx) -> list[dict[str, Any]]:
    try:
        n = int(similar.get("n") or 0)
    except (TypeError, ValueError):
        return []
    if n <= 0:
        return []
    low = bool(similar.get("low_sample")) or n < SIMILAR_MIN_N
    items: list[dict[str, Any]] = []
    outcomes = similar.get("outcomes") if isinstance(similar.get("outcomes"), dict) else None
    if outcomes and all(isinstance(outcomes.get(k), (int, float)) for k in ("1", "0", "2")):
        f = {k: float(outcomes[k]) for k in ("1", "0", "2")}
        txt = (f"Benzer oranlı {n} geçmiş maçta sonuç dağılımı: ev {_pct(f['1'])}, beraberlik {_pct(f['0'])}, deplasman {_pct(f['2'])}")
        if low:
            items.append(_item(txt + " (örneklem küçük, yalnızca bilgi).", "neutral"))
        else:
            # Kıyas tabanı: varsa eşleşen maçlarda piyasanın beklediği (pool_implied), yoksa bugünkü piyasa olasılığı
            pool = similar.get("pool_implied")
            use_pool = isinstance(pool, dict) and all(isinstance(pool.get(k), (int, float)) for k in ("1", "0", "2"))
            base = {k: float(pool[k]) for k in ("1", "0", "2")} if use_pool and isinstance(pool, dict) else q
            base_txt = "o maçlarda piyasanın beklediğinden" if use_pool else "bugünkü piyasa fiyatından"
            edge_k = max(("1", "0", "2"), key=lambda k: f[k] - base[k])
            edge = f[edge_k] - base[edge_k]
            ci = similar.get("outcomes_ci95")
            ci_k = ci.get(edge_k) if isinstance(ci, dict) else None
            significant = not (isinstance(ci_k, (list, tuple)) and len(ci_k) == 2 and float(ci_k[0]) <= base[edge_k])
            side = _ms_side(edge_k)
            label = "beraberlik" if side == "draw" else c.name(side)
            if edge >= SIMILAR_EDGE_MIN and significant:
                items.append(_item(f"{txt}; {label} {base_txt} {_pct(edge)} daha sık gerçekleşmiş.",
                                   side, SIMILAR_MAX_WEIGHT * _strength(edge, SIMILAR_EDGE_MIN, SIMILAR_EDGE_FULL)))
            elif edge >= SIMILAR_EDGE_MIN:
                items.append(_item(f"{txt}; {label} lehine {_pct(edge)} fark var ama güven aralığı bunu desteklemiyor.", "neutral"))
            else:
                items.append(_item(txt + "; fiyatlamayla uyumlu.", "neutral"))
    over = similar.get("over25")
    btts = similar.get("btts")
    if isinstance(over, (int, float)):
        txt = f"Aynı maçlarda 2.5 Üst oranı {_pct(float(over))}" + (f", karşılıklı gol {_pct(float(btts))}" if isinstance(btts, (int, float)) else "")
        if low:
            items.append(_item(txt + ".", "neutral"))
        elif float(over) >= GOALS_OVER_P:
            items.append(_item(txt + ".", "goals_over", SIMILAR_MAX_WEIGHT * _strength(float(over), GOALS_OVER_P, GOALS_OVER_P + GOALS_P_FULL)))
        elif float(over) <= GOALS_UNDER_P:
            items.append(_item(txt + ".", "goals_under",
                               SIMILAR_MAX_WEIGHT * _strength(1 - float(over), 1 - GOALS_UNDER_P, 1 - GOALS_UNDER_P + GOALS_P_FULL)))
        else:
            items.append(_item(txt + ".", "neutral"))
    return items


# ---------------------------------------------------------------- 7) riskler

def _section_risk(payload: dict[str, Any], c: _Ctx, forms: dict[str, _Form], lig_meta: dict[str, Any], market_gap: float | None,
                  doubts: list[str]) -> tuple[dict[str, Any], list[str]]:
    """(bölüm, kısa etiketler). Etiketler hüküm gerekçesinde madde metnini tekrar etmeden riskleri saymak için."""
    items: list[dict[str, Any]] = []
    labels: list[str] = []
    m = payload.get("model") or {}
    level = m.get("confidence", "yok")
    if level in ("düşük", "yok"):
        items.append(_item(f"Model güveni {level}: takım verisi ya da ligler arası bağlantı zayıf, tahmin priora dayanıyor.",
                           "neutral", RISK_LOW_CONF))
        labels.append(f"model güveni {level}")
    elif level == "orta":
        items.append(_item("Model güveni orta: takımlardan birinin yakın dönem verisi sınırlı.", "neutral", RISK_MID_CONF))
        labels.append("orta model güveni")
    if c.is_cup:
        items.append(_item(f"{c.league_name} maçı: rotasyon ve tur hesabı (rövanş, uzatma ihtimali) oyunu değiştirebilir.",
                           "neutral", RISK_CUP))
        labels.append("kupa/Avrupa maçı")
    if c.neutral:
        items.append(_item("Tarafsız saha: ev sahibi avantajı yok, iç saha formu bu maça taşınmaz.", "neutral", RISK_NEUTRAL))
        labels.append("tarafsız saha")
    thin = [c.name(s) for s in ("home", "away") if forms[s].n < FORM_MIN_MATCHES]
    if thin:
        items.append(_item(f"Son maç verisi az: {_join(thin)}.", "neutral", RISK_THIN_FORM))
        labels.append("az form verisi")
    if market_gap is not None and market_gap >= MARKET_GAP_RISK:
        items.append(_item(f"Model ile piyasa favori olasılığında {_pct(market_gap)} ayrışıyor: piyasa modelin görmediği bir bilgiyi "
                           "(sakatlık, rotasyon) fiyatlıyor olabilir.", "neutral", RISK_MARKET_GAP))
        labels.append(f"model-piyasa ayrışması ({_pct(market_gap)})")
    if c.kickoff is not None:
        for s in ("home", "away"):
            f = forms[s]
            if f.last_date is None:
                continue
            gap_days = (c.kickoff - f.last_date).total_seconds() / 86400
            if 0 < gap_days <= CONGESTION_DAYS:
                euro = " (Avrupa kupası maçından sonra)" if f.last_league.startswith("uefa.") and not c.league.startswith("uefa.") else ""
                items.append(_item(f"{c.name(s)} son maçından {gap_days:.0f} gün sonra sahada{euro}: yorgunluk/rotasyon ihtimali.",
                                   "neutral", RISK_CONGESTION))
                labels.append(f"{c.name(s)} için yoğun fikstür")
    if lig_meta.get("early"):
        items.append(_item("Sezon başı: tablo ve form henüz gürültülü.", "neutral", RISK_EARLY_SEASON))
        labels.append("sezon başı")
    sim_notes = (payload.get("sim") or {}).get("notes") or {}
    for s in ("home", "away"):
        for note in sim_notes.get(s) or []:
            items.append(_item(f"{c.name(s)}: {note}.", "neutral", RISK_SIM_NOTE))
            labels.append(f"{c.name(s)} oyuncu verisi")
    if doubts:
        items.append(_item(f"Müsaitliği belirsiz kilit oyuncular: {_join(doubts)}; ilk 11 açıklanınca tablo değişebilir.",
                           "neutral", RISK_KEY_DOUBT))
        labels.append("kilit oyuncu belirsizliği")
    return _section("risk", items, True, None if items else "Öne çıkan ek risk yok."), labels


# ---------------------------------------------------------------- hüküm

def _section_net(items: list[dict[str, Any]], direction: str, cs_mode: bool) -> float:
    opp = OPPOSITE[direction]
    s = 0.0
    for it in items:
        w = float(it["weight"])
        if it["side"] == direction:
            s += w
        elif it["side"] == opp:
            s -= w
        elif it["side"] == "draw" and direction in ("home", "away"):
            s += DRAW_FOR_CS_FACTOR * w if cs_mode else -DRAW_AGAINST_FACTOR * w
    return max(-SECTION_NET_CAP, min(SECTION_NET_CAP, s))


def _axis(sections: list[dict[str, Any]], direction: str | None, cs_mode: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"direction": direction, "agree": [], "disagree": [], "nets": {}}
    if direction is None:
        return out
    allowed = GOALS_SECTIONS if direction in ("goals_over", "goals_under") else EVIDENCE_SECTIONS
    for s in sections:
        if s["key"] not in allowed or not s["available"]:
            continue
        n = _section_net(s["items"], direction, cs_mode)
        out["nets"][s["key"]] = round(n, 3)
        if n >= AGREE_MIN_NET:
            out["agree"].append(s["key"])
        elif n <= -AGREE_MIN_NET:
            out["disagree"].append(s["key"])
    return out


def _grade(ax: dict[str, Any], level: str, risk_total: float) -> tuple[str | None, str]:
    """(güven, durum). güven: 'yüksek' | 'orta' | None; durum: 'ok' | 'conflict' | 'weak'."""
    agree, dis = ax["agree"], ax["disagree"]
    ind_a = sum(k in INDEPENDENT_SECTIONS for k in agree)
    ind_d = sum(k in INDEPENDENT_SECTIONS for k in dis)
    if len(dis) >= CONFLICT_MIN_DISAGREE or (ind_d >= 1 and ind_a == 0):
        return None, "conflict"
    if (len(agree) >= STRONG_MIN_AGREE and not dis and ind_a >= STRONG_MIN_INDEPENDENT and level == "yüksek"
            and risk_total < RISK_CAP_TOTAL):
        return "yüksek", "ok"
    if len(agree) >= MEDIUM_MIN_AGREE and len(agree) - len(dis) >= MEDIUM_MIN_MARGIN and ind_a >= 1 and ind_a > ind_d:
        return "orta", "ok"
    return None, "weak"


def _pick_axis(sel: Selection) -> tuple[str, str | None, bool]:
    """(eksen, yön, çifte şans mı)."""
    if sel.key in ("ms", "hnd"):
        return "result", {"1": "home", "2": "away"}.get(sel.outcome_name), False
    if sel.key == "cs":
        return "result", {"1 ve 0": "home", "0 ve 2": "away"}.get(sel.outcome_name), True
    if sel.key in ("au", "kg"):
        return "goals", "goals_over" if sel.outcome_name in ("Üst", "Var") else "goals_under", False
    return "other", None, False


def _selection_text(sel: Selection, c: _Ctx) -> str:
    k, n = sel.key, sel.outcome_name
    if k == "ms":
        return {"1": f"{c.home} kazanır (MS 1)", "2": f"{c.away} kazanır (MS 2)", "0": "Beraberlik (MS X)"}.get(n, n)
    if k == "cs":
        return {"1 ve 0": f"{c.home} kaybetmez (1X)", "0 ve 2": f"{c.away} kaybetmez (X2)", "1 ve 2": "Beraberlik olmaz (12)"}.get(n, n)
    if k == "hnd" and sel.line is not None:
        v = float(sel.line)
        hcap = f"({v:g}:0)" if v >= 0 else f"(0:{-v:g})"
        if n == "1":
            return f"{c.home} handikaplı kazanır {hcap}"
        if n == "2":
            return f"{c.away} handikaplı kazanır {hcap}"
        return f"Handikaplı beraberlik {hcap}"
    if k == "au":
        return f"{sel.line} {n}" + (" (en az 3 gol)" if n == "Üst" and sel.line == "2.5" else (" (en çok 2 gol)" if sel.line == "2.5" else ""))
    if k == "kg":
        return "Karşılıklı gol var" if n == "Var" else "Karşılıklı gol yok"
    return f"{sel.label} {sel.line or ''} {n}".strip()


def _pick_json(sel: Selection, c: _Ctx, same: bool) -> dict[str, Any]:
    return {
        "market_key": sel.market_key, "key": sel.key, "label": sel.label, "line": sel.line, "selection": sel.outcome_name,
        "selection_text": _selection_text(sel, c), "odd": float(sel.odd), "p_model": float(sel.p_model),
        "p_market": float(sel.p_market), "p_safe": float(sel.p_blend), "ev": float(sel.ev) if sel.ev is not None else None,
        "family_validated": bool(sel.family_validated), "same_as_model_pick": same,
    }


def _dir_text(direction: str, c: _Ctx, cs_mode: bool = False) -> str:
    if direction == "goals_over":
        return "bol gol"
    if direction == "goals_under":
        return "az gol"
    return c.name(direction) + (" (kaybetmez)" if cs_mode else "")


def _toward(direction: str) -> str:
    return "yönünde" if direction in ("goals_over", "goals_under") else "lehine"


def _titles(keys: list[str]) -> str:
    return _join([TITLES[k].lower() for k in keys])


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _pas(headline: str, reason: str) -> dict[str, Any]:
    return {"verdict": "pas", "headline": headline, "reason": _cap(reason), "confidence": None, "pick": None}


def _verdict(payload: dict[str, Any], sections: list[dict[str, Any]], c: _Ctx, risk_total: float,
             risk_labels: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    by_key = {s["key"]: s for s in sections}
    m = payload.get("model") or {}
    level = str(m.get("confidence", "yok"))
    ms = _std_probs(payload, "ms")
    result_dir = ("home" if ms.get("1", 0) >= ms.get("2", 0) else "away") if ms else None
    over = _std_probs(payload, "au", "2.5").get("Üst")
    goals_dir = None if over is None else ("goals_over" if over >= 0.5 else "goals_under")
    signals = {"result": _axis(sections, result_dir), "goals": _axis(sections, goals_dir)}

    if not payload.get("covered") or not m:
        return _pas("Pas — model kapsamı dışında", payload.get("coverage_note") or "Takımlardan biri için geçmiş maç verisi yok."), signals
    if level in ("düşük", "yok"):
        notes = "; ".join(m.get("confidence_notes") or [])
        return _pas("Pas — veri zayıf", f"Model güveni {level}" + (f" ({notes})" if notes else "") +
                    ". Zayıf veriyle öneri verilmez."), signals
    if not (payload.get("iddaa") or {}).get("markets"):
        return _pas("Pas — bültende oran yok", "Bu maç iddaa bülteninde eşleşmedi; oranı olmayan bir seçim önerilmez."), signals
    evidence = [k for k in ("form", "lig", "h2h", "profil", "piyasa") if by_key[k]["available"]]
    if len(evidence) < MIN_EVIDENCE_SECTIONS:
        return _pas("Pas — veri yetersiz", f"Model dışında yalnızca {len(evidence)} bölümde veri var "
                    f"({_titles(evidence) or 'hiçbiri'}); en az {MIN_EVIDENCE_SECTIONS} gerekli."), signals
    if risk_total >= RISK_PAS_TOTAL:
        return _pas("Pas — risk yüksek", f"Risk puanı {risk_total:.2f}, öneri sınırı {RISK_PAS_TOTAL:.2f}: {_join(risk_labels)}."), signals

    pk = model_pick(payload)
    if pk is None:
        return _pas("Pas — net sinyal yok", "Model hiçbir ana pazarda öneri eşiğine ulaşmıyor (net favori, güçlü çifte şans ya da "
                    "belirgin gol eğilimi yok)."), signals
    axis, direction, cs_mode = _pick_axis(pk)
    if direction is None:
        return _pas("Pas — net sinyal yok", "Modelin önerisi scout eksenlerine (sonuç/gol) oturmuyor."), signals
    ax = _axis(sections, direction, cs_mode)
    signals[axis] = ax
    conf, status = _grade(ax, level, risk_total)
    sels = candidates([payload], require_confidence=False, require_fresh=False)

    def find(key: str, name: str, line: str | None = None) -> Selection | None:
        return next((s for s in sels if s.key == key and s.outcome_name == name and (line is None or s.line == line)), None)

    if conf is not None:
        chosen, note = pk, ""
        if conf == "orta" and pk.key == "hnd":
            alt = find("ms", pk.outcome_name)
            if alt is not None:
                chosen, note = alt, " Kanıt orta düzeyde olduğu için handikap yerine düz maç sonucu seçildi."
        draw_total = sum(float(it["weight"]) for s in sections if s["key"] in EVIDENCE_SECTIONS for it in s["items"] if it["side"] == "draw")
        if conf == "orta" and chosen.key == "ms" and draw_total >= DRAW_DOWNGRADE_TOTAL:
            alt = find("cs", "1 ve 0" if chosen.outcome_name == "1" else "0 ve 2")
            if alt is not None and alt.p_model >= PICK_CS_MIN_P and alt.odd >= PICK_CS_MIN_ODDS:
                chosen, note = alt, " Beraberlik sinyalleri belirgin olduğu için maç sonucu yerine çifte şans seçildi."
        pick = _pick_json(chosen, c, chosen is pk)
        against = f" Karşı yönde: {_titles(ax['disagree'])}." if ax["disagree"] else " Karşı kanıt yok."
        reason = (f"{_cap(_dir_text(direction, c, cs_mode))} {_toward(direction)} {len(ax['agree'])} bölüm aynı yönde ({_titles(ax['agree'])})."
                  f"{against} Seçimin model olasılığı {_pct(chosen.p_model)}, piyasa {_pct(chosen.p_market)} (oran {chosen.odd:.2f}).{note}")
        return {"verdict": "oneri", "headline": f"Öneri: {pick['selection_text']}", "reason": reason, "confidence": conf,
                "pick": pick}, signals

    # Sonuç ekseni çelişkili/zayıf: gol ekseninde güçlü uyum varsa modelin eşiklerini geçen gol pazarı
    goals_note = ""
    if axis == "result":
        alts = [s for s in sels if ((s.key == "au" and s.line == "2.5") or s.key == "kg")
                and s.p_model >= PICK_GOALS_MIN_P and s.odd >= PICK_GOALS_MIN_ODDS]
        for alt in sorted(alts, key=lambda s: -s.p_model):
            _, gdir, _ = _pick_axis(alt)
            gax = _axis(sections, gdir)
            gconf, _ = _grade(gax, level, risk_total)
            if gconf is not None:
                signals["goals"] = gax
                pick = _pick_json(alt, c, False)
                reason = (f"Sonuç tarafında uyum yok ({'kanıtlar çelişiyor' if status == 'conflict' else 'kanıt yetersiz'}), "
                          f"ama {_dir_text(str(gdir), c)} {_toward(str(gdir))} {len(gax['agree'])} bölüm birleşiyor ({_titles(gax['agree'])}). "
                          f"Model {_pct(alt.p_model)}, piyasa {_pct(alt.p_market)} (oran {alt.odd:.2f}).")
                return {"verdict": "oneri", "headline": f"Öneri: {pick['selection_text']}", "reason": reason,
                        "confidence": "orta", "pick": pick}, signals
        if alts:
            goals_note = " Gol pazarlarında da yeterli uyum yok."

    dtxt = _dir_text(direction, c, cs_mode)
    if status == "conflict":
        opp_txt = "karşı yön" if direction not in OPPOSITE else _dir_text(OPPOSITE[direction], c)
        reason = (f"Kanıtlar çelişiyor: {_titles(ax['agree']) or 'hiçbir bölüm'} {dtxt} {_toward(direction)}, "
                  f"{_titles(ax['disagree'])} ise {opp_txt} {_toward(OPPOSITE.get(direction, direction))}.{goals_note}")
    else:
        neutral = [k for k in ax["nets"] if k not in ax["agree"] and k not in ax["disagree"]]
        ind = [k for k in ax["agree"] if k in INDEPENDENT_SECTIONS]
        ind_seen = [k for k in ax["nets"] if k in INDEPENDENT_SECTIONS]
        if ind or not ax["agree"]:
            lack = ""
        elif ind_seen:
            lack = " Bağımsız kanıt desteği olmadan model ve piyasa tek başına yeterli sayılmaz."
        else:
            lack = " Form, lig konumu ya da karşılıklı geçmiş verisi olmadan model tek başına yeterli sayılmaz."
        rest = [x for x in (f"{_titles(neutral)} nötr" if neutral else "",
                            f"{_titles(ax['disagree'])} karşı" if ax["disagree"] else "") if x]
        if ax["agree"]:
            head = f"{dtxt} {_toward(direction)} yalnızca {_titles(ax['agree'])} sinyal veriyor" + "".join(f", {x}" for x in rest)
        else:
            head = f"{dtxt} {_toward(direction)} hiçbir bölüm net sinyal vermiyor" + (f" ({'; '.join(rest)})" if rest else "")
        reason = f"{head}.{lack}{goals_note}"
    return _pas("Pas — net sinyal yok", reason), signals


# ---------------------------------------------------------------- giriş noktası

def _summary(payload: dict[str, Any], c: _Ctx) -> str:
    head = f"{c.home} – {c.away}, {c.league_name}" + (" (tarafsız saha)" if c.neutral else "") + "."
    m = payload.get("model")
    if not payload.get("covered") or not m:
        return f"{head} Model bu maçı kapsamıyor."
    ms = _std_probs(payload, "ms")
    tot = float(m["lambda_home"]) + float(m["lambda_away"])
    if ms:
        p1, p0, p2 = ms.get("1", 0.0), ms.get("0", 0.0), ms.get("2", 0.0)
        fav = "home" if p1 >= p2 else "away"
        pf = max(p1, p2)
        if pf >= GUC_FAV_FULL_P:
            view = f"Model {c.name(fav)} tarafını açık favori görüyor ({_pct(pf)})"
        elif pf >= GUC_FAV_MIN_P and abs(p1 - p2) >= GUC_FAV_MIN_MARGIN:
            view = f"Model {c.name(fav)} tarafına yakın ({_pct(pf)}, beraberlik {_pct(p0)})"
        else:
            view = f"Model dengeli bir maç bekliyor ({_pct(p1)} / {_pct(p0)} / {_pct(p2)})"
        return f"{head} {view}; toplam gol beklentisi {tot:.1f}."
    return f"{head} Toplam gol beklentisi {tot:.1f}."


def build_scout(payload: dict, *, form: dict, standings: dict | None, h2h: list[dict], similar: dict | None = None) -> dict:
    """Maç için scout raporu. Girdiler None/boş olabilir; dönen yapı JSON-serileştirilebilir."""
    mt = payload.get("match") or {}
    lg = LEAGUE_BY_SLUG.get(str(mt.get("league") or ""))
    c = _Ctx(
        match_id=str(mt.get("id") or ""), home_id=str((mt.get("home") or {}).get("id") or ""),
        away_id=str((mt.get("away") or {}).get("id") or ""), home=str((mt.get("home") or {}).get("name") or "Ev sahibi"),
        away=str((mt.get("away") or {}).get("name") or "Deplasman"), kickoff=_dt(mt.get("date_utc")),
        league=str(mt.get("league") or ""), league_name=str(mt.get("league_name") or mt.get("league") or ""),
        neutral=bool(mt.get("neutral")), is_cup=bool(lg.is_cup) if lg else False,
    )
    guc = _section_guc(payload, c)
    form_sec, forms = _section_form(form if form is not None else payload.get("form"), c)
    lig, lig_meta = _section_lig(standings, c)
    h2h_sec = _section_h2h(h2h, c)
    profil, doubts = _section_profil(payload, c)
    piyasa, market_gap = _section_piyasa(payload, similar, c)
    risk, risk_labels = _section_risk(payload, c, forms, lig_meta, market_gap, doubts)
    sections = [guc, form_sec, lig, h2h_sec, profil, piyasa, risk]
    risk_total = round(sum(float(it["weight"]) for it in risk["items"]), 3)
    verdict, signals = _verdict(payload, sections, c, risk_total, risk_labels)
    return {
        "version": SCOUT_VERSION,
        "match_id": c.match_id,
        "home": {"id": c.home_id, "name": c.home},
        "away": {"id": c.away_id, "name": c.away},
        "summary": _summary(payload, c),
        "verdict": verdict,
        "signals": signals,
        "sections": sections,
        "risk_total": risk_total,
    }
