"""Model fit + maç tahmini (pazarlar, iddaa karşılaştırması, korner, simülasyon)."""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np

from .. import db
from ..config import (
    BLEND_WEIGHT_DEFAULT, DATA_DIR, DEFAULT_SIGMA, DEFAULT_TAU, DEFAULT_XI, LEAGUE_BY_SLUG, N_SCENARIOS, N_SIMS,
    REFERENCE_LEAGUE,
)
from ..sources.iddaa import MARKETS
from . import markets as mk
from .count_model import CountModel, fit_count_model, nb_dispersion
from .goals import GoalModel, MatchRecord, build_count_data, fit_goal_model, score_matrix
from .market_fit import MarketTarget, blend_matrix, fit_market_matrix, ms_probs
from .players import PlayerStore, lineup_factor, own_goal_rate
from .simulate import TeamSimInput, simulate_match

log = logging.getLogger(__name__)
PARAMS_PATH = DATA_DIR / "model_params.json"
MODEL_VERSION = "v1"


def load_params(con: sqlite3.Connection | None = None) -> dict[str, float]:
    """Model hiperparametreleri veritabanında saklanır (GitHub'da yalnızca veritabanı çalışmalar arasında taşınır).
    Eski kurulumlardaki model_params.json dosyası geçiş için okunur."""
    p = {"xi": DEFAULT_XI, "sigma": DEFAULT_SIGMA, "tau": DEFAULT_TAU, "alpha": 1.0, "cal_t": 1.0, "cal_g": 1.0}
    stored = db.meta_get(con, "model_params") if con is not None else None
    if isinstance(stored, dict):
        p.update({k: float(v) for k, v in stored.items() if k in p})
    elif PARAMS_PATH.exists():
        try:
            p.update({k: float(v) for k, v in json.loads(PARAMS_PATH.read_text(encoding="utf-8")).items() if k in p})
        except (ValueError, OSError) as e:
            log.error("model_params.json okunamadı, varsayılanlar kullanılıyor: %s", e)
    return p


@dataclass
class AuxCountModel:
    model: CountModel
    k: float
    n: int

    def means(self, comp: str, home: str, away: str, neutral: bool) -> tuple[float, float] | None:
        lr = self.model.log_rates(comp, home, away, neutral)
        if lr is None:
            return None
        return float(np.exp(lr[0])), float(np.exp(lr[1]))


@dataclass
class FittedModels:
    as_of: datetime
    goals: GoalModel
    shots: AuxCountModel | None
    corners: AuxCountModel | None
    players: PlayerStore
    omega: float
    params: dict[str, float]

    @property
    def version(self) -> str:
        h = hashlib.sha1(json.dumps(self.params, sort_keys=True).encode()).hexdigest()[:6]
        return f"{MODEL_VERSION}-{self.as_of.strftime('%Y%m%d%H')}-{h}"


def _stat_values(con: sqlite3.Connection, before: str, column: str) -> dict[str, tuple[float, float]]:
    rows = con.execute(
        f"""SELECT s.match_id, s.is_home, s.{column} v FROM team_match_stats s JOIN matches m ON m.id=s.match_id
            WHERE m.completed=1 AND m.extra_time=0 AND m.date_utc < ? AND s.{column} IS NOT NULL""",
        (before,),
    ).fetchall()
    tmp: dict[str, dict[int, float]] = {}
    for r in rows:
        tmp.setdefault(r["match_id"], {})[int(r["is_home"])] = float(r["v"])
    return {mid: (d[1], d[0]) for mid, d in tmp.items() if 1 in d and 0 in d}


def _fit_aux(matches: list[MatchRecord], values: dict[str, tuple[float, float]], as_of: datetime, xi: float) -> AuxCountModel | None:
    data = build_count_data(matches, as_of, xi, values=values)
    if len(data.weight) < 200:
        return None
    m = fit_count_model(data, REFERENCE_LEAGUE, sigma=0.25, tau=0.3, home_prior=(0.1, 0.15), delta_prior_sd=0.2)
    eh = m.mu + m.home[data.comp_idx] * (1 - data.neutral) + m.delta[data.comp_idx] + m.att[data.home_idx] - m.defn[data.away_idx]
    ea = m.mu + m.delta[data.comp_idx] + m.att[data.away_idx] - m.defn[data.home_idx]
    y = np.concatenate([data.y_home, data.y_away])
    mu = np.exp(np.concatenate([eh, ea]))
    w = np.concatenate([data.weight, data.weight])
    return AuxCountModel(m, nb_dispersion(y, mu, w), len(data.weight))


