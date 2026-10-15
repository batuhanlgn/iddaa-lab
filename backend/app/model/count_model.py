"""Ortak hiyerarşik log-lineer sayım modeli (goller, şutlar, kornerler).

    log E[y_ev]  = mu + h_C·(1-neutral) + delta_C + att_ev  - def_dep
    log E[y_dep] = mu                   + delta_C + att_dep - def_ev

    att_t = A_lig(t) + a_t ,  a: lig içinde toplamı sıfır (merkezlenmiş parametreleme)
    def_t = D_lig(t) + d_t
    A_ref = D_ref = 0 (referans lig) ; A, D ~ N(0, tau²) ; a, d ~ N(0, sigma²)

Lig ortalamalarının (A+D yönü) karşılaştırılabilirliği yalnızca ligler arası maçlarla (Avrupa/yerel kupa,
küme düşen/çıkan takımlar) belirlenir; bağlantısı zayıf liglerde bu yön priora dayanır ve raporlanır.
Ağırlıklı Poisson (zaman sönümü) penalize olabilirlik, L-BFGS-B ve analitik gradyanla çözülür.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import minimize

OTHER = "__other__"


@dataclass
class CountData:
    home_idx: np.ndarray      # takım indeksleri
    away_idx: np.ndarray
    comp_idx: np.ndarray      # yarışma indeksi
    neutral: np.ndarray       # 0/1
    y_home: np.ndarray
    y_away: np.ndarray
    weight: np.ndarray
    teams: list[str]
    team_league: list[str]    # her takımın (as_of anındaki) yerel ligi veya OTHER
    comps: list[str]
    comp_is_cup: list[bool]
    g_home: np.ndarray | None = None   # gerçek goller (hedef bileşik olsa da DC rho bunlarla fit edilir)
    g_away: np.ndarray | None = None


@dataclass
class CountModel:
    teams: list[str]
    team_index: dict[str, int]
    team_league: list[str]
    leagues: list[str]
    comps: list[str]
    comp_index: dict[str, int]
    comp_is_cup: list[bool]
    mu: float
    A: dict[str, float]
    D: dict[str, float]
    att: np.ndarray
    defn: np.ndarray
    home: np.ndarray
    delta: np.ndarray
    team_weight: np.ndarray          # takım başına efektif (ağırlıklı) maç sayısı
    league_cross_weight: dict[str, float] = field(default_factory=dict)
    converged: bool = True
    objective: float = 0.0

    def log_rates(self, comp: str, home_team: str, away_team: str, neutral: bool = False) -> tuple[float, float] | None:
        hi = self.team_index.get(home_team)
        ai = self.team_index.get(away_team)
        if hi is None or ai is None:
            return None
        ci = self.comp_index.get(comp)
        h = float(self.home[ci]) if ci is not None else float(np.median(self.home))
        dl = float(self.delta[ci]) if ci is not None else 0.0
        if neutral:
            h = 0.0
        eh = self.mu + h + dl + self.att[hi] - self.defn[ai]
        ea = self.mu + dl + self.att[ai] - self.defn[hi]
        return float(eh), float(ea)


def fit_count_model(
    data: CountData,
    reference_league: str,
    sigma: float,
    tau: float,
    home_prior: tuple[float, float] = (0.2, 0.2),
    delta_prior_sd: float = 0.25,
    max_iter: int = 600,
) -> CountModel:
    T = len(data.teams)
    C = len(data.comps)
    leagues = sorted({lg for lg in data.team_league if lg != reference_league})
    lg_index = {lg: i for i, lg in enumerate(leagues)}
    L = len(leagues)
    team_lg = np.array([lg_index.get(lg, -1) for lg in data.team_league])  # -1 = referans lig
    is_other = np.array([lg == OTHER for lg in data.team_league])
    centered = ~is_other

    # Merkezleme grubu: referans lig dahil her yerel lig için ayrı grup
    group_names = sorted(set(data.team_league))
    gidx = {g: i for i, g in enumerate(group_names)}
    team_group = np.array([gidx[g] for g in data.team_league])
    G = len(group_names)
    group_size = np.bincount(team_group, weights=centered.astype(float), minlength=G)
    group_size[group_size == 0] = 1.0

    cup_mask = np.array(data.comp_is_cup, dtype=bool)

    # Parametre düzeni: [mu | A(L) | D(L) | a_raw(T) | d_raw(T) | h(C) | delta(C)]
    o_mu = 0
    o_A = 1
    o_D = o_A + L
    o_a = o_D + L
    o_d = o_a + T
    o_h = o_d + T
    o_dl = o_h + C
    P = o_dl + C

    hi, ai, ci = data.home_idx, data.away_idx, data.comp_idx
    w = data.weight
    yh, ya = data.y_home, data.y_away
    nh = 1.0 - data.neutral

    def center(raw: np.ndarray) -> np.ndarray:
        means = np.bincount(team_group, weights=raw * centered, minlength=G) / group_size
        return np.where(centered, raw - means[team_group], raw)

    def center_grad(g: np.ndarray) -> np.ndarray:
        means = np.bincount(team_group, weights=g * centered, minlength=G) / group_size
        return np.where(centered, g - means[team_group], g)

    hp_mu, hp_sd = home_prior

    def unpack(x: np.ndarray):
        mu = x[o_mu]
        A = x[o_A:o_D]
        D = x[o_D:o_a]
        a = center(x[o_a:o_d])
        d = center(x[o_d:o_h])
        h = x[o_h:o_dl]
        dl = np.where(cup_mask, x[o_dl:P], 0.0)
        Afull = np.where(team_lg >= 0, A[np.maximum(team_lg, 0)] if L else 0.0, 0.0)
        Dfull = np.where(team_lg >= 0, D[np.maximum(team_lg, 0)] if L else 0.0, 0.0)
        att = Afull + a
        de = Dfull + d
        return mu, A, D, a, d, h, dl, att, de

    def fg(x: np.ndarray) -> tuple[float, np.ndarray]:
        mu, A, D, a, d, h, dl, att, de = unpack(x)
        eta_h = mu + h[ci] * nh + dl[ci] + att[hi] - de[ai]
        eta_a = mu + dl[ci] + att[ai] - de[hi]
        lam_h = np.exp(eta_h)
        lam_a = np.exp(eta_a)
        nll = float(np.sum(w * (lam_h - yh * eta_h)) + np.sum(w * (lam_a - ya * eta_a)))
        r_h = w * (lam_h - yh)
        r_a = w * (lam_a - ya)
        g = np.zeros(P)
        g[o_mu] = r_h.sum() + r_a.sum()
        g_att = np.bincount(hi, weights=r_h, minlength=T) + np.bincount(ai, weights=r_a, minlength=T)
        g_def = -np.bincount(ai, weights=r_h, minlength=T) - np.bincount(hi, weights=r_a, minlength=T)
        g_h = np.bincount(ci, weights=r_h * nh, minlength=C)
        g_dl = (np.bincount(ci, weights=r_h, minlength=C) + np.bincount(ci, weights=r_a, minlength=C)) * cup_mask
        # Priorlar
        nll += float(np.sum(a**2) + np.sum(d**2)) / (2 * sigma**2)
        g_a_c = a / sigma**2
        g_d_c = d / sigma**2
        if L:
            nll += float(np.sum(A**2) + np.sum(D**2)) / (2 * tau**2)
            msk = team_lg >= 0
            g[o_A:o_D] = np.bincount(team_lg[msk], weights=g_att[msk], minlength=L) + A / tau**2
            g[o_D:o_a] = np.bincount(team_lg[msk], weights=g_def[msk], minlength=L) + D / tau**2
        # Ham parametrelerde küçük ridge: merkezlemenin boş yönünü sabitler
        ra, rd = x[o_a:o_d], x[o_d:o_h]
        nll += 1e-4 * float(np.sum(ra**2) + np.sum(rd**2))
        g[o_a:o_d] = center_grad(g_att + g_a_c) + 2e-4 * ra
        g[o_d:o_h] = center_grad(g_def + g_d_c) + 2e-4 * rd
        nll += float(np.sum((h - hp_mu) ** 2)) / (2 * hp_sd**2)
        g[o_h:o_dl] = g_h + (h - hp_mu) / hp_sd**2
        dl_raw = x[o_dl:P]
        nll += float(np.sum(dl_raw**2)) / (2 * delta_prior_sd**2)
        g[o_dl:P] = g_dl + dl_raw / delta_prior_sd**2
        return nll, g

    x0 = np.zeros(P)
    tot_w = float(np.sum(w)) * 2
    mean_y = float(np.sum(w * (yh + ya)) / max(tot_w, 1e-9))
    x0[o_mu] = np.log(max(mean_y, 1e-3))
    x0[o_h:o_dl] = hp_mu
    res = minimize(fg, x0, jac=True, method="L-BFGS-B", options={"maxiter": max_iter, "maxfun": max_iter * 2})
    mu, A, D, a, d, h, dl, att, de = unpack(res.x)

    team_weight = np.bincount(hi, weights=w, minlength=T) + np.bincount(ai, weights=w, minlength=T)
    cross = (np.array(data.team_league)[hi] != np.array(data.team_league)[ai])
    lg_cross: dict[str, float] = {}
    tl = np.array(data.team_league)
    for k in np.nonzero(cross)[0]:
        for t in (hi[k], ai[k]):
            lg_cross[tl[t]] = lg_cross.get(tl[t], 0.0) + float(w[k])

    return CountModel(
        teams=list(data.teams),
        team_index={t: i for i, t in enumerate(data.teams)},
        team_league=list(data.team_league),
        leagues=[reference_league] + leagues,
        comps=list(data.comps),
        comp_index={c: i for i, c in enumerate(data.comps)},
        comp_is_cup=list(data.comp_is_cup),
        mu=float(mu),
        A={reference_league: 0.0, **{lg: float(A[i]) for lg, i in lg_index.items()}},
        D={reference_league: 0.0, **{lg: float(D[i]) for lg, i in lg_index.items()}},
        att=att,
        defn=de,
        home=h,
        delta=dl,
        team_weight=team_weight,
        league_cross_weight=lg_cross,
        converged=bool(res.success),
        objective=float(res.fun),
    )


def nb_dispersion(y: np.ndarray, mu: np.ndarray, w: np.ndarray, lo: float = 2.0, hi: float = 500.0) -> float:
    """Var = mu + mu²/k için ağırlıklı moment tahmini."""
    num = float(np.sum(w * mu**2))
    den = float(np.sum(w * ((y - mu) ** 2 - mu)))
    if den <= 0:
        return hi
    return float(np.clip(num / den, lo, hi))
