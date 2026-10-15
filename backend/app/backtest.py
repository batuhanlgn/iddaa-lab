"""Walk-forward doğrulama.

- Her hafta başında yalnızca o ana kadarki veriyle fit, sonraki 7 günün maçlarını tahmin.
- Hiperparametreler (xi, sigma) AYARLAMA diliminde seçilir; raporlanan skorlar ayrı DEĞERLENDİRME dilimindendir.
- Bazlar: lig taban oranları (as_of öncesi) ve basit Poisson (hiyerarşi/zaman ağırlığı zayıf, DC yok).
- Pazar ailesi doğrulaması: model, değerlendirme diliminde taban orandan daha iyi log-loss ve kabul edilebilir
  kalibrasyon gösterirse o aile kupona açılır.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np

from . import db
from .config import DEFAULT_SIGMA, DEFAULT_TAU, DEFAULT_XI, MAX_GOALS, REFERENCE_LEAGUE
from .model import markets as mk
from .model.count_model import fit_count_model
from .model.goals import build_count_data, fit_goal_model, load_matches, score_matrix
from .model.pipeline import _fit_aux, _stat_values

log = logging.getLogger(__name__)
EPS = 1e-12


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass
class Pred:
    match_id: str
    league: str
    fam: str            # ms | au | kg | iy | iyms | korner
    probs: list[float]
    outcome: int
    base: list[float]   # lig taban oranı tahmini
    simple: list[float] | None


def _league_base_rates(train: list, as_of: datetime) -> dict[str, dict[str, list[float]]]:
    acc: dict[str, dict[str, np.ndarray]] = defaultdict(lambda: {
        "ms": np.zeros(3), "au": np.zeros(2), "kg": np.zeros(2), "iy": np.zeros(3), "iyms": np.zeros(9), "n_ht": np.zeros(1)})
    since = as_of - timedelta(days=400)
    for m in train:
        if m.date < since:
            continue
        a = acc[m.league]
        a["ms"][0 if m.hg > m.ag else 1 if m.hg == m.ag else 2] += 1
        a["au"][0 if m.hg + m.ag < 2.5 else 1] += 1
        a["kg"][0 if (m.hg > 0 and m.ag > 0) else 1] += 1
        if m.hht is not None:
            ht = 0 if m.hht > m.aht else 1 if m.hht == m.aht else 2
            ft = 0 if m.hg > m.ag else 1 if m.hg == m.ag else 2
            a["iy"][ht] += 1
            a["iyms"][ht * 3 + ft] += 1
    out = {}
    for lg, a in acc.items():
        out[lg] = {k: list((v + 1) / (v.sum() + len(v))) for k, v in a.items() if k != "n_ht"}
    return out


def _outcomes(m) -> dict[str, int]:
    o = {"ms": 0 if m.hg > m.ag else 1 if m.hg == m.ag else 2, "au": 0 if m.hg + m.ag < 2.5 else 1,
         "kg": 0 if (m.hg > 0 and m.ag > 0) else 1}
    if m.hht is not None and m.aht is not None:
        ht = 0 if m.hht > m.aht else 1 if m.hht == m.aht else 2
        o["iy"] = ht
        o["iyms"] = ht * 3 + o["ms"]
    return o


def _probs_from_joint(j: mk.Joint) -> dict[str, list[float]]:
    X, Y, I, J, P = j.X, j.Y, j.I, j.J, j.P
    ms = [P[X > Y].sum(), P[X == Y].sum(), P[X < Y].sum()]
    au = [P[X + Y < 2.5].sum(), P[X + Y > 2.5].sum()]
    kg = [P[(X > 0) & (Y > 0)].sum(), P[~((X > 0) & (Y > 0))].sum()]
    hts = [I > J, I == J, I < J]
    fts = [X > Y, X == Y, X < Y]
    iy = [P[h].sum() for h in hts]
    iyms = [P[h & f].sum() for h in hts for f in fts]
    return {"ms": ms, "au": au, "kg": kg, "iy": iy, "iyms": iyms}


def _ms_from_matrix(sm: np.ndarray) -> list[float]:
    return [float(np.tril(sm, -1).sum()), float(np.trace(sm)), float(np.triu(sm, 1).sum())]


@dataclass
class RawPred:
    lh: float
    la: float
    rho: float
    hg: int
    ag: int


def walk_forward(con: sqlite3.Connection, start: datetime, end: datetime, xi: float, sigma: float, tau: float,
                 with_baselines: bool = True, with_corners: bool = False, alpha: float = 1.0, cal_t: float = 1.0,
                 cal_g: float = 1.0, raw: list[RawPred] | None = None) -> list[Pred]:
    preds: list[Pred] = []
    all_matches = load_matches(con, _iso(end))
    corner_vals = _stat_values(con, _iso(end), "corners") if with_corners else {}
    wk = start
    while wk < end:
        nxt = min(wk + timedelta(days=7), end)
        test = [m for m in all_matches if wk <= m.date < nxt]
        if not test:
            wk = nxt
            continue
        gm, train, _ = fit_goal_model(con, wk, xi, sigma, tau, alpha, cal_t, cal_g)
        base = _league_base_rates(train, wk)
        simple = None
        if with_baselines:
            sdata = build_count_data(train, wk, 0.0015)
            simple = fit_count_model(sdata, REFERENCE_LEAGUE, sigma=3.0, tau=3.0, home_prior=(0.2, 1.0), delta_prior_sd=1.0)
        corners = _fit_aux(train, corner_vals, wk, xi) if with_corners else None
        train_ids = {m.id for m in train if m.date >= wk - timedelta(days=400)}
        c_tr = [sum(v) > 9.5 for k, v in corner_vals.items() if k in train_ids]
        c_base = float(np.mean(c_tr)) if c_tr else 0.5
        for m in test:
            r = gm.rates(m.league, m.home, m.away, m.neutral)
            if r is None or m.league not in base:
                continue
            if raw is not None:
                raw.append(RawPred(r[0], r[1], gm.rho, m.hg, m.ag))
            sm = gm.matrix(r[0], r[1])
            j = mk.build_joint(sm, gm.p1.get(m.league, gm.p1_global))
            probs = _probs_from_joint(j)
            sp = None
            if simple is not None:
                lr = simple.log_rates(m.league, m.home, m.away, m.neutral)
                if lr is not None:
                    sp = _ms_from_matrix(score_matrix(float(np.exp(lr[0])), float(np.exp(lr[1])), 0.0))
            for fam, y in _outcomes(m).items():
                preds.append(Pred(m.id, m.league, fam, [float(x) for x in probs[fam]], y, base[m.league][fam],
                                  sp if fam == "ms" else None))
            if corners is not None and m.id in corner_vals:
                cm = corners.means(m.league, m.home, m.away, m.neutral)
                if cm:
                    alt, ust = mk.corner_over_prob(cm[0], cm[1], corners.k, 9.5)
                    tot = sum(corner_vals[m.id])
                    preds.append(Pred(m.id, m.league, "korner", [alt, ust], 0 if tot < 9.5 else 1, [1 - c_base, c_base], None))
        wk = nxt
    return preds


def _score_loglik(raw: list[RawPred], t: float, g: float) -> float:
    """Kalibre skor matrisinin gerçekleşen tam skorlar üzerindeki ortalama log-olabilirliği (vektörel)."""
    from scipy.stats import poisson

    n = MAX_GOALS + 1
    k = np.arange(n)
    lh = np.array([r.lh for r in raw]) * g
    la = np.array([r.la for r in raw]) * g
    rho = np.array([r.rho for r in raw])
    ph = poisson.pmf(k[None, :], lh[:, None])
    pa = poisson.pmf(k[None, :], la[:, None])
    ph[:, -1] += np.clip(1 - ph.sum(axis=1), 0, None)
    pa[:, -1] += np.clip(1 - pa.sum(axis=1), 0, None)
    M = ph[:, :, None] * pa[:, None, :]
    lo = np.maximum(-1 / lh, -1 / la)
    hi = np.minimum(1.0, 1 / (lh * la))
    r_ = np.clip(rho, lo + 1e-9, hi - 1e-9)
    M[:, 0, 0] *= 1 - lh * la * r_
    M[:, 0, 1] *= 1 + lh * r_
    M[:, 1, 0] *= 1 + la * r_
    M[:, 1, 1] *= 1 - r_
    M = np.clip(M / M.sum(axis=(1, 2), keepdims=True), 1e-15, 1.0) ** t
    M = M / M.sum(axis=(1, 2), keepdims=True)
    hg = np.minimum([r.hg for r in raw], n - 1)
    ag = np.minimum([r.ag for r in raw], n - 1)
    return float(np.mean(np.log(M[np.arange(len(raw)), hg, ag])))


def fit_score_calibration(raw: list[RawPred]) -> tuple[float, float, float]:
    from scipy.optimize import minimize

    res = minimize(lambda x: -_score_loglik(raw, float(x[0]), float(x[1])), np.array([1.0, 1.0]), method="L-BFGS-B",
                   bounds=[(0.7, 1.3), (0.85, 1.15)])
    return float(res.x[0]), float(res.x[1]), float(-res.fun)


def _goal_families_ll(ps: list[Pred]) -> float:
    """MS + A/Ü + KG toplam log-loss (şut tabanlı güç ve kalibrasyon seçiminde ölçüt)."""
    tot = 0.0
    for fam in ("ms", "au", "kg"):
        xs = [p for p in ps if p.fam == fam]
        tot += logloss([p.probs for p in xs], [p.outcome for p in xs])
    return tot


def logloss(ps: list[list[float]], ys: list[int]) -> float:
    return float(-np.mean([np.log(max(p[y], EPS)) for p, y in zip(ps, ys)]))


def brier(ps: list[list[float]], ys: list[int]) -> float:
    out = []
    for p, y in zip(ps, ys):
        v = np.zeros(len(p))
        v[y] = 1
        out.append(np.sum((np.array(p) - v) ** 2))
    return float(np.mean(out))


def calibration(ps: list[list[float]], ys: list[int], bins: int = 10) -> list[dict]:
    """Tüm sonuçlar üzerinden (one-vs-rest) güvenilirlik eğrisi."""
    pr, ob = [], []
    for p, y in zip(ps, ys):
        for k, pk in enumerate(p):
            pr.append(pk)
            ob.append(1.0 if k == y else 0.0)
    pr_a, ob_a = np.array(pr), np.array(ob)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        msk = (pr_a >= edges[i]) & (pr_a < edges[i + 1] if i < bins - 1 else pr_a <= edges[i + 1])
        n = int(msk.sum())
        if n:
            out.append({"bin_lo": float(edges[i]), "bin_hi": float(edges[i + 1]), "pred": float(pr_a[msk].mean()),
                        "obs": float(ob_a[msk].mean()), "n": n})
    return out


def summarize(preds: list[Pred]) -> dict:
    fams: dict[str, list[Pred]] = defaultdict(list)
    for p in preds:
        fams[p.fam].append(p)
    out = {}
    for fam, ps in fams.items():
        ys = [p.outcome for p in ps]
        model = [p.probs for p in ps]
        res = {
            "n": len(ps),
            "model_logloss": logloss(model, ys),
            "model_brier": brier(model, ys),
            "base_logloss": logloss([p.base for p in ps], ys),
            "base_brier": brier([p.base for p in ps], ys),
            "calibration": calibration(model, ys),
        }
        sp = [(p.simple, p.outcome) for p in ps if p.simple is not None]
        if sp:
            res["simple_logloss"] = logloss([s for s, _ in sp], [y for _, y in sp])
        out[fam] = res
    return out


def tune_and_evaluate(con: sqlite3.Connection, progress: Callable[[str], None]) -> dict:
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    # Üç dilim: AYARLAMA (parametre + kalibrasyon öğrenme) | DOĞRULAMA (kalibrasyon kullanılsın mı kararı) |
    # DEĞERLENDİRME (hiçbir seçimde kullanılmaz; yalnızca rapor ve pazar ailesi doğrulaması)
    tune_start = now - timedelta(days=420)
    val_start = now - timedelta(days=210)
    eval_start = now - timedelta(days=150)

    # 1) Zaman sönümü ve büzülme (yalnız goller)
    grid = [(xi, s_) for xi in (0.0015, 0.0025, 0.004, 0.006) for s_ in (0.25, 0.35, 0.5)]
    tuning = []
    for i, (xi, s_) in enumerate(grid):
        ps = walk_forward(con, tune_start, val_start, xi, s_, DEFAULT_TAU, with_baselines=False)
        ms = [p for p in ps if p.fam == "ms"]
        ll = logloss([p.probs for p in ms], [p.outcome for p in ms])
        tuning.append({"xi": xi, "sigma": s_, "ms_logloss": ll, "n": len(ms)})
        progress(f"Ayarlama {i + 1}/{len(grid)}: xi={xi} sigma={s_} MS log-loss={ll:.4f} (n={len(ms)})")
    best = min(tuning, key=lambda t: t["ms_logloss"])
    xi, sigma = best["xi"], best["sigma"]

    # 2) Şut tabanlı güç: gol / isabetli şut karışımı (α=1 yalnız gol)
    alpha_tuning = []
    for alpha in (1.0, 0.7, 0.5, 0.3, 0.15, 0.0):
        ps = walk_forward(con, tune_start, val_start, xi, sigma, DEFAULT_TAU, with_baselines=False, alpha=alpha)
        ll = _goal_families_ll(ps)
        alpha_tuning.append({"alpha": alpha, "goal_families_logloss": ll})
        progress(f"Şut ağırlığı α={alpha}: MS+A/Ü+KG log-loss={ll:.4f}")
    alpha = min(alpha_tuning, key=lambda t: t["goal_families_logloss"])["alpha"]

    # 3) Skor kalibrasyonu: ayarlama diliminin ham tahminlerinden öğren
    raw: list[RawPred] = []
    walk_forward(con, tune_start, val_start, xi, sigma, DEFAULT_TAU, with_baselines=False, alpha=alpha, raw=raw)
    cal_t, cal_g, cal_ll = fit_score_calibration(raw)
    base_ll = _score_loglik(raw, 1.0, 1.0)
    progress(f"Skor kalibrasyonu (ayarlama): t={cal_t:.3f} g={cal_g:.3f} tam skor log-olabilirlik {base_ll:.4f} -> {cal_ll:.4f}")

    # 4) Kalibrasyon kararı DOĞRULAMA diliminde (değerlendirme dilimi bu karara karışmaz)
    va_raw = walk_forward(con, val_start, eval_start, xi, sigma, DEFAULT_TAU, with_baselines=False, alpha=alpha)
    va_cal = walk_forward(con, val_start, eval_start, xi, sigma, DEFAULT_TAU, with_baselines=False, alpha=alpha,
                          cal_t=cal_t, cal_g=cal_g)
    ll_raw, ll_cal = _goal_families_ll(va_raw), _goal_families_ll(va_cal)
    use_cal = ll_cal < ll_raw
    score_cal = {"t": cal_t, "g": cal_g, "used": use_cal, "eval_ll_raw": ll_raw, "eval_ll_cal": ll_cal,
                 "tune_score_ll_raw": base_ll, "tune_score_ll_cal": cal_ll, "decided_on": "doğrulama dilimi"}
    progress(f"Doğrulama MS+A/Ü+KG log-loss: kalibrasyonsuz {ll_raw:.4f}, kalibre {ll_cal:.4f} -> {'kullanılıyor' if use_cal else 'kullanılmıyor'}")
    # 5) Değerlendirme (dokunulmamış dilim): yalnızca seçilen yapılandırmayla, rapor + aile doğrulaması
    ev = walk_forward(con, eval_start, now, xi, sigma, DEFAULT_TAU, with_baselines=True, with_corners=True, alpha=alpha,
                      cal_t=cal_t if use_cal else 1.0, cal_g=cal_g if use_cal else 1.0)
    params = {"xi": xi, "sigma": sigma, "tau": DEFAULT_TAU, "alpha": alpha,
              "cal_t": cal_t if use_cal else 1.0, "cal_g": cal_g if use_cal else 1.0}
    with db.tx(con):
        db.meta_set(con, "model_params", params)
    progress(f"Seçilen parametreler: {params}")

    summary = summarize(ev)
    by_league: dict[str, dict] = {}
    lg_groups: dict[str, list[Pred]] = defaultdict(list)
    for p in ev:
        if p.fam == "ms":
            lg_groups[p.league].append(p)
    for lg, ps in lg_groups.items():
        ys = [p.outcome for p in ps]
        by_league[lg] = {"n": len(ps), "model_logloss": logloss([p.probs for p in ps], ys),
                         "base_logloss": logloss([p.base for p in ps], ys)}
    # NB k yalnızca DEĞERLENDİRME ÖNCESİ dilimden: oyuncu doğrulaması ve tahminler gelecekteki veriyi görmez
    disp = out_of_sample_dispersion(con, tune_start, eval_start, params["xi"])
    with db.tx(con):
        db.meta_set(con, "aux_dispersion", disp)
    progress(f"Örneklem dışı NB dağılım parametreleri: {disp}")
    validation = {}
    for fam, r in summary.items():
        cal = r["calibration"]
        tot = sum(c["n"] for c in cal)
        ece = sum(c["n"] * abs(c["pred"] - c["obs"]) for c in cal) / tot if tot else 1.0
        ok = r["n"] >= 300 and r["model_logloss"] < r["base_logloss"] - 0.002 and ece < 0.03
        validation[fam] = {"validated": ok, "ece": ece, "n": r["n"],
                           "gain": r["base_logloss"] - r["model_logloss"]}
        r["ece"] = ece
    family = {
        "ms": validation.get("ms", {}),
        "au": validation.get("au", {}),
        "kg": validation.get("kg", {}),
        "iy": {**validation.get("iy", {}), "validated": bool(validation.get("iy", {}).get("validated")) and bool(validation.get("iyms", {}).get("validated"))},
        "korner": validation.get("korner", {}),
    }
    result = {
        "created_at": _iso(datetime.now(timezone.utc)),
        "tune_window": [_iso(tune_start), _iso(val_start)],
        "validation_window": [_iso(val_start), _iso(eval_start)],
        "eval_window": [_iso(eval_start), _iso(now)],
        "params": params,
        "tuning": tuning,
        "alpha_tuning": alpha_tuning,
        "score_calibration": score_cal,
        "summary": summary,
        "by_league": by_league,
        "family_validation": family,
        "dispersion": disp,
    }
    with db.tx(con):
        db.meta_set(con, "backtest", result)
        db.meta_set(con, "family_validation", family)
    return result


def out_of_sample_dispersion(con: sqlite3.Connection, start: datetime, end: datetime, xi: float) -> dict[str, float]:
    """Şut ve korner için NB k: haftalık walk-forward tahminlerinin artıklarından (örneklem içi aşırı uyum yok)."""
    from .model.count_model import nb_dispersion

    all_matches = load_matches(con, _iso(end))
    out: dict[str, float] = {}
    for stat in ("shots", "corners"):
        vals = _stat_values(con, _iso(end), stat)
        ys: list[float] = []
        mus: list[float] = []
        wk = start
        while wk < end:
            nxt = min(wk + timedelta(days=7), end)
            test = [m for m in all_matches if wk <= m.date < nxt and m.id in vals]
            if test:
                train = [m for m in all_matches if m.date < wk - timedelta(hours=3)]
                aux = _fit_aux(train, vals, wk, xi)
                if aux is not None:
                    for m in test:
                        mm = aux.means(m.league, m.home, m.away, m.neutral)
                        if mm:
                            ys.extend(vals[m.id])
                            mus.extend(mm)
            wk = nxt
        if len(ys) >= 400:
            out[stat] = nb_dispersion(np.array(ys), np.array(mus), np.ones(len(ys)))
            out[f"{stat}_n"] = float(len(ys))
    return out


def _platt_fit(v: list[tuple[float, int]]) -> tuple[float, float]:
    from scipy.optimize import minimize

    p = np.clip(np.array([x for x, _ in v]), 1e-6, 1 - 1e-6)
    y = np.array([t for _, t in v], dtype=float)
    z = np.log(p / (1 - p))

    def nll(w: np.ndarray) -> float:
        q = 1 / (1 + np.exp(-(w[0] + w[1] * z)))
        q = np.clip(q, 1e-9, 1 - 1e-9)
        return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))

    res = minimize(nll, np.array([0.0, 1.0]), method="L-BFGS-B", bounds=[(-3, 3), (0.3, 3.0)])
    return float(res.x[0]), float(res.x[1])


def _bin_ll(v: list[tuple[float, int]], a: float = 0.0, b: float = 1.0) -> float:
    p = np.clip(np.array([x for x, _ in v]), 1e-6, 1 - 1e-6)
    q = 1 / (1 + np.exp(-(a + b * np.log(p / (1 - p)))))
    q = np.clip(q, 1e-9, 1 - 1e-9)
    y = np.array([t for _, t in v], dtype=float)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def evaluate_players(con: sqlite3.Connection, progress: Callable[[str], None], n_matches: int = 400, n_sims: int = 2000) -> dict:
    """Oyuncu ve takım şut tahminlerinin doğrulaması (sızıntısız) + çapraz doğrulamalı Platt kalibrasyonu."""
    from .model.pipeline import fit_all
    from .model.simulate import TeamSimInput, simulate_match

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=120)
    rows = con.execute(
        """SELECT * FROM matches WHERE completed=1 AND summary_status='ok' AND extra_time=0 AND date_utc >= ? AND date_utc < ?
           ORDER BY date_utc""",
        (_iso(start), _iso(now)),
    ).fetchall()
    rng = np.random.default_rng(7)
    if len(rows) > n_matches:
        idx = np.sort(rng.choice(len(rows), size=n_matches, replace=False))
        rows = [rows[i] for i in idx]
    by_week: dict[str, list] = defaultdict(list)
    for r in rows:
        d = _dt(r["date_utc"])
        wk = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        by_week[_iso(wk)].append(r)
    # kayıt: (tahmin, gerçekleşme, kat) — kat = maç sırası paritesi (2 katlı çapraz doğrulama)
    recs: dict[str, list[tuple[float, int, int]]] = defaultdict(list)
    mi = 0
    for i, (wk, ms) in enumerate(sorted(by_week.items())):
        fm = fit_all(con, _dt(wk))
        if fm.shots is None:
            continue
        for m in ms:
            r = fm.goals.rates(m["league"], m["home_id"], m["away_id"], bool(m["neutral"]))
            smu = fm.shots.means(m["league"], m["home_id"], m["away_id"], bool(m["neutral"]))
            if r is None or smu is None:
                continue
            fold = mi % 2
            mi += 1
            sim = simulate_match(
                fm.goals.matrix(r[0], r[1]),
                TeamSimInput("home", m["home_id"], smu[0], fm.shots.k, fm.omega, fm.players.team_context(m["home_id"])),
                TeamSimInput("away", m["away_id"], smu[1], fm.shots.k, fm.omega, fm.players.team_context(m["away_id"])),
                n_sims, 0, 11,
            )
            actual = {r2["player_id"]: r2 for r2 in con.execute(
                "SELECT player_id, minutes, shots, shots_on_target, goals FROM player_match WHERE match_id=?", (m["id"],))}
            tstats = {r2["team_id"]: r2 for r2 in con.execute(
                "SELECT team_id, shots_on_target FROM team_match_stats WHERE match_id=?", (m["id"],))}
            for side in ("home", "away"):
                t = sim["teams"][side]
                ts = tstats.get(t["team_id"])
                if ts and ts["shots_on_target"] is not None:
                    for k in ("3", "4", "5"):
                        recs["team_sot"].append((t["shots_on_target"]["at_least"][k], int(ts["shots_on_target"] >= int(k)), fold))
                for p in t["players"]:
                    a_ = actual.get(p["player_id"])
                    sot = (a_["shots_on_target"] or 0) if a_ else 0
                    sh = (a_["shots"] or 0) if a_ else 0
                    gl = (a_["goals"] or 0) if a_ else 0
                    recs["p_sot_1"].append((p["p_sot_1"], int(sot >= 1), fold))
                    recs["p_sot_2"].append((p["p_sot_2"], int(sot >= 2), fold))
                    recs["p_shots_1"].append((p["p_shots_1"], int(sh >= 1), fold))
                    recs["p_shots_2"].append((p["p_shots_2"], int(sh >= 2), fold))
                    recs["p_shots_3"].append((p["p_shots_3"], int(sh >= 3), fold))
                    recs["p_goal"].append((p["p_goal"], int(gl >= 1), fold))
                    recs["p_play"].append((p["p_play"], int(bool(a_) and (a_["minutes"] or 0) > 0), fold))
        progress(f"Oyuncu doğrulaması: hafta {i + 1}/{len(by_week)}")
    out = {}
    pcal: dict[str, dict] = {}
    for k, v3 in recs.items():
        if not v3:
            continue
        v = [(p, y) for p, y, _ in v3]
        ps = [[1 - p, p] for p, _ in v]
        ys = [y for _, y in v]
        base_rate = float(np.mean(ys))
        # 2 katlı çapraz doğrulama: bir katta öğren, diğerinde ölç
        f0 = [(p, y) for p, y, f in v3 if f == 0]
        f1 = [(p, y) for p, y, f in v3 if f == 1]
        cv_raw = cv_cal = None
        if len(f0) > 200 and len(f1) > 200:
            a0, b0 = _platt_fit(f0)
            a1, b1 = _platt_fit(f1)
            cv_raw = (_bin_ll(f1) * len(f1) + _bin_ll(f0) * len(f0)) / len(v)
            cv_cal = (_bin_ll(f1, a0, b0) * len(f1) + _bin_ll(f0, a1, b1) * len(f0)) / len(v)
        a_all, b_all = _platt_fit(v) if len(v) > 200 else (0.0, 1.0)
        use = cv_raw is not None and cv_cal is not None and cv_cal < cv_raw - 0.0005
        pcal[k] = {"a": a_all, "b": b_all, "use": use, "cv_ll_raw": cv_raw, "cv_ll_cal": cv_cal, "n": len(v)}
        q = [[1 - pp, pp] for pp in (1 / (1 + np.exp(-(a_all + b_all * np.log(np.clip(p, 1e-6, 1 - 1e-6) / (1 - np.clip(p, 1e-6, 1 - 1e-6)))))) for p, _ in v)] if use else ps
        out[k] = {
            "n": len(v), "model_logloss": logloss(ps, ys), "base_logloss": logloss([[1 - base_rate, base_rate]] * len(v), ys),
            "mean_pred": float(np.mean([p for p, _ in v])), "mean_obs": base_rate,
            "calibration": calibration(ps, ys),
            "calibrated": use, "cv_ll_raw": cv_raw, "cv_ll_cal": cv_cal,
            "calibration_after": calibration(q, ys) if use else None,
        }
    with db.tx(con):
        db.meta_set(con, "player_backtest", {"created_at": _iso(now), "window_start": _iso(start), "metrics": out})
        db.meta_set(con, "player_calibration", pcal)
    return out


def tune_lineup_beta(con: sqlite3.Connection, progress: Callable[[str], None]) -> dict:
    """Resmi kadro ayarının gücü β: geçmiş maçların GERÇEK ilk 11'leri ile (maç öncesi açıklanmış gibi).

    β doğrulama diliminde seçilir; değerlendirme dilimi yalnızca rapor içindir. β=0 ayarın kapalı olmasıdır.
    """
    from .model.goals import score_matrix_cal
    from .model.pipeline import load_params
    from .model.players import PlayerStore, attack_index

    params = load_params(con)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    val_start, eval_start = now - timedelta(days=210), now - timedelta(days=150)
    all_matches = {m.id: m for m in load_matches(con, _iso(now))}
    recs: dict[str, list[tuple]] = {"val": [], "eval": []}
    wk = val_start
    while wk < now:
        nxt = min(wk + timedelta(days=7), now)
        rows = con.execute(
            """SELECT id FROM matches WHERE completed=1 AND summary_status='ok' AND extra_time=0
               AND date_utc >= ? AND date_utc < ?""",
            (_iso(wk), _iso(nxt)),
        ).fetchall()
        ids = [r["id"] for r in rows if r["id"] in all_matches]
        if ids:
            gm, _, _ = fit_goal_model(con, wk, params["xi"], params["sigma"], params["tau"], params.get("alpha", 1.0),
                                      params.get("cal_t", 1.0), params.get("cal_g", 1.0))
            ps = PlayerStore(con, wk)
            for mid in ids:
                m = all_matches[mid]
                r = gm.rates(m.league, m.home, m.away, m.neutral)
                if r is None:
                    continue
                ratios = []
                for team in (m.home, m.away):
                    lineup = {x["player_id"]: bool(x["starter"]) for x in con.execute(
                        "SELECT player_id, starter FROM player_match WHERE match_id=? AND team_id=?", (mid, team))}
                    if sum(lineup.values()) < 11 or len(ps.by_team_match.get(team, {})) < 3:
                        ratios.append(None)
                        continue
                    usual = attack_index(ps.team_context(team))
                    conf = attack_index(ps.team_context(team, lineup))
                    ratios.append(conf / usual if usual > 0 and conf > 0 else None)
                if ratios[0] is None and ratios[1] is None:
                    continue
                recs["val" if wk < eval_start else "eval"].append(
                    (r[0], r[1], gm.rho, gm.cal_t, gm.cal_g, ratios[0] or 1.0, ratios[1] or 1.0, m.hg, m.ag))
        progress(f"Kadro ayarı doğrulaması: {_iso(wk)[:10]} haftası")
        wk = nxt

    def ll(rs: list[tuple], beta: float) -> float:
        tot = 0.0
        for lh, la, rho, t, g, rh, ra, hg, ag in rs:
            fh = float(np.clip(rh**beta, 0.85, 1.15))
            fa = float(np.clip(ra**beta, 0.85, 1.15))
            sm = score_matrix_cal(lh * fh, la * fa, rho, t, g)
            n = sm.shape[0] - 1
            res = 0 if hg > ag else 1 if hg == ag else 2
            ms = [float(np.tril(sm, -1).sum()), float(np.trace(sm)), float(np.triu(sm, 1).sum())]
            k = np.arange(n + 1)
            tot_goals = k[:, None] + k[None, :]
            p_over = float(sm[tot_goals > 2.5].sum())
            p_kg = float(sm[1:, 1:].sum())
            tot -= np.log(max(ms[res], 1e-12))
            tot -= np.log(max(p_over if hg + ag > 2.5 else 1 - p_over, 1e-12))
            tot -= np.log(max(p_kg if (hg > 0 and ag > 0) else 1 - p_kg, 1e-12))
        return tot / max(len(rs), 1)

    grid = [0.0, 0.25, 0.5, 0.75, 1.0]
    val_curve = {b: ll(recs["val"], b) for b in grid}
    beta = min(val_curve, key=lambda b: val_curve[b])
    res = {
        "beta": beta, "n_val": len(recs["val"]), "n_eval": len(recs["eval"]),
        "val_curve": {str(b): v for b, v in val_curve.items()},
        "eval_ll_off": ll(recs["eval"], 0.0), "eval_ll_chosen": ll(recs["eval"], beta),
        "created_at": _iso(datetime.now(timezone.utc)),
    }
    if len(recs["val"]) < 200:
        res["beta"] = 0.0
        res["note"] = "yetersiz doğrulama örneği"
    with db.tx(con):
        db.meta_set(con, "lineup_beta", res)
    progress(f"Kadro ayarı: β={res['beta']} (doğrulama n={res['n_val']}), değerlendirme log-loss kapalı "
             f"{res['eval_ll_off']:.4f} -> seçilen {res['eval_ll_chosen']:.4f}")
    return res
