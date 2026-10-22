"""Korner ve kart pazarları: takım başına sayım ortalamalarından (hiyerarşik log-lineer model, count_model) ortak dağılım
ve iddaa pazar olasılıkları.

Ortak dağılım "toplam + pay" kurgusuyla kurulur (tüm pazarlar tek matristen -> birbiriyle tutarlı):
    T = H + A ~ NB(mu_T, k_toplam),   mu_T = m_L · ((mu_H + mu_A) / m_L)^beta
    H | T     ~ BetaBinom(T, pi = mu_H / (mu_H + mu_A), phi)
m_L, iki takımın liglerinin ortalama takımları için modelin beklediği toplamdır. beta < 1 toplam beklentisini lig
ortalamasına çeker: ayarlama dilimlerinde korner toplamı tahminleri fazla yayılıyordu (tahmini 8,6 olan maçlarda gerçek
ortalama 9,1; 10,9 olanlarda 10,5), takımın korner payı ise (ev/deplasman, kim daha çok, handikap) takım etkilerinden
fayda görüyordu; beta yalnız toplamı büzer, payı değiştirmez.
İki bağımsız NB yerine bu kurgu seçildi çünkü kornerlerde ev ve deplasman sayıları maç içinde negatif ilişkili
(ayarlama diliminde artık korelasyonu ≈ -0,23: baskı kuran takım korner kazanır, rakibi kazanamaz); bağımsız toplam bu
ilişkiyi yok sayar. k_toplam toplam çizgilerinin log-loss'uyla, phi payın olabilirliğiyle ayarlama+doğrulama
dilimlerinde seçilir (backtest.tune_aux); değerlendirme dilimi karara karışmaz.

Kart sayımı iddaa kuralıdır (sarı 1, kırmızı 2; ikinci sarıyla atılan oyuncu 1+2): espn.card_counts.
İlk yarı kart: toplam kart puanı lig bazında ilk yarı payıyla binom inceltilir (yaklaşık; kırmızı 2 puanı bölünmez
varsayımı yok sayılır). Kırmızı kart: takım başına seyrek-olay Poisson oranı (ayrı model), P(en az bir) = 1 - e^-(λ_H+λ_A).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.special import betaln, gammaln
from scipy.stats import binom

FAMILIES = ("korner", "kart")   # bu modülün fiyatladığı pazar aileleri (sources.iddaa.MarketDef.family)
CORNER_NMAX = 40
CARD_NMAX = 30

# Model kendi başına gösterilecek çizgiler (iddaa'nın sunduğu aralıkları kapsar)
CORNER_TOTAL_LINES = (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)
CORNER_HOME_LINES = (3.5, 4.5, 5.5, 6.5)
CORNER_AWAY_LINES = (2.5, 3.5, 4.5, 5.5)
CORNER_HANDICAPS = (-3.5, -2.5, -1.5, 1.5, 2.5)
CORNER_RANGES = ("0-8", "9-11", "12+")
CARD_TOTAL_LINES = (2.5, 3.5, 4.5, 5.5, 6.5)
CARD_HT_LINES = (0.5, 1.5, 2.5)


@dataclass(frozen=True)
class CountDist:
    """Ortak dağılım parametreleri: k_total toplamın NB dağılım parametresi, phi ev payının beta-binom yoğunluğu,
    beta toplam beklentisinin lig ortalamasına büzülme üssü (1 = büzülme yok)."""
    k_total: float
    phi: float
    beta: float = 1.0


def shrink_means(mu_home: float, mu_away: float, league_total: float | None, beta: float) -> tuple[float, float]:
    """Toplam beklentisini lig ortalamasına (log ölçekte) beta oranında çeker; ev/deplasman payı korunur."""
    mt = mu_home + mu_away
    if league_total is None or league_total <= 0 or beta == 1.0 or mt <= 0:
        return mu_home, mu_away
    mt_c = league_total * (mt / league_total) ** beta
    return mu_home * mt_c / mt, mu_away * mt_c / mt


@dataclass
class CountJoint:
    P: np.ndarray                     # P[h, a]
    H: np.ndarray
    A: np.ndarray
    mu_home: float
    mu_away: float
    ht_share: float | None = None     # ilk yarı payı (yalnız kart)
    p_red: float | None = None        # en az bir kırmızı kart olasılığı (yalnız kart)

    def total_pmf(self) -> np.ndarray:
        n = self.P.shape[0]
        T = (self.H + self.A).ravel()
        return np.bincount(T, weights=self.P.ravel(), minlength=2 * n - 1)[:n]

    def ht_total_pmf(self) -> np.ndarray | None:
        if self.ht_share is None:
            return None
        pt = self.total_pmf()
        t = np.arange(pt.size)
        B = binom.pmf(t[None, :], t[:, None], self.ht_share)   # B[T, i] = P(İY = i | T)
        return pt @ B


def nb_pmf(mu: float, k: float, nmax: int) -> np.ndarray:
    x = np.arange(nmax + 1)
    mu = max(float(mu), 1e-9)
    lp = gammaln(x + k) - gammaln(k) - gammaln(x + 1) + k * np.log(k / (k + mu)) + x * np.log(mu / (k + mu))
    p = np.exp(lp)
    return p / p.sum()


def split_matrix(pi: float, phi: float, nmax: int) -> np.ndarray:
    """C[T, h] = P(H = h | T) beta-binom(T, pi·phi, (1-pi)·phi); h > T için 0."""
    x = np.arange(nmax + 1)
    T = x[:, None]
    h = x[None, :]
    valid = h <= T
    rest = np.where(valid, T - h, 0)
    a, b = max(pi, 1e-6) * phi, max(1.0 - pi, 1e-6) * phi
    lc = gammaln(T + 1) - gammaln(h + 1) - gammaln(rest + 1) + betaln(h + a, rest + b) - betaln(a, b)
    return np.where(valid, np.exp(np.where(valid, lc, 0.0)), 0.0)


def count_joint(mu_home: float, mu_away: float, dist: CountDist, nmax: int, ht_share: float | None = None,
                p_red: float | None = None) -> CountJoint:
    mt = mu_home + mu_away
    pT = nb_pmf(mt, dist.k_total, nmax)
    C = split_matrix(mu_home / mt, dist.phi, nmax)
    Tg, hg = np.nonzero(C > 0)
    P = np.zeros((nmax + 1, nmax + 1))
    P[hg, Tg - hg] = pT[Tg] * C[Tg, hg]
    x = np.arange(nmax + 1)
    H, A = np.meshgrid(x, x, indexing="ij")
    return CountJoint(P, H, A, mu_home, mu_away, ht_share, p_red)


def _range_mask(name: str, T: np.ndarray) -> np.ndarray | None:
    n = name.replace(" ", "")
    if n.endswith("+") and n[:-1].isdigit():
        return T >= int(n[:-1])
    if "-" in n:
        lo, hi = n.split("-", 1)
        if lo.isdigit() and hi.isdigit():
            return (T >= int(lo)) & (T <= int(hi))
    return None


def _three_way(H: np.ndarray, A: np.ndarray) -> dict[str, np.ndarray]:
    return {"1": H > A, "0": H == A, "2": H < A}


AUX_KEYS = frozenset({"korner_au", "korner_ar", "ev_korner_au", "dep_korner_au", "korner_kdc", "korner_hnd",
                      "kart_au", "iy_kart_au", "kart_kdc", "kirmizi"})


def outcome_prob(key: str, sov: str | None, name: str, j: CountJoint) -> float | None:
    """iddaa sonuç adı için model olasılığı. Tanınmayan ad / çizgi -> None (o sonuç fiyatlanmaz)."""
    n = name.strip()
    line = float(sov) if sov not in (None, "") else None
    H, A, P = j.H, j.A, j.P
    T = H + A
    if key in ("korner_au", "kart_au", "ev_korner_au", "dep_korner_au") and line is not None:
        v = {"korner_au": T, "kart_au": T, "ev_korner_au": H, "dep_korner_au": A}[key]
        m = {"Alt": v < line, "Üst": v > line}.get(n)
        return float(P[m].sum()) if m is not None else None
    if key == "korner_ar":
        m = _range_mask(n, T)
        return float(P[m].sum()) if m is not None else None
    if key in ("korner_kdc", "kart_kdc"):
        m = _three_way(H, A).get(n)
        return float(P[m].sum()) if m is not None else None
    if key == "korner_hnd" and line is not None:
        m = _three_way(H + line, A).get(n)
        return float(P[m].sum()) if m is not None else None
    if key == "iy_kart_au" and line is not None:
        ht = j.ht_total_pmf()
        if ht is None:
            return None
        i = np.arange(ht.size)
        m = {"Alt": i < line, "Üst": i > line}.get(n)
        return float(ht[m].sum()) if m is not None else None
    if key == "kirmizi" and j.p_red is not None:
        return {"Evet": j.p_red, "Hayır": 1.0 - j.p_red}.get(n)
    return None


@dataclass(frozen=True)
class AuxResult:
    """Gerçekleşen 90 dk değerleri: ev / deplasman sayımı (korner ya da kart puanı), ilk yarı kart toplamı, kırmızı."""
    home: int
    away: int
    ht_total: int | None = None
    reds: int | None = None


def settle(key: str, sov: str | None, name: str, r: AuxResult) -> str | None:
    """Seçim sonucu: "won" | "lost" | "void" (tam sayı handikapta eşitlik: iade) | None (veri yok / tanınmayan)."""
    n = name.strip()
    line = float(sov) if sov not in (None, "") else None
    T = r.home + r.away

    def au(v: int) -> str | None:
        if line is None or n not in ("Alt", "Üst"):
            return None
        if v == line:
            return "void"
        return "won" if (n == "Üst") == (v > line) else "lost"

    if key in ("korner_au", "kart_au"):
        return au(T)
    if key == "ev_korner_au":
        return au(r.home)
    if key == "dep_korner_au":
        return au(r.away)
    if key == "iy_kart_au":
        return au(r.ht_total) if r.ht_total is not None else None
    if key == "korner_ar":
        m = _range_mask(n, np.array(T))
        return None if m is None else ("won" if bool(m) else "lost")
    if key in ("korner_kdc", "kart_kdc"):
        res = "1" if r.home > r.away else "0" if r.home == r.away else "2"
        return None if n not in ("1", "0", "2") else ("won" if n == res else "lost")
    if key == "korner_hnd" and line is not None:
        adj = r.home + line
        if adj == r.away and n in ("1", "2"):
            return "void"
        res = "1" if adj > r.away else "0" if adj == r.away else "2"
        return None if n not in ("1", "0", "2") else ("won" if n == res else "lost")
    if key == "kirmizi" and r.reds is not None and n in ("Evet", "Hayır"):
        return "won" if (n == "Evet") == (r.reds > 0) else "lost"
    return None


def red_prob(lam_home: float, lam_away: float) -> float:
    """Takım başına kırmızı kart beklentisi (Poisson) -> maçta en az bir kırmızı kart olasılığı."""
    return float(1.0 - np.exp(-(lam_home + lam_away)))


def corner_view(j: CountJoint, dist: CountDist) -> dict:
    """Maç sayfası için korner özeti (model olasılıkları)."""
    def au(key: str, L: float) -> dict[str, float]:
        return {nm: outcome_prob(key, str(L), nm, j) or 0.0 for nm in ("Alt", "Üst")}

    return {
        "mu_home": j.mu_home, "mu_away": j.mu_away, "k": dist.k_total, "phi": dist.phi,
        "lines": {str(L): au("korner_au", L) for L in CORNER_TOTAL_LINES},
        "home_lines": {str(L): au("ev_korner_au", L) for L in CORNER_HOME_LINES},
        "away_lines": {str(L): au("dep_korner_au", L) for L in CORNER_AWAY_LINES},
        "kdc": {nm: outcome_prob("korner_kdc", None, nm, j) or 0.0 for nm in ("1", "0", "2")},
        "ranges": {nm: outcome_prob("korner_ar", None, nm, j) or 0.0 for nm in CORNER_RANGES},
        "handicap": {str(L): {nm: outcome_prob("korner_hnd", str(L), nm, j) or 0.0 for nm in ("1", "2")}
                     for L in CORNER_HANDICAPS},
    }


def card_view(j: CountJoint, dist: CountDist, red_home: float | None, red_away: float | None) -> dict:
    """Maç sayfası için kart özeti (iddaa sayımı: sarı 1, kırmızı 2)."""
    def au(key: str, L: float) -> dict[str, float]:
        return {nm: outcome_prob(key, str(L), nm, j) or 0.0 for nm in ("Alt", "Üst")}

    return {
        "mu_home": j.mu_home, "mu_away": j.mu_away, "k": dist.k_total, "phi": dist.phi,
        "lines": {str(L): au("kart_au", L) for L in CARD_TOTAL_LINES},
        "ht_lines": {str(L): au("iy_kart_au", L) for L in CARD_HT_LINES} if j.ht_share is not None else {},
        "ht_share": j.ht_share,
        "kdc": {nm: outcome_prob("kart_kdc", None, nm, j) or 0.0 for nm in ("1", "0", "2")},
        "p_red": j.p_red, "red_home": red_home, "red_away": red_away,
    }


# ---------------------------------------------------------------- backtest alt pazarları

def line_name(key: str, line: float | str) -> str:
    """Alt pazar / çizgi adı (backtest raporu ve çizgi bazında doğrulama anahtarı): "korner_au 9.5", "korner_hnd -1.5"."""
    return f"{key} {float(line):g}"

# (ad, sonuç fonksiyonu (ev, dep, ev_iy, dep_iy, kırmızı) -> sınıf, sınıf sayısı, model olasılık fonksiyonu)

Outcome = Callable[[int, int, int | None, int | None, int | None], int | None]


@dataclass(frozen=True)
class SubMarket:
    name: str              # rapor anahtarı (ör. "korner_au 9.5")
    key: str               # MARKETS anahtarı (pazar başına doğrulama bayrağı)
    k: int
    outcome: Outcome
    probs: Callable[[CountJoint], list[float] | None]


def _au(key: str, L: float, side: str) -> SubMarket:
    def outc(h: int, a: int, hh: int | None, ah: int | None, r: int | None) -> int | None:
        if side == "iy":
            return None if hh is None or ah is None else int(hh + ah > L)
        v = {"tot": h + a, "ev": h, "dep": a}[side]
        return int(v > L)

    def pr(j: CountJoint) -> list[float] | None:
        u = outcome_prob(key, str(L), "Üst", j)
        return None if u is None else [1.0 - u, u]

    return SubMarket(line_name(key, L), key, 2, outc, pr)


def _kdc(key: str) -> SubMarket:
    def pr(j: CountJoint) -> list[float]:
        return [outcome_prob(key, None, nm, j) or 0.0 for nm in ("1", "0", "2")]

    return SubMarket(key, key, 3, lambda h, a, hh, ah, r: 0 if h > a else 1 if h == a else 2, pr)


def _hnd(L: float) -> SubMarket:
    def pr(j: CountJoint) -> list[float]:
        p1 = outcome_prob("korner_hnd", str(L), "1", j) or 0.0
        return [1.0 - p1, p1]

    return SubMarket(line_name("korner_hnd", L), "korner_hnd", 2, lambda h, a, hh, ah, r: int(h + L > a), pr)


def _range() -> SubMarket:
    def pr(j: CountJoint) -> list[float]:
        return [outcome_prob("korner_ar", None, nm, j) or 0.0 for nm in CORNER_RANGES]

    return SubMarket("korner_ar", "korner_ar", 3, lambda h, a, hh, ah, r: 0 if h + a <= 8 else 1 if h + a <= 11 else 2, pr)


def _red() -> SubMarket:
    def pr(j: CountJoint) -> list[float] | None:
        return None if j.p_red is None else [1.0 - j.p_red, j.p_red]

    return SubMarket("kirmizi", "kirmizi", 2, lambda h, a, hh, ah, r: None if r is None else int(r > 0), pr)


# Doğrulama çizgileri: iddaa'nın sık sunduğu çizgiler (toplam korner 7.5–11.5, kart 2.5–5.5)
CORNER_SUBMARKETS: tuple[SubMarket, ...] = (
    *(_au("korner_au", L, "tot") for L in (7.5, 8.5, 9.5, 10.5, 11.5)),
    *(_au("ev_korner_au", L, "ev") for L in (4.5, 5.5)),
    *(_au("dep_korner_au", L, "dep") for L in (3.5, 4.5)),
    _kdc("korner_kdc"), _range(), _hnd(-1.5), _hnd(1.5),
)
CARD_SUBMARKETS: tuple[SubMarket, ...] = (
    *(_au("kart_au", L, "tot") for L in (2.5, 3.5, 4.5, 5.5)),
    *(_au("iy_kart_au", L, "iy") for L in (0.5, 1.5, 2.5)),
    _kdc("kart_kdc"), _red(),
)
# Toplam çizgileri: k_toplam bu çizgilerin ortalama log-loss'uyla seçilir
CORNER_TUNE_LINES = (7.5, 8.5, 9.5, 10.5, 11.5)
CARD_TUNE_LINES = (2.5, 3.5, 4.5, 5.5)
K_TOTAL_GRID = (6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 60.0, 100.0)
BETA_GRID = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def total_lines_logloss(mu_t: np.ndarray, totals: np.ndarray, k: float, lines: tuple[float, ...]) -> float:
    """NB(mu_t, k) toplam dağılımının verilen çizgilerdeki ortalama ikili log-loss'u."""
    from scipy.stats import nbinom

    out = 0.0
    for L in lines:
        p = np.clip(1.0 - nbinom.cdf(np.floor(L), k, k / (k + mu_t)), 1e-9, 1 - 1e-9)
        y = totals > L
        out += float(-np.mean(np.where(y, np.log(p), np.log(1 - p))))
    return out / len(lines)


