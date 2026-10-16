"""Takım gol modeli: hiyerarşik Poisson + Dixon-Coles düşük skor düzeltmesi + ilk yarı oranı."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.stats import poisson

from ..config import LEAGUE_BY_SLUG, MAX_GOALS, REFERENCE_LEAGUE
from .count_model import OTHER, CountData, CountModel, fit_count_model


@dataclass
class MatchRecord:
    id: str
    league: str
    date: datetime
    home: str
    away: str
    neutral: bool
    hg: int
    ag: int
    hht: int | None
    aht: int | None


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


RESULT_LAG = timedelta(hours=3)


def result_cutoff(as_of: datetime) -> str:
    """Sonucu as_of anında BİLİNEN maçlar: başlama + 3 saat (uzatma dahil) < as_of. Backtest sızıntısını önler."""
    return (as_of - RESULT_LAG).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_matches(con: sqlite3.Connection, before: str) -> list[MatchRecord]:
    rows = con.execute(
        """SELECT id, league, date_utc, home_id, away_id, neutral, ft90_home, ft90_away, home_ht, away_ht
           FROM matches WHERE completed=1 AND ft90_home IS NOT NULL AND ft90_away IS NOT NULL AND date_utc < ?
           ORDER BY date_utc""",
        (before,),
    ).fetchall()
    # Skor = 90 dakika skoru (iddaa kuralı); uzatmalı ve 90 dk skoru doğrulanamayan maçlar zaten dışarıda
    return [
        MatchRecord(
            r["id"], r["league"], _dt(r["date_utc"]), r["home_id"], r["away_id"], bool(r["neutral"]),
            int(r["ft90_home"]), int(r["ft90_away"]), r["home_ht"], r["away_ht"],
        )
        for r in rows
    ]


def team_leagues(matches: list[MatchRecord]) -> dict[str, str]:
    """Her takımın en son oynadığı yerel (kupa olmayan) lig; hiç yoksa OTHER."""
    out: dict[str, str] = {}
    for m in matches:  # tarih sıralı -> son yazılan kazanır
        lg = LEAGUE_BY_SLUG.get(m.league)
        if lg is None or lg.is_cup:
            continue
        out[m.home] = m.league
        out[m.away] = m.league
    for m in matches:
        out.setdefault(m.home, OTHER)
        out.setdefault(m.away, OTHER)
    return out


def build_count_data(
    matches: list[MatchRecord], as_of: datetime, xi: float, values: dict[str, tuple[float, float]] | None = None,
    min_weight: float = 1e-3,
) -> CountData:
    """values verilirse (maç id -> (ev, dep)) hedef olarak gol yerine bu değerler kullanılır (şut/korner)."""
    tl = team_leagues(matches)
    teams = sorted(tl)
    tix = {t: i for i, t in enumerate(teams)}
    comps = sorted({m.league for m in matches})
    cix = {c: i for i, c in enumerate(comps)}
    hi, ai, ci, ne, yh, ya, ww, gh_, ga_ = [], [], [], [], [], [], [], [], []
    for m in matches:
        days = (as_of - m.date).total_seconds() / 86400.0
        w = float(np.exp(-xi * max(days, 0.0)))
        if w < min_weight:
            continue
        if values is not None:
            v = values.get(m.id)
            if v is None:
                continue
            h, a = v
        else:
            h, a = m.hg, m.ag
        hi.append(tix[m.home]); ai.append(tix[m.away]); ci.append(cix[m.league])
        ne.append(1.0 if m.neutral else 0.0); yh.append(h); ya.append(a); ww.append(w)
        gh_.append(m.hg); ga_.append(m.ag)
    return CountData(
        home_idx=np.array(hi, dtype=np.int64), away_idx=np.array(ai, dtype=np.int64), comp_idx=np.array(ci, dtype=np.int64),
        neutral=np.array(ne), y_home=np.array(yh, dtype=float), y_away=np.array(ya, dtype=float), weight=np.array(ww),
        teams=teams, team_league=[tl[t] for t in teams], comps=comps,
        comp_is_cup=[bool(LEAGUE_BY_SLUG[c].is_cup) if c in LEAGUE_BY_SLUG else True for c in comps],
        g_home=np.array(gh_, dtype=float), g_away=np.array(ga_, dtype=float),
    )


def dc_tau(x: np.ndarray, y: np.ndarray, lh: np.ndarray, la: np.ndarray, rho: float) -> np.ndarray:
    t = np.ones_like(lh)
    m00 = (x == 0) & (y == 0)
    m01 = (x == 0) & (y == 1)
    m10 = (x == 1) & (y == 0)
    m11 = (x == 1) & (y == 1)
    t = np.where(m00, 1 - lh * la * rho, t)
    t = np.where(m01, 1 + lh * rho, t)
    t = np.where(m10, 1 + la * rho, t)
    t = np.where(m11, 1 - rho, t)
    return t


def rho_bounds(lh: float | np.ndarray, la: float | np.ndarray) -> tuple[float, float]:
    """Her maçta tau>0 için: max(-1/lh, -1/la) <= rho <= min(1, 1/(lh*la))."""
    lh = np.atleast_1d(lh)
    la = np.atleast_1d(la)
    lo = float(np.max(np.maximum(-1 / lh, -1 / la)))
    hi = float(np.min(np.minimum(1.0, 1 / (lh * la))))
    return lo, hi


def fit_rho(data: CountData, model: CountModel) -> float:
    eh = model.mu + model.home[data.comp_idx] * (1 - data.neutral) + model.delta[data.comp_idx] + model.att[data.home_idx] - model.defn[data.away_idx]
    ea = model.mu + model.delta[data.comp_idx] + model.att[data.away_idx] - model.defn[data.home_idx]
    lh, la = np.exp(eh), np.exp(ea)
    x = data.g_home if data.g_home is not None else data.y_home
    y = data.g_away if data.g_away is not None else data.y_away
    w = data.weight
    lo, hi = rho_bounds(lh, la)
    lo, hi = max(lo + 1e-6, -0.3), min(hi - 1e-6, 0.3)
    low = (x <= 1) & (y <= 1)

    def nll(r: float) -> float:
        t = dc_tau(x[low], y[low], lh[low], la[low], r)
        return -float(np.sum(w[low] * np.log(np.maximum(t, 1e-12))))

    res = minimize_scalar(nll, bounds=(lo, hi), method="bounded")
    return float(res.x)


def calibrate_matrix(sm: np.ndarray, t: float) -> np.ndarray:
    """Sıcaklık kalibrasyonu: M ∝ M^t (t<1 dağılımı yayar, t>1 sivriltir). t=1 kimlik."""
    if abs(t - 1.0) < 1e-12:
        return sm
    m = np.clip(sm, 1e-15, 1.0) ** t
    return m / m.sum()


def score_matrix_cal(lh: float, la: float, rho: float, t: float = 1.0, g: float = 1.0) -> np.ndarray:
    """Kalibre skor matrisi: gol seviyesi çarpanı g ve sıcaklık t (backtest ayarlama diliminde öğrenilir)."""
    return calibrate_matrix(score_matrix(lh * g, la * g, rho), t)


def score_matrix(lh: float, la: float, rho: float, n: int = MAX_GOALS) -> np.ndarray:
    k = np.arange(n + 1)
    ph = poisson.pmf(k, lh)
    pa = poisson.pmf(k, la)
    # Kuyruk olasılığını son hücreye ekle (toplam 1 olsun)
    ph[-1] += max(0.0, 1 - ph.sum())
    pa[-1] += max(0.0, 1 - pa.sum())
    M = np.outer(ph, pa)
    lo, hi = rho_bounds(lh, la)
    r = float(np.clip(rho, lo + 1e-9, hi - 1e-9))
    M[0, 0] *= 1 - lh * la * r
    M[0, 1] *= 1 + lh * r
    M[1, 0] *= 1 + la * r
    M[1, 1] *= 1 - r
    return M / M.sum()


def first_half_share(con: sqlite3.Connection, before: str, prior_k: float = 300.0) -> tuple[dict[str, float], float]:
    """Lig bazında 1. yarı gol payı (yalnızca as_of öncesi gol dakikalarından), genel orana büzülmüş."""
    rows = con.execute(
        """SELECT m.league, SUM(CASE WHEN g.period=1 THEN 1 ELSE 0 END) g1, COUNT(*) g
           FROM goal_events g JOIN matches m ON m.id=g.match_id
           WHERE m.completed=1 AND m.date_utc < ? AND g.period IN (1,2)
           GROUP BY m.league""",
        (before,),
    ).fetchall()
    tot1 = sum(r["g1"] for r in rows)
    tot = sum(r["g"] for r in rows)
    glob = tot1 / tot if tot else 0.44
    return {r["league"]: (r["g1"] + prior_k * glob) / (r["g"] + prior_k) for r in rows}, glob


@dataclass
class GoalModel:
    counts: CountModel
    rho: float
    p1: dict[str, float]
    p1_global: float
    as_of: str
    xi: float
    sigma: float
    tau: float
    n_matches: int
    alpha: float = 1.0
    cal_t: float = 1.0
    cal_g: float = 1.0
    xg_weight: float = 0.0

    def matrix(self, lh: float, la: float) -> np.ndarray:
        return score_matrix_cal(lh, la, self.rho, self.cal_t, self.cal_g)

    def rates(self, comp: str, home: str, away: str, neutral: bool = False) -> tuple[float, float] | None:
        lr = self.counts.log_rates(comp, home, away, neutral)
        if lr is None:
            return None
        return float(np.exp(lr[0])), float(np.exp(lr[1]))

    def confidence(self, comp: str, home: str, away: str) -> tuple[str, list[str]]:
        notes: list[str] = []
        level = "yüksek"
        for t in (home, away):
            i = self.counts.team_index.get(t)
            if i is None:
                return "yok", ["Takım verisi yok"]
            wt = float(self.counts.team_weight[i])
            if wt < 4:
                level = "düşük"
                notes.append("Takımın yakın dönem maç verisi çok az")
            elif wt < 10 and level == "yüksek":
                level = "orta"
                notes.append("Takımın yakın dönem maç verisi sınırlı")
        lh = self.counts.team_league[self.counts.team_index[home]]
        la = self.counts.team_league[self.counts.team_index[away]]
        if lh != la:
            for lg in (lh, la):
                cw = self.counts.league_cross_weight.get(lg, 0.0)
                if lg == OTHER or cw < 8:
                    level = "düşük"
                    notes.append("Ligler arası karşılaştırma zayıf bağlantıya / priora dayanıyor")
                    break
        return level, notes


def sot_composite(con: sqlite3.Connection, matches: list[MatchRecord], before: str, alpha: float,
                  prior_k: float = 400.0) -> dict[str, tuple[float, float]] | None:
    """Şut tabanlı güç için bileşik hedef: y = α·gol + (1-α)·dönüşüm_lig·isabetli_şut.

    İsabetli şut, gelecekteki gol üretimini goldan daha az gürültüyle gösterir. Lig dönüşüm oranı (gol / isabetli şut)
    yalnızca kesim öncesi maçlardan ve genel orana büzülerek hesaplanır. İstatistiği olmayan maçlarda hedef = gol.
    """
    if alpha >= 0.999:
        return None
    rows = con.execute(
        """SELECT s.match_id, s.is_home, s.shots_on_target v FROM team_match_stats s JOIN matches m ON m.id=s.match_id
           WHERE m.completed=1 AND m.extra_time=0 AND m.date_utc < ? AND s.shots_on_target IS NOT NULL""",
        (before,),
    ).fetchall()
    sot: dict[str, dict[int, float]] = {}
    for r in rows:
        sot.setdefault(r["match_id"], {})[int(r["is_home"])] = float(r["v"])
    by_id = {m.id: m for m in matches}
    lg_g: dict[str, float] = {}
    lg_s: dict[str, float] = {}
    for mid, d in sot.items():
        m = by_id.get(mid)
        if m is None or 0 not in d or 1 not in d:
            continue
        lg_g[m.league] = lg_g.get(m.league, 0.0) + m.hg + m.ag
        lg_s[m.league] = lg_s.get(m.league, 0.0) + d[1] + d[0]
    tg, ts = sum(lg_g.values()), sum(lg_s.values())
    glob = tg / ts if ts > 0 else 0.3
    conv = {lg: (lg_g[lg] + prior_k * glob) / (lg_s[lg] + prior_k) for lg in lg_g}
    out: dict[str, tuple[float, float]] = {}
    for m in matches:
        d = sot.get(m.id)
        if d and 0 in d and 1 in d:
            c = conv.get(m.league, glob)
            out[m.id] = (alpha * m.hg + (1 - alpha) * c * d[1], alpha * m.ag + (1 - alpha) * c * d[0])
        else:
            out[m.id] = (float(m.hg), float(m.ag))
    return out


def load_xg(con: sqlite3.Connection, before: str) -> dict[str, tuple[float, float]]:
    """Kesimden önce oynanmış maçların xG'si (maç id -> (ev, dep)). Tablo yoksa (eski kurulum) boş."""
    try:
        rows = con.execute(
            """SELECT x.match_id, x.xg_home, x.xg_away FROM match_xg x JOIN matches m ON m.id=x.match_id
               WHERE m.completed=1 AND m.date_utc < ?""",
            (before,),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: (float(r[1]), float(r[2])) for r in rows}