def fit_all(con: sqlite3.Connection, as_of: datetime | None = None, params: dict[str, float] | None = None,
            with_aux: bool = True) -> FittedModels:
    as_of = as_of or datetime.now(timezone.utc)
    params = params or load_params(con)
    gm, matches, _ = fit_goal_model(con, as_of, params["xi"], params["sigma"], params["tau"], params.get("alpha", 1.0),
                                    params.get("cal_t", 1.0), params.get("cal_g", 1.0))
    before = gm.as_of
    shots = corners = None
    if with_aux:
        shots = _fit_aux(matches, _stat_values(con, before, "shots"), as_of, params["xi"])
        corners = _fit_aux(matches, _stat_values(con, before, "corners"), as_of, params["xi"])
        # Örneklem içi k aşırı uyum yüzünden Poisson'a kayar; varsa backtest'in örneklem dışı k'sı kullanılır
        disp = db.meta_get(con, "aux_dispersion") or {}
        for aux, key, fallback in ((shots, "shots", 12.0), (corners, "corners", 25.0)):
            if aux is not None:
                aux.k = float(disp.get(key, min(aux.k, fallback)))
    return FittedModels(as_of, gm, shots, corners, PlayerStore(con, as_of), own_goal_rate(con, before), params)


# ---------------------------------------------------------------- tahmin

def _family_validation(con: sqlite3.Connection) -> dict[str, bool]:
    v = db.meta_get(con, "family_validation") or {}
    return {k: bool(x.get("validated")) for k, x in v.items()} if isinstance(v, dict) else {}


def _blend_weight(con: sqlite3.Connection) -> tuple[float, bool]:
    """(model ağırlığı w, ayrı dilimde doğrulandı mı). Harman piyasadan kötü çıktıysa piyasaya (w=0) güvenilir."""
    b = db.meta_get(con, "blend_calibration")
    if isinstance(b, dict):
        if b.get("validated") and "weight" in b:
            return float(b["weight"]), True
        if b.get("status") == "dogrulanamadi":
            return 0.0, False
    return BLEND_WEIGHT_DEFAULT, False


def _confirmed_lineup(con: sqlite3.Connection, match_id: str, team_id: str) -> dict[str, bool] | None:
    rows = con.execute(
        "SELECT player_id, starter FROM player_match WHERE match_id=? AND team_id=?", (match_id, team_id)
    ).fetchall()
    if not rows or sum(r["starter"] for r in rows) < 11:
        return None
    return {r["player_id"]: bool(r["starter"]) for r in rows}


def _team_json(con: sqlite3.Connection, team_id: str) -> dict[str, Any]:
    r = con.execute("SELECT id, name, short_name, abbreviation, logo, color FROM teams WHERE id=?", (team_id,)).fetchone()
    return dict(r) if r else {"id": team_id, "name": team_id}


def standard_markets(j: mk.Joint) -> list[dict[str, Any]]:
    out = []
    for key, sov, names in mk.STANDARD_MARKETS:
        md = next(m for m in MARKETS.values() if m.key == key)
        outs = []
        for n in names:
            mask = mk.outcome_mask(key, sov, n, j)
            if mask is None:
                break
            outs.append({"name": n, "p_model": mk.prob(j, mask)})
        else:
            out.append({"key": key, "label": md.label, "family": md.family, "line": sov, "outcomes": outs})
    return out


