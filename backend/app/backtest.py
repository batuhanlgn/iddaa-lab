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
from .config import DEFAULT_SIGMA, DEFAULT_TAU, DEFAULT_XI, REFERENCE_LEAGUE
from .model import markets as mk
from .model.count_model import fit_count_model
from .model.goals import build_count_data, fit_goal_model, load_matches, score_matrix
from .model.pipeline import PARAMS_PATH, _fit_aux, _stat_values

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


def walk_forward(con: sqlite3.Connection, start: datetime, end: datetime, xi: float, sigma: float, tau: float,
                 with_baselines: bool = True, with_corners: bool = False) -> list[Pred]:
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
        gm, train, _ = fit_goal_model(con, wk, xi, sigma, tau)
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
            sm = score_matrix(r[0], r[1], gm.rho)
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
    tune_start = now - timedelta(days=420)
    eval_start = now - timedelta(days=150)
    grid = [(xi, s) for xi in (0.0015, 0.0025, 0.004, 0.006) for s in (0.25, 0.35, 0.5)]
    tuning = []
    for i, (xi, s) in enumerate(grid):
        ps = walk_forward(con, tune_start, eval_start, xi, s, DEFAULT_TAU, with_baselines=False)
        ms = [p for p in ps if p.fam == "ms"]
        ll = logloss([p.probs for p in ms], [p.outcome for p in ms])
        tuning.append({"xi": xi, "sigma": s, "ms_logloss": ll, "n": len(ms)})
        progress(f"Ayarlama {i + 1}/{len(grid)}: xi={xi} sigma={s} MS log-loss={ll:.4f} (n={len(ms)})")
    best = min(tuning, key=lambda t: t["ms_logloss"])
    params = {"xi": best["xi"], "sigma": best["sigma"], "tau": DEFAULT_TAU}
    PARAMS_PATH.write_text(json.dumps(params, indent=2), encoding="utf-8")
    progress(f"Seçilen parametreler: {params}. Değerlendirme dilimi çalışıyor…")
    ev = walk_forward(con, eval_start, now, params["xi"], params["sigma"], params["tau"], with_baselines=True, with_corners=True)
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
    # Kupon pazar aileleri: 'au' ve 'kg' ailesi aynı skor matrisinden; 'iy' ailesi iy+iyms ikisini de geçmeli
    family = {
        "ms": validation.get("ms", {}),
        "au": validation.get("au", {}),
        "kg": validation.get("kg", {}),
        "iy": {**validation.get("iy", {}), "validated": bool(validation.get("iy", {}).get("validated")) and bool(validation.get("iyms", {}).get("validated"))},
        "korner": validation.get("korner", {}),
    }
    result = {
        "created_at": _iso(datetime.now(timezone.utc)),
        "tune_window": [_iso(tune_start), _iso(eval_start)],
        "eval_window": [_iso(eval_start), _iso(now)],
        "params": params,
        "tuning": tuning,
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


def evaluate_players(con: sqlite3.Connection, progress: Callable[[str], None], n_matches: int = 300, n_sims: int = 2000) -> dict:
    """Oyuncu P(SoT>=1), P(şut>=1), P(gol) kalibrasyonu: değerlendirme dilimindeki maçlardan örneklem, sızıntısız."""
    from .model.pipeline import fit_all
    from .model.simulate import TeamSimInput, simulate_match

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=120)
    rows = con.execute(
        """SELECT * FROM matches WHERE completed=1 AND summary_status='ok' AND date_utc >= ? AND date_utc < ?
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
    recs: dict[str, list[tuple[float, int]]] = defaultdict(list)
    team_sot: list[tuple[float, int]] = []
    for i, (wk, ms) in enumerate(sorted(by_week.items())):
        fm = fit_all(con, _dt(wk))
        if fm.shots is None:
            continue
        for m in ms:
            r = fm.goals.rates(m["league"], m["home_id"], m["away_id"], bool(m["neutral"]))
            smu = fm.shots.means(m["league"], m["home_id"], m["away_id"], bool(m["neutral"]))
            if r is None or smu is None:
                continue
            sm = score_matrix(r[0], r[1], fm.goals.rho)
            sim = simulate_match(
                sm,
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
                    team_sot.append((t["shots_on_target"]["at_least"]["4"], int(ts["shots_on_target"] >= 4)))
                for p in t["players"]:
                    a = actual.get(p["player_id"])
                    sot = (a["shots_on_target"] or 0) if a else 0
                    sh = (a["shots"] or 0) if a else 0
                    gl = (a["goals"] or 0) if a else 0
                    recs["p_sot_1"].append((p["p_sot_1"], int(sot >= 1)))
                    recs["p_shots_1"].append((p["p_shots_1"], int(sh >= 1)))
                    recs["p_goal"].append((p["p_goal"], int(gl >= 1)))
                    recs["p_play"].append((p["p_play"], int(bool(a) and (a["minutes"] or 0) > 0)))
        progress(f"Oyuncu doğrulaması: hafta {i + 1}/{len(by_week)}")
    out = {}
    for k, v in list(recs.items()) + [("team_sot_4plus", team_sot)]:
        if not v:
            continue
        ps = [[1 - p, p] for p, _ in v]
        ys = [y for _, y in v]
        base_rate = float(np.mean(ys))
        out[k] = {
            "n": len(v), "model_logloss": logloss(ps, ys), "base_logloss": logloss([[1 - base_rate, base_rate]] * len(v), ys),
            "mean_pred": float(np.mean([p for p, _ in v])), "mean_obs": base_rate,
            "calibration": calibration(ps, ys),
        }
    with db.tx(con):
        db.meta_set(con, "player_backtest", {"created_at": _iso(now), "window_start": _iso(start), "metrics": out})
    return out