def xg_composite(con: sqlite3.Connection, matches: list[MatchRecord], before: str, alpha: float, xg_weight: float,
                 prior_k: float = 300.0) -> dict[str, tuple[float, float]] | None:
    """Gol / isabetli şut karışımına xG eklenmiş hedef.

    xG'li maçta: y = (1-w)·[α·gol + (1-α)·dönüşüm·isabetli_şut] + w·ölçek_lig·xG   (w = xg_weight)
    xG'siz maçta hedef sot_composite ile aynıdır. Lig ölçeği (gol / xG) yalnızca kesim öncesi xG'li maçlardan ve genel
    orana büzülerek hesaplanır (Understat xG'si gol seviyesine zaten yakın; ölçek ligler arası küçük sapmaları alır).
    w <= 0 iken sot_composite'in kendisi döner (eski model, bit-bit aynı).
    """
    base = sot_composite(con, matches, before, alpha)
    if xg_weight <= 0:
        return base
    xg = load_xg(con, before)
    if not xg:
        return base
    by_id = {m.id: m for m in matches}
    lg_g: dict[str, float] = {}
    lg_x: dict[str, float] = {}
    for mid, (xh, xa) in xg.items():
        m = by_id.get(mid)
        if m is None:
            continue
        lg_g[m.league] = lg_g.get(m.league, 0.0) + m.hg + m.ag
        lg_x[m.league] = lg_x.get(m.league, 0.0) + xh + xa
    tg, tx = sum(lg_g.values()), sum(lg_x.values())
    glob = tg / tx if tx > 0 else 1.0
    scale = {lg: (lg_g[lg] + prior_k * glob) / (lg_x[lg] + prior_k) for lg in lg_g}
    w = min(float(xg_weight), 1.0)
    out: dict[str, tuple[float, float]] = {}
    for m in matches:
        b = base.get(m.id) if base is not None else None
        bh, ba = b if b is not None else (float(m.hg), float(m.ag))
        x = xg.get(m.id)
        if x is None:
            out[m.id] = (bh, ba)
            continue
        c = scale.get(m.league, glob)
        out[m.id] = ((1 - w) * bh + w * c * x[0], (1 - w) * ba + w * c * x[1])
    return out


def fit_goal_model(con: sqlite3.Connection, as_of: datetime, xi: float, sigma: float, tau: float, alpha: float = 1.0,
                   cal_t: float = 1.0, cal_g: float = 1.0,
                   xg_weight: float = 0.0) -> tuple[GoalModel, list[MatchRecord], CountData]:
    before = result_cutoff(as_of)
    matches = load_matches(con, before)
    values = sot_composite(con, matches, before, alpha) if xg_weight <= 0 else xg_composite(
        con, matches, before, alpha, xg_weight)
    data = build_count_data(matches, as_of, xi, values=values)
    cm = fit_count_model(data, REFERENCE_LEAGUE, sigma=sigma, tau=tau)
    rho = fit_rho(data, cm)
    p1, p1g = first_half_share(con, before)
    gm = GoalModel(cm, rho, p1, p1g, before, xi, sigma, tau, len(data.weight), alpha, cal_t, cal_g, xg_weight)
    return gm, matches, data
