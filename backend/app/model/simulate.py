"""Maç simülasyonu (Codex'le ortak karar, docs/03):

1. Nihai skor (C_H, C_A) ~ Dixon-Coles skor matrisi  -> skor pazarları bozulmaz.
2. Her takım için kadro/dakika senaryosu: geçerli ilk 11 (1 kaleci + 10), çıkış dakikaları ve giren yedekler.
3. Yardımcı şut modeli, skora koşullu ve HER kadro senaryosunun kendi u,v'siyle:
       P(S,T,F,O | F+O=c) ∝ NB(S;μ,k) · Bin(T;S,u) · Bin(F;T,v) · Pois(O;ω)
   u = Σ w_i a_i ,  v = Σ w_i a_i b_i / u ,  w_i = M_i r_i / Σ M_j r_j
   Tam örnekleme (Gamma-Poisson eşleniği): S|Λ ~ Pois(Λ), Λ ~ Gamma(k, k/μ). İnceltmeyle F|Λ ~ Pois(Λuv) ve
   diğer şut kategorileri Λ verildiğinde bağımsız Poisson'dur. Böylece:
       F | c          ∝ NB(F; μuv, k) · Pois(c−F; ω)
       Λ | F          ~ Gamma(k+F, k/μ + uv)
       (T−F) | Λ      ~ Pois(Λ·u·(1−v)),   (S−T) | Λ ~ Pois(Λ·(1−u))
4. Oyunculara dağıtım (multinomial): goller ∝ w a b, golsüz isabetli ∝ w a (1-b), isabetsiz ∝ w (1-a).
   Böylece gol ≤ SoT ≤ şut hem takımda hem oyuncuda korunur; kendi kalesine gol hücum oyuncusuna yazılmaz.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import nbinom, poisson

from ..config import MAX_GOALS
from .players import TeamPlayerContext

_POS_FULL90 = {"G": 0.97, "D": 0.82, "M": 0.55, "F": 0.45}


@dataclass
class TeamSimInput:
    side: str                   # "home" | "away"
    team_id: str
    shots_mu: float
    shots_k: float
    own_goal_rate: float
    ctx: TeamPlayerContext | None


def _sample_lineups(ctx: TeamPlayerContext, n: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Dönüş: dakika (n×P), giriş dakikası (n×P, -1=oynamadı), çıkış dakikası (n×P)."""
    L = ctx.lineup
    P = len(L)
    is_gk = np.array([e.pos_group == "G" for e in L])
    start_p = np.array([e.start_prob for e in L])
    sub_p = np.array([e.sub_prob for e in L])
    on = np.full((n, P), -1, dtype=np.int64)
    off = np.full((n, P), -1, dtype=np.int64)

    if ctx.lineup_confirmed:
        starters = np.tile(np.array([e.confirmed_starter is True for e in L]), (n, 1))
        bench_ok = np.array([e.confirmed_starter is False for e in L])
    else:
        g = rng.gumbel(size=(n, P))
        keys = np.log(start_p + 1e-4) + g
        starters = np.zeros((n, P), dtype=bool)
        if is_gk.any():
            gk_keys = np.where(is_gk[None, :], keys, -np.inf)
            starters[np.arange(n), np.argmax(gk_keys, axis=1)] = True
        of_keys = np.where(is_gk[None, :], -np.inf, keys)
        n_out = min(10, int((~is_gk).sum()))
        if n_out:
            top = np.argpartition(-of_keys, n_out - 1, axis=1)[:, :n_out]
            starters[np.arange(n)[:, None], top] = True
        bench_ok = sub_p > 0

    # Çıkış dakikaları
    exit_m = np.full((n, P), 90, dtype=np.int64)
    for j, e in enumerate(L):
        if len(e.start_exit) >= 3:
            exit_m[:, j] = np.array(e.start_exit)[rng.integers(0, len(e.start_exit), size=n)]
        else:
            full = rng.random(n) < _POS_FULL90.get(e.pos_group, 0.6)
            exit_m[:, j] = np.where(full, 90, rng.integers(46, 90, size=n))
    # Kaleci değişikliği modellenmez (kaleci yerine saha oyuncusu girmesin); diğer çıkışlar en fazla 5 değişiklik
    # ve uygun yedek sayısıyla sınırlanır: değiştirilemeyen oyuncu sahada kalır (takım 10 kişi kalmaz).
    exit_m = np.where(starters & ~is_gk[None, :], exit_m, 90)
    bkeys = np.log(sub_p + 1e-4)[None, :] + rng.gumbel(size=(n, P))
    bkeys = np.where(starters | is_gk[None, :] | ~bench_ok[None, :], -np.inf, bkeys)
    allowed = np.minimum(5, np.isfinite(bkeys).sum(axis=1))
    exiting = np.where(exit_m < 90, exit_m, 10_000)
    rank = np.argsort(np.argsort(exiting, axis=1, kind="stable"), axis=1, kind="stable")
    exit_m = np.where((exit_m < 90) & (rank < allowed[:, None]), exit_m, 90)
    on[starters] = 0
    off[starters] = exit_m[starters]

    # Yedekler: çıkan ilk 11 oyuncularının yerine, yedek eğilimiyle seçilir (sıralı eşleme)
    exit_sorted = np.sort(np.where(starters & (exit_m < 90), exit_m, 10_000), axis=1)
    order = np.argsort(-bkeys, axis=1)
    rows = np.arange(n)
    for s in range(min(5, P)):
        cand = order[:, s]
        entry = exit_sorted[:, s]
        valid = (entry < 90) & np.isfinite(bkeys[rows, cand])
        on[rows[valid], cand[valid]] = entry[valid]
        off[rows[valid], cand[valid]] = 90
    minutes = np.where(on >= 0, off - on, 0)
    return minutes.astype(float), on, off


