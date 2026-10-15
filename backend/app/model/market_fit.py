"""Piyasanın ima ettiği skor dağılımı ve model-piyasa harmanı (skor matrisi düzeyinde).

Pazar bazında ayrı ayrı harmanlamak, aynı olayın olasılığının pazardan pazara değişmesine yol açar
(ör. P(MS=1) ≠ P(1 ve KG Var)+P(1 ve KG Yok)). Bunun yerine:
  1) iddaa'nın marjı arındırılmış ana pazarlarına (MS, A/Ü, KG, takım golleri, handikap) en iyi uyan
     Dixon-Coles skor matrisi M_q bulunur (KL ıraksaması, λ_ev ve λ_dep üzerinde).
  2) Harman: M ∝ M_model^w · M_q^(1-w)  (hücre bazında geometrik havuz, normalize).
  3) Tüm pazar olasılıkları bu TEK matristen türetilir -> pazarlar arası tutarlı.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from . import markets as mk
from .goals import score_matrix

CORE_KEYS = ("ms", "au", "kg", "ev_au", "dep_au", "hnd")


@dataclass
class MarketTarget:
    key: str
    line: str | None
    names: list[str]
    q: list[float]


def fit_market_matrix(targets: list[MarketTarget], rho: float, start: tuple[float, float]) -> tuple[float, float, float] | None:
    """Dönüş: (λ_ev, λ_dep, KL) ya da MS pazarı yoksa None."""
    tg = [t for t in targets if t.key in CORE_KEYS]
    if not any(t.key == "ms" for t in tg):
        return None
    k = np.arange(11)
    X, Y = np.meshgrid(k, k, indexing="ij")
    Z = np.zeros_like(X)
    probe = mk.Joint(np.ones((11, 11)), X, Y, Z, Z)
    masks: list[tuple[list[np.ndarray], np.ndarray]] = []
    for t in tg:
        ms_ = [mk.outcome_mask(t.key, t.line, n, probe) for n in t.names]
        if any(m is None for m in ms_):
            continue
        masks.append(([m for m in ms_ if m is not None], np.array(t.q)))

    def kl(x: np.ndarray) -> float:
        sm = score_matrix(float(np.exp(x[0])), float(np.exp(x[1])), rho)
        tot = 0.0
        for mlist, q in masks:
            p = np.array([sm[m].sum() for m in mlist])
            p = np.clip(p / p.sum(), 1e-9, 1.0)
            tot += float(np.sum(q * np.log(np.clip(q, 1e-9, 1.0) / p)))
        return tot

    x0 = np.log(np.clip(np.array(start), 0.05, 6.0))
    res = minimize(kl, x0, method="Nelder-Mead", options={"xatol": 1e-4, "fatol": 1e-7, "maxiter": 400})
    lh, la = float(np.exp(res.x[0])), float(np.exp(res.x[1]))
    if not (0.02 < lh < 8 and 0.02 < la < 8):
        return None
    return lh, la, float(res.fun)


def blend_matrix(model: np.ndarray, market: np.ndarray, w: float) -> np.ndarray:
    m = np.clip(model, 1e-12, 1.0) ** w * np.clip(market, 1e-12, 1.0) ** (1.0 - w)
    return m / m.sum()


def ms_probs(sm: np.ndarray) -> list[float]:
    return [float(np.tril(sm, -1).sum()), float(np.trace(sm)), float(np.triu(sm, 1).sum())]