def iddaa_markets(con: sqlite3.Connection, event_id: int, sm_model: np.ndarray, j_model: mk.Joint, p1: float, rho: float,
                  corners: dict | None, blend_w: float, validated: dict[str, bool],
                  start: tuple[float, float]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    rows = con.execute(
        """SELECT o.market_key, o.outcome_no, o.outcome_name, o.odd, o.mbs, o.fetched_at FROM odds_current o
           JOIN iddaa_events e ON e.id=o.event_id
           WHERE o.event_id=? AND e.active=1 AND e.is_live=0 ORDER BY o.market_key, o.outcome_no""",
        (event_id,),
    ).fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        groups.setdefault(r["market_key"], []).append(r)

    # 1) Piyasanın ima ettiği skor matrisi (ana pazarlardan) ve tek matriste harman
    targets: list[MarketTarget] = []
    for mkey, rs in groups.items():
        t, st, sov = mkey.split(":")
        md = MARKETS.get((int(t), int(st)))
        if md is None or md.key not in ("ms", "au", "kg", "ev_au", "dep_au", "hnd"):
            continue
        targets.append(MarketTarget(md.key, sov or None, [r["outcome_name"] for r in rs], mk.devig([float(r["odd"]) for r in rs])))
    fit = fit_market_matrix(targets, rho, start)
    info: dict[str, Any] | None = None
    j_blend: mk.Joint | None = None
    if fit is not None:
        sm_q = score_matrix(fit[0], fit[1], rho)
        sm_b = blend_matrix(sm_model, sm_q, blend_w)
        j_blend = mk.build_joint(sm_b, p1)
        ms_actual = next((t.q for t in targets if t.key == "ms" and t.names == ["1", "0", "2"]), None)
        info = {"lambda_home": fit[0], "lambda_away": fit[1], "kl": fit[2], "ms_market_fit": ms_probs(sm_q),
                "ms_blend": ms_probs(sm_b), "ms_market_actual": ms_actual}

    out = []
    for mkey, rs in groups.items():
        t, st, sov = mkey.split(":")
        md = MARKETS.get((int(t), int(st)))
        if md is None:
            continue
        sov_v = sov or None
        odds = [float(r["odd"]) for r in rs]
        q = mk.devig(odds)
        p_model: list[float] = []
        p_blend: list[float] | None = []
        ok = True
        if md.key == "korner_au":
            # Korner skor matrisinden bağımsız: tek pazar içinde harman (kendi içinde tutarlı)
            if corners is None or sov_v is None:
                continue
            alt, ust = mk.corner_over_prob(corners["mu_home"], corners["mu_away"], corners["k"], float(sov_v))
            lookup = {"Alt": alt, "Üst": ust}
            if any(r["outcome_name"] not in lookup for r in rs):
                continue
            p_model = [lookup[r["outcome_name"]] for r in rs]
            p_blend = mk.blend(p_model, q, blend_w)
        else:
            for r in rs:
                mask = mk.outcome_mask(md.key, sov_v, r["outcome_name"], j_model)
                if mask is None:
                    ok = False
                    break
                p_model.append(mk.prob(j_model, mask))
                if j_blend is not None and p_blend is not None:
                    p_blend.append(mk.prob(j_blend, mask))
            if not ok:
                continue
            if j_blend is None:
                p_blend = None
        if not mk.is_exhaustive(p_model):
            continue
        # Pazar içi harman GERÇEK iddaa olasılığıyla (projeksiyon hatası yok). Değer/EV için muhafazakâr olasılık:
        # p_safe = min(matris harmanı, pazar içi harman). w=0 iken p_safe <= piyasa -> EV <= -marj (sahte değer yok).
        p_local = mk.blend(p_model, q, blend_w)
        outs = []
        for i, r in enumerate(rs):
            pb = p_blend[i] if p_blend is not None else None
            p_safe = min(float(pb), float(p_local[i])) if pb is not None else None
            outs.append({
                "no": r["outcome_no"], "name": r["outcome_name"], "odd": float(r["odd"]),
                "p_model": float(p_model[i]), "p_market": float(q[i]), "p_blend": float(pb) if pb is not None else None,
                "p_safe": p_safe,
                "ev": float(p_safe * float(r["odd"]) - 1.0) if p_safe is not None else None,
                "ev_model": float(p_model[i] * float(r["odd"]) - 1.0),
            })
        out.append({
            "market_key": mkey, "key": md.key, "label": md.label, "family": md.family, "line": sov_v,
            "mbs": rs[0]["mbs"], "margin": mk.margin(odds), "family_validated": validated.get(md.family, False),
            "fetched_at": rs[0]["fetched_at"], "outcomes": outs,
        })
    order = {d.key: i for i, d in enumerate(MARKETS.values())}
    out.sort(key=lambda m: (order.get(m["key"], 99), float(m["line"]) if m["line"] not in (None, "") else 0.0))
    return out, info


def predict_match(con: sqlite3.Connection, fm: FittedModels, match: sqlite3.Row, n_sims: int = N_SIMS,
                  with_sim: bool = True) -> dict[str, Any] | None:
    comp, home, away = match["league"], match["home_id"], match["away_id"]
    neutral = bool(match["neutral"])
    rates = fm.goals.rates(comp, home, away, neutral)
    lg = LEAGUE_BY_SLUG.get(comp)
    base: dict[str, Any] = {
        "match": {
            "id": match["id"], "league": comp, "league_name": lg.name if lg else comp, "country": lg.country if lg else "",
            "date_utc": match["date_utc"], "venue": match["venue"], "neutral": neutral, "state": match["state"],
            "home": _team_json(con, home), "away": _team_json(con, away),
            "lineup_confirmed": bool(match["lineup_confirmed"]),
        },
        "model_version": fm.version,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if rates is None:
        base["covered"] = False
        base["coverage_note"] = "Takımlardan en az biri için geçmiş maç verisi yok"
        return base
    lh, la = rates
    # Resmi ilk 11 açıklandıysa takımın beklenen golü kadronun hücum gücüne göre ayarlanır (β backtest'ten)
    conf_h = _confirmed_lineup(con, match["id"], home)
    conf_a = _confirmed_lineup(con, match["id"], away)
    lineup_adj: dict[str, Any] = {"beta": 0.0, "home": 1.0, "away": 1.0, "home_ratio": None, "away_ratio": None}
    beta = float((db.meta_get(con, "lineup_beta") or {}).get("beta", 0.0))
    if beta > 0:
        lineup_adj["beta"] = beta
        if conf_h:
            lineup_adj["home"], lineup_adj["home_ratio"] = lineup_factor(fm.players, home, conf_h, beta)
        if conf_a:
            lineup_adj["away"], lineup_adj["away_ratio"] = lineup_factor(fm.players, away, conf_a, beta)
        lh, la = lh * lineup_adj["home"], la * lineup_adj["away"]
    level, notes = fm.goals.confidence(comp, home, away)
    p1 = fm.goals.p1.get(comp, fm.goals.p1_global)
    sm = fm.goals.matrix(lh, la)   # kalibre skor matrisi
    j = mk.build_joint(sm, p1)
    validated = _family_validation(con)
    blend_w, blend_calibrated = _blend_weight(con)

    corners = None
    if fm.corners:
        cm = fm.corners.means(comp, home, away, neutral)
        if cm:
            corners = {"mu_home": cm[0], "mu_away": cm[1], "k": fm.corners.k,
                       "lines": {str(L): dict(zip(("Alt", "Üst"), mk.corner_over_prob(cm[0], cm[1], fm.corners.k, L)))
                                 for L in (7.5, 8.5, 9.5, 10.5, 11.5)}}

    ev = con.execute(
        """SELECT id, mbs, competition_id FROM iddaa_events WHERE espn_match_id=? AND active=1 AND is_live=0
           ORDER BY match_score DESC LIMIT 1""",
        (match["id"],),
    ).fetchone()
    iddaa = None
    if ev:
        mkts, minfo = iddaa_markets(con, ev["id"], sm, j, p1, fm.goals.rho, corners, blend_w, validated, (lh, la))
        if mkts:
            iddaa = {"event_id": ev["id"], "mbs": ev["mbs"], "markets": mkts, "market_model": minfo}

    top = 7
    sm_view = sm[:top, :top]
    base.update({
        "covered": True,
        "model": {
            "lambda_home": lh, "lambda_away": la, "rho": fm.goals.rho, "p1": p1,
            "cal_t": fm.goals.cal_t, "cal_g": fm.goals.cal_g, "alpha": fm.goals.alpha, "lineup_adj": lineup_adj,
            "confidence": level, "confidence_notes": notes, "as_of": fm.goals.as_of,
            "params": fm.params, "blend_weight": blend_w, "blend_calibrated": blend_calibrated,
            "family_validation": validated,
        },
        "score_matrix": {"size": top, "p": sm_view.tolist(), "other": float(1 - sm_view.sum())},
        "top_scores": _top_scores(sm),
        "markets": standard_markets(j),
        "iddaa": iddaa,
        "corners": corners,
    })
    if with_sim and fm.shots is not None:
        smu = fm.shots.means(comp, home, away, neutral)
        if smu:
            ctx_h = fm.players.team_context(home, conf_h)
            ctx_a = fm.players.team_context(away, conf_a)
            seed = int(hashlib.sha1(match["id"].encode()).hexdigest()[:8], 16)
            sim = simulate_match(
                sm,
                TeamSimInput("home", home, smu[0], fm.shots.k, fm.omega, ctx_h),
                TeamSimInput("away", away, smu[1], fm.shots.k, fm.omega, ctx_a),
                n_sims, N_SCENARIOS, seed,
            )
            apply_player_calibration(sim, db.meta_get(con, "player_calibration") or {})
            sim["notes"] = {"home": ctx_h.notes, "away": ctx_a.notes,
                            "lineup_source": {"home": "resmi" if ctx_h.lineup_confirmed else "tahmini",
                                              "away": "resmi" if ctx_a.lineup_confirmed else "tahmini"}}
            base["sim"] = sim
    return base


def _top_scores(sm: np.ndarray, n: int = 8) -> list[dict[str, Any]]:
    idx = np.argsort(-sm.ravel())[:n]
    return [{"home": int(i // sm.shape[1]), "away": int(i % sm.shape[1]), "p": float(sm.ravel()[i])} for i in idx]


def predict_upcoming(con: sqlite3.Connection, fm: FittedModels, days: int = 7,
                     progress: Callable[[str], None] | None = None) -> dict[str, int]:
    now = datetime.now(timezone.utc)
    rows = con.execute(
        "SELECT * FROM matches WHERE state='pre' AND date_utc >= ? AND date_utc <= ? ORDER BY date_utc",
        ((now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), (now + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")),
    ).fetchall()
    done = covered = 0
    for i, r in enumerate(rows):
        try:
            payload = predict_match(con, fm, r)
        except Exception:  # noqa: BLE001 - tek maç hatası tüm tahminleri durdurmamalı; loglanır ve sayılır
            log.exception("Tahmin başarısız: %s", r["id"])
            continue
        if payload is None:
            continue
        with db.tx(con):
            # Tam yük yalnızca en son tahmin için; geçmiş kompakt günlükte (DB saatlik çalışmada şişmesin)
            con.execute("DELETE FROM predictions WHERE match_id=?", (r["id"],))
            con.execute(
                "INSERT INTO predictions(match_id, created_at, model_version, payload) VALUES(?,?,?,?)",
                (r["id"], payload["created_at"], fm.version, json.dumps(payload, ensure_ascii=False)),
            )
            log_prediction(con, payload)
        done += 1
        covered += int(bool(payload.get("covered")))
        if progress and (i + 1) % 25 == 0:
            progress(f"Tahminler: {i + 1}/{len(rows)}")
    with db.tx(con):
        db.meta_set(con, "current_model_version", fm.version)
        db.meta_set(con, "current_model_as_of", fm.goals.as_of)
    return {"matches": len(rows), "predicted": done, "covered": covered}


# ---------------------------------------------------------------- kalibrasyon ve günlük

PLAYER_CAL_FIELDS = {
    "p_sot_1": "p_sot_1", "p_sot_2": "p_sot_2", "p_shots_1": "p_shots_1", "p_shots_2": "p_shots_2",
    "p_shots_3": "p_shots_3", "p_goal": "p_goal", "p_play": "p_play",
}


def platt(p: float, a: float, b: float) -> float:
    q = min(max(p, 1e-6), 1 - 1e-6)
    z = a + b * np.log(q / (1 - q))
    return float(1.0 / (1.0 + np.exp(-z)))


def apply_player_calibration(sim: dict, cal: dict) -> None:
    """Backtest'te çapraz doğrulamayla kazanç gösteren Platt düzeltmelerini uygular; sıralama tutarlılığını korur."""
    if not cal:
        return
    for side in ("home", "away"):
        team = sim["teams"][side]
        for pl in team["players"]:
            for field in PLAYER_CAL_FIELDS:
                c = cal.get(field)
                if c and c.get("use"):
                    pl[field] = platt(pl[field], c["a"], c["b"])
            # Mantıksal sıralama (kalibrasyon sonrası da): olay A, B'yi gerektiriyorsa P(A) ≤ P(B)
            pl["p_shots_1"] = min(pl["p_shots_1"], pl["p_play"])
            pl["p_sot_1"] = min(pl["p_sot_1"], pl["p_shots_1"])
            pl["p_goal"] = min(pl["p_goal"], pl["p_sot_1"])
            pl["p_shots_2"] = min(pl["p_shots_2"], pl["p_shots_1"])
            pl["p_shots_3"] = min(pl["p_shots_3"], pl["p_shots_2"])
            pl["p_sot_2"] = min(pl["p_sot_2"], pl["p_sot_1"], pl["p_shots_2"])
            pl["p_goal_2"] = min(pl["p_goal_2"], pl["p_goal"], pl["p_sot_2"])
        c = cal.get("team_sot")
        if c and c.get("use"):
            al = team["shots_on_target"]["at_least"]
            prev = 1.0
            for k in sorted(al, key=int):
                prev = min(prev, platt(al[k], c["a"], c["b"]))
                al[k] = prev
        team["calibrated"] = True


def log_prediction(con: sqlite3.Connection, payload: dict) -> None:
    from ..coupons import model_pick

    if not payload.get("covered") or not payload.get("model"):
        return
    m = payload["model"]
    idd = payload.get("iddaa") or {}
    mm = idd.get("market_model") or {}
    pk = model_pick(payload)
    pick = None
    if pk is not None:
        pick = {"market_key": pk.market_key, "outcome_no": pk.outcome_no, "key": pk.key, "label": pk.label, "line": pk.line,
                "name": pk.outcome_name, "odd": pk.odd, "p_model": pk.p_model, "p_safe": pk.p_blend, "ev": pk.ev,
                "family": pk.family}
    con.execute(
        """INSERT OR REPLACE INTO prediction_log(match_id, created_at, model_version, lambda_home, lambda_away, rho, cal_t,
               cal_g, mkt_lambda_home, mkt_lambda_away, ms_market_actual, blend_weight, iddaa_event_id, pick)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (payload["match"]["id"], payload["created_at"], payload["model_version"], m["lambda_home"], m["lambda_away"], m["rho"],
         m.get("cal_t", 1.0), m.get("cal_g", 1.0), mm.get("lambda_home"), mm.get("lambda_away"),
         json.dumps(mm.get("ms_market_actual")) if mm.get("ms_market_actual") else None, m.get("blend_weight"),
         idd.get("event_id"), json.dumps(pick, ensure_ascii=False) if pick else None),
    )


def compact_predictions(con: sqlite3.Connection) -> int:
    """Eski tam tahmin yüklerini günlüğe aktarır ve maç başına yalnızca son yükü tutar (idempotent)."""
    rows = con.execute(
        """SELECT p.match_id, p.created_at, p.payload FROM predictions p
           WHERE p.created_at < (SELECT MAX(created_at) FROM predictions p2 WHERE p2.match_id=p.match_id)
              OR NOT EXISTS (SELECT 1 FROM prediction_log l WHERE l.match_id=p.match_id AND l.created_at=p.created_at)"""
    ).fetchall()
    n = 0
    with db.tx(con):
        for r in rows:
            try:
                log_prediction(con, json.loads(r["payload"]))
            except (ValueError, KeyError):
                continue
            n += 1
        con.execute(
            """DELETE FROM predictions WHERE created_at < (SELECT MAX(created_at) FROM predictions p2
               WHERE p2.match_id = predictions.match_id)"""
        )
    return n
