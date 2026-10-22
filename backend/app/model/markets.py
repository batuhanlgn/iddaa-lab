"""Pazar olasılıkları (DC skor matrisinden analitik), marj arındırma ve model-piyasa harmanı.

İY pazarları için FT skoru binom inceltmeyle yarılara bölünür: her gol bağımsız olarak p1 olasılıkla
1. yarıya düşer. Bu FT ortak dağılımını aynen korur; yarılara atama ek bir varsayımdır ve İY ailesi
backtest'te doğrulanmadan kupona girmez.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.stats import binom

from ..config import MAX_GOALS


@dataclass
class Joint:
    P: np.ndarray   # [ft_h, ft_a, ht_h, ht_a]
    X: np.ndarray
    Y: np.ndarray
    I: np.ndarray
    J: np.ndarray


def build_joint(score: np.ndarray, p1: float) -> Joint:
    n = score.shape[0]
    k = np.arange(n)
    # B[x, i] = P(HT=i | FT=x)
    B = binom.pmf(k[None, :], k[:, None], p1)
    P = score[:, :, None, None] * B[:, None, :, None] * B[None, :, None, :]
    X, Y, I, J = np.meshgrid(k, k, k, k, indexing="ij")
    return Joint(P, X, Y, I, J)


Pred = Callable[[Joint], np.ndarray]


def _res(a: np.ndarray, b: np.ndarray) -> dict[str, np.ndarray]:
    return {"1": a > b, "0": a == b, "2": a < b}


def outcome_mask(key: str, sov: str | None, name: str, j: Joint) -> np.ndarray | None:
    """iddaa sonuç adından olay maskesi. Tanınmayan ad -> None (o sonuç fiyatlanmaz)."""
    X, Y, I, J = j.X, j.Y, j.I, j.J
    T = X + Y
    n = name.strip()
    line = float(sov) if sov not in (None, "") else None
    ft = _res(X, Y)
    ht = _res(I, J)
    h2 = _res(X - I, Y - J)
    kg = {"Var": (X > 0) & (Y > 0), "Yok": ~((X > 0) & (Y > 0))}
    if key == "ms":
        return ft.get(n)
    if key in ("cs", "iy_cs"):
        base = ft if key == "cs" else ht
        parts = n.replace(" ", "").split("ve")
        if len(parts) == 2 and all(p in base for p in parts):
            return base[parts[0]] | base[parts[1]]
        return None
    if key == "iy":
        return ht.get(n)
    if key == "iy2":
        return h2.get(n)
    if key == "kg":
        return kg.get(n)
    if key == "iy_kg":
        return {"Var": (I > 0) & (J > 0), "Yok": ~((I > 0) & (J > 0))}.get(n)
    if key in ("au", "iy_au", "ev_au", "dep_au") and line is not None:
        v = {"au": T, "iy_au": I + J, "ev_au": X, "dep_au": Y}[key]
        return {"Alt": v < line, "Üst": v > line}.get(n)
    if key == "hnd" and line is not None:
        return _res(X + line, Y).get(n)
    if key == "iyms":
        if "/" in n:
            a, b = n.split("/", 1)
            if a in ht and b in ft:
                return ht[a] & ft[b]
        return None
    if key == "tc":
        return {"Tek": T % 2 == 1, "Çift": T % 2 == 0}.get(n)
    if key == "tg":
        return {"0-1 gol": T <= 1, "2-3 gol": (T >= 2) & (T <= 3), "4-5 gol": (T >= 4) & (T <= 5), "6+ gol": T >= 6}.get(n)
    if key == "cgy":
        g1, g2 = I + J, T - I - J
        return {"1.": g1 > g2, "Eşit": g1 == g2, "2.": g1 < g2}.get(n)
    if key in ("ms_au", "ms_kg", "au_kg"):
        parts = [p.strip() for p in n.split(" ve ")]
        if len(parts) != 2:
            return None
        au = {"Alt": T < (line if line is not None else 2.5), "Üst": T > (line if line is not None else 2.5)}
        if key == "ms_au" and parts[0] in ft and parts[1] in au:
            return ft[parts[0]] & au[parts[1]]
        if key == "ms_kg" and parts[0] in ft and parts[1] in kg:
            return ft[parts[0]] & kg[parts[1]]
        if key == "au_kg" and parts[0] in au and parts[1] in kg:
            return au[parts[0]] & kg[parts[1]]
        return None
    return None


def prob(j: Joint, mask: np.ndarray) -> float:
    return float(j.P[mask].sum())


# Model kendi başına (oran olmasa da) gösterilecek standart pazar listesi
STANDARD_MARKETS: list[tuple[str, str | None, list[str]]] = [
    ("ms", None, ["1", "0", "2"]),
    ("cs", None, ["1 ve 0", "1 ve 2", "0 ve 2"]),
    ("kg", None, ["Var", "Yok"]),
    ("au", "1.5", ["Alt", "Üst"]),
    ("au", "2.5", ["Alt", "Üst"]),
    ("au", "3.5", ["Alt", "Üst"]),
    ("ev_au", "0.5", ["Alt", "Üst"]),
    ("ev_au", "1.5", ["Alt", "Üst"]),
    ("dep_au", "0.5", ["Alt", "Üst"]),
    ("dep_au", "1.5", ["Alt", "Üst"]),
    ("hnd", "-1", ["1", "0", "2"]),
    ("hnd", "1", ["1", "0", "2"]),
    ("tg", None, ["0-1 gol", "2-3 gol", "4-5 gol", "6+ gol"]),
    ("tc", None, ["Tek", "Çift"]),
    ("iy", None, ["1", "0", "2"]),
    ("iy_au", "0.5", ["Alt", "Üst"]),
    ("iy_au", "1.5", ["Alt", "Üst"]),
    ("iyms", None, ["1/1", "1/0", "1/2", "0/1", "0/0", "0/2", "2/1", "2/0", "2/2"]),
    ("cgy", None, ["1.", "Eşit", "2."]),
    ("ms_kg", None, ["1 ve Var", "1 ve Yok", "0 ve Var", "0 ve Yok", "2 ve Var", "2 ve Yok"]),
]


def devig(odds: list[float]) -> list[float]:
    """Orantısal marj arındırma (tüm sonuçlar ayrık ve kapsayıcı olmalı)."""
    inv = np.array([1.0 / o for o in odds])
    return list(inv / inv.sum())


def margin(odds: list[float]) -> float:
    return float(sum(1.0 / o for o in odds) - 1.0)


def blend(model: list[float], market: list[float], w: float) -> list[float]:
    """Geometrik havuzlama: p_k ∝ model_k^w · piyasa_k^(1-w), tüm pazar üzerinde normalize."""
    m = np.clip(np.array(model), 1e-9, 1.0)
    q = np.clip(np.array(market), 1e-9, 1.0)
    p = m**w * q ** (1 - w)
    return list(p / p.sum())


def is_exhaustive(probs: list[float], tol: float = 0.02) -> bool:
    return abs(sum(probs) - 1.0) <= tol