def fit_total(mu_t: np.ndarray, league_t: np.ndarray, totals: np.ndarray, lines: tuple[float, ...]
              ) -> tuple[float, float, float]:
    """(beta, k_toplam, log-loss): toplam çizgilerinin ortalama log-loss'unu en küçükleyen ızgara noktası."""
    best = (1.0, K_TOTAL_GRID[0], float("inf"))
    for beta in BETA_GRID:
        mt = league_t * (mu_t / league_t) ** beta
        for k in K_TOTAL_GRID:
            ll = total_lines_logloss(mt, totals, k, lines)
            if ll < best[2]:
                best = (beta, k, ll)
    return best


def fit_phi(pi: np.ndarray, h: np.ndarray, t: np.ndarray) -> float:
    """Ev payının beta-binom yoğunluğu (ML): H | T ~ BetaBinom(T, pi·phi, (1-pi)·phi). T=0 maçlar bilgi taşımaz."""
    from scipy.optimize import minimize_scalar

    msk = t > 0
    pi, h, t = np.clip(pi[msk], 1e-4, 1 - 1e-4), h[msk], t[msk]

    def nll(lphi: float) -> float:
        phi = float(np.exp(lphi))
        a, b = pi * phi, (1 - pi) * phi
        return float(-np.sum(betaln(h + a, t - h + b) - betaln(a, b)))

    res = minimize_scalar(nll, bounds=(np.log(1.0), np.log(1000.0)), method="bounded")
    return float(np.exp(res.x))