def sample_shots(goals: np.ndarray, mu: float, k: float, u: np.ndarray, v: np.ndarray, omega: float,
                 rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Skora (goals) koşullu takım şut (S), isabetli şut (T) ve oyuncu golü (F) — senaryo bazlı u, v ile tam örnekleme."""
    n = goals.size
    pg = u * v
    f = np.arange(MAX_GOALS + 1)
    m = (mu * pg)[:, None]                                   # F'nin koşulsuz NB ortalaması
    logw = nbinom.logpmf(f[None, :], k, k / (k + m)) + poisson.logpmf(goals[:, None] - f[None, :], omega)
    logw = np.where(f[None, :] <= goals[:, None], logw, -np.inf)
    F = np.argmax(logw + rng.gumbel(size=logw.shape), axis=1)   # Gumbel-max ile kategorik örnek
    lam = rng.gamma(shape=k + F, scale=1.0 / (k / mu + pg), size=n)
    sot_nogoal = rng.poisson(lam * u * (1 - v))
    off_target = rng.poisson(lam * (1 - u))
    T = F + sot_nogoal
    S = T + off_target
    return S.astype(np.int64), T.astype(np.int64), F.astype(np.int64)


def _safe_norm(m: np.ndarray) -> np.ndarray:
    z = m.sum(axis=1, keepdims=True)
    P = m.shape[1]
    return np.where(z > 0, m / np.where(z > 0, z, 1), 1.0 / P)


def simulate_match(
    score: np.ndarray,
    home: TeamSimInput,
    away: TeamSimInput,
    n_sims: int,
    n_scenarios: int,
    seed: int,
) -> dict:
    rng = np.random.default_rng(seed)
    flat = score.ravel()
    draws = rng.choice(flat.size, size=n_sims, p=flat / flat.sum())
    gh, ga = np.unravel_index(draws, score.shape)
    out: dict = {"n_sims": n_sims, "teams": {}, "scenarios": []}
    per_team: dict[str, dict] = {}

    for side, inp, goals in (("home", home, gh), ("away", away, ga)):
        ctx = inp.ctx
        use_players = ctx is not None and ctx.data_ok and len(ctx.lineup) >= 11
        if use_players:
            assert ctx is not None
            minutes, on, off = _sample_lineups(ctx, n_sims, rng)
            ids = [e.player_id for e in ctx.lineup]
            r = np.array([ctx.rates[i].shots_p90 for i in ids])
            a = np.array([ctx.rates[i].acc for i in ids])
            b = np.array([ctx.rates[i].conv for i in ids])
            wm = minutes * r[None, :]
            w = _safe_norm(wm)
            u_s = np.sum(w * a[None, :], axis=1)                       # senaryo bazlı isabet oranı
            v_s = np.sum(w * (a * b)[None, :], axis=1) / np.maximum(u_s, 1e-9)
        else:
            minutes = on = off = None
            u_s = np.full(n_sims, 0.33)
            v_s = np.full(n_sims, 0.30)
        u_s = np.clip(u_s, 0.08, 0.8)
        v_s = np.clip(v_s, 0.05, 0.8)
        S, T, F = sample_shots(goals.astype(np.int64), inp.shots_mu, inp.shots_k, u_s, v_s, inp.own_goal_rate, rng)
        O = goals - F
        team_out = {
            "team_id": inp.team_id,
            "u": float(u_s.mean()),
            "v": float(v_s.mean()),
            "shots_mu_prior": inp.shots_mu,
            "shots": _dist_summary(S, [5, 8, 10, 12, 15, 18]),
            "shots_on_target": _dist_summary(T, [1, 2, 3, 4, 5, 6, 7]),
            "own_goals_for": float(O.mean()),
            "players": [],
            "players_available": use_players,
        }
        if use_players:
            assert ctx is not None and minutes is not None
            pg = rng.multinomial(F, _safe_norm(w * (a * b)[None, :]))
            psot = rng.multinomial(T - F, _safe_norm(w * (a * (1 - b))[None, :]))
            poff = rng.multinomial(S - T, _safe_norm(w * (1 - a)[None, :]))
            p_sot = pg + psot
            p_shots = p_sot + poff
            played = minutes > 0
            players = []
            for j, e in enumerate(ctx.lineup):
                pr = ctx.rates[e.player_id]
                pl = played[:, j]
                p_play = float(pl.mean())
                if p_play < 0.08:
                    continue  # kadroya pek girmeyen oyuncular tabloda yer kaplamasın (simülasyona dahiller)
                players.append(
                    {
                        "player_id": e.player_id,
                        "name": e.name,
                        "pos_group": e.pos_group,
                        "position": e.position,
                        "p_play": p_play,
                        "p_start": float((on[:, j] == 0).mean()),
                        "exp_minutes": float(minutes[:, j].mean()),
                        "exp_shots": float(p_shots[:, j].mean()),
                        "p_shots_1": float((p_shots[:, j] >= 1).mean()),
                        "p_shots_2": float((p_shots[:, j] >= 2).mean()),
                        "p_shots_3": float((p_shots[:, j] >= 3).mean()),
                        "exp_sot": float(p_sot[:, j].mean()),
                        "p_sot_1": float((p_sot[:, j] >= 1).mean()),
                        "p_sot_2": float((p_sot[:, j] >= 2).mean()),
                        "p_goal": float((pg[:, j] >= 1).mean()),
                        "p_goal_2": float((pg[:, j] >= 2).mean()),
                        "rate_shots_p90": pr.shots_p90,
                        "rate_acc": pr.acc,
                        "rate_conv": pr.conv,
                        "minutes_seen": pr.minutes_seen,
                        "confirmed_starter": e.confirmed_starter,
                        "flags": e.flags,
                    }
                )
            players.sort(key=lambda x: -x["exp_shots"])
            team_out["players"] = players
            per_team[side] = {"ids": [e.player_id for e in ctx.lineup], "names": [e.name for e in ctx.lineup],
                              "on": on, "off": off, "goals": pg, "sot": psot, "off_t": poff}
        else:
            per_team[side] = {}
        per_team[side].update({"S": S, "T": T, "F": F, "O": O})
        out["teams"][side] = team_out

    out["scenarios"] = [
        _scenario(i, gh, ga, per_team, home.team_id, away.team_id, rng) for i in range(min(n_scenarios, n_sims))
    ]
    return out


def _dist_summary(x: np.ndarray, thresholds: list[int]) -> dict:
    vals, cnt = np.unique(x, return_counts=True)
    return {
        "mean": float(x.mean()),
        "p10": float(np.percentile(x, 10)),
        "p50": float(np.percentile(x, 50)),
        "p90": float(np.percentile(x, 90)),
        "at_least": {str(t): float((x >= t).mean()) for t in thresholds},
        "pmf": {str(int(v)): float(c / x.size) for v, c in zip(vals, cnt)},
    }


def _scenario(i: int, gh: np.ndarray, ga: np.ndarray, per_team: dict, home_id: str, away_id: str, rng: np.random.Generator) -> dict:
    """Bir simülasyon örneğinden dakika dakika olay akışı (dakikalar oyuncunun sahada olduğu aralıktan örneklenir)."""
    events: list[dict] = []
    for side, team_id in (("home", home_id), ("away", away_id)):
        d = per_team.get(side, {})
        if "ids" in d:
            on, off = d["on"][i], d["off"][i]
            for j, pid in enumerate(d["ids"]):
                if on[j] < 0:
                    continue
                lo, hi = int(on[j]) + 1, max(int(off[j]), int(on[j]) + 1)
                for typ, arr in (("goal", d["goals"]), ("sot", d["sot"]), ("shot", d["off_t"])):
                    for _ in range(int(arr[i, j])):
                        events.append({"minute": int(rng.integers(lo, hi + 1)), "side": side, "team_id": team_id,
                                       "player_id": pid, "player": d["names"][j], "type": typ})
                if on[j] > 0:
                    events.append({"minute": int(on[j]), "side": side, "team_id": team_id, "player_id": pid,
                                   "player": d["names"][j], "type": "sub_in"})
        else:
            # Oyuncu verisi yok: takım düzeyinde olaylar
            for typ, cnt in (("goal", int(d["F"][i])), ("sot", int(d["T"][i] - d["F"][i])), ("shot", int(d["S"][i] - d["T"][i]))):
                for _ in range(cnt):
                    events.append({"minute": int(rng.integers(1, 91)), "side": side, "team_id": team_id,
                                   "player_id": None, "player": None, "type": typ})
        for _ in range(int(d["O"][i])):
            events.append({"minute": int(rng.integers(1, 91)), "side": side, "team_id": team_id, "player_id": None,
                           "player": None, "type": "own_goal_for"})
    order = {"sub_in": 0, "shot": 1, "sot": 2, "goal": 3, "own_goal_for": 3}
    events.sort(key=lambda e: (e["minute"], order[e["type"]]))
    ht_h = sum(1 for e in events if e["side"] == "home" and e["type"] in ("goal", "own_goal_for") and e["minute"] <= 45)
    ht_a = sum(1 for e in events if e["side"] == "away" and e["type"] in ("goal", "own_goal_for") and e["minute"] <= 45)
    return {
        "score": [int(gh[i]), int(ga[i])],
        "ht": [ht_h, ht_a],
        "stats": {
            side: {"shots": int(per_team[side]["S"][i]), "sot": int(per_team[side]["T"][i])} for side in ("home", "away")
        },
        "events": events,
    }
