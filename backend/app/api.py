"""FastAPI arka uç. Yalnızca 127.0.0.1'e bağlanır; her istek yerel paylaşılan token ister
(Next.js sunucu tarafı bu token ile çağırır, tarayıcı arka uca doğrudan erişmez)."""
from __future__ import annotations

import json
import logging
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from . import coupons, db
from .config import DATA_DIR, LEAGUES, ROOT, TOKEN_PATH
from .model import markets as mk

log = logging.getLogger("api")


def _load_or_create_token() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if TOKEN_PATH.exists():
        t = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    t = secrets.token_urlsafe(32)
    TOKEN_PATH.write_text(t, encoding="utf-8")
    return t


API_TOKEN = _load_or_create_token()


def require_token(x_local_token: str | None = Header(default=None)) -> None:
    if not x_local_token or not secrets.compare_digest(x_local_token, API_TOKEN):
        raise HTTPException(status_code=401, detail="Yetkisiz: geçerli X-Local-Token gerekli")


app = FastAPI(title="iddaa-lab", version="1.0", dependencies=[Depends(require_token)])


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def con() -> Any:
    return db.get_conn()


# ---------------------------------------------------------------- işler / zamanlayıcı

_job_lock = threading.Lock()
_job_proc: subprocess.Popen | None = None


def _running_job(c) -> dict | None:
    r = c.execute("SELECT * FROM job_runs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
    if r is None:
        return None
    started = datetime.fromisoformat(r["started_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) - started > timedelta(hours=6):
        return None  # yarım kalmış eski kayıt
    return dict(r)


def start_job(command: str) -> dict[str, Any]:
    global _job_proc
    with _job_lock:
        if _job_proc is not None and _job_proc.poll() is None:
            return {"started": False, "reason": "Zaten çalışan bir iş var"}
        if _running_job(con()) is not None:
            return {"started": False, "reason": "Zaten çalışan bir iş var"}
        log_path = DATA_DIR / f"job_{command}.log"
        fh = open(log_path, "a", encoding="utf-8")  # noqa: SIM115 - alt süreç yaşadıkça açık kalmalı
        _job_proc = subprocess.Popen(
            [sys.executable, "-m", "app.jobs", command], cwd=str(ROOT / "backend"), stdout=fh, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {"started": True, "command": command, "pid": _job_proc.pid}


def _scheduler() -> None:
    """Uygulama açıkken: iddaa oranları 30 dakikada, tam güncelleme 3 saatte bir (bayatsa)."""
    time.sleep(20)
    while True:
        try:
            c = db.connect()
            last_full = c.execute(
                "SELECT MAX(finished_at) f FROM job_runs WHERE job IN ('refresh','bootstrap') AND status='ok'").fetchone()["f"]
            last_odds = c.execute(
                "SELECT MAX(finished_at) f FROM job_runs WHERE job IN ('refresh','bootstrap','odds') AND status='ok'").fetchone()["f"]
            c.close()
            now = datetime.now(timezone.utc)

            def age(s: str | None) -> float:
                return 1e9 if not s else (now - datetime.fromisoformat(s.replace("Z", "+00:00"))).total_seconds()

            if age(last_full) > 3 * 3600:
                start_job("refresh")
            elif age(last_odds) > 30 * 60:
                start_job("odds")
        except Exception:  # noqa: BLE001 - zamanlayıcı ölmemeli; hata loglanır
            log.exception("Zamanlayıcı hatası")
        time.sleep(120)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    threading.Thread(target=_scheduler, daemon=True, name="scheduler").start()


# ---------------------------------------------------------------- modeller

class Pick(BaseModel):
    match_id: str = Field(min_length=1, max_length=32)
    market_key: str = Field(min_length=3, max_length=32)
    outcome_no: int = Field(ge=0, le=50)


class CustomCoupon(BaseModel):
    picks: list[Pick] = Field(min_length=1, max_length=20)


class RefreshRequest(BaseModel):
    command: str = Field(default="refresh", pattern="^(refresh|odds|backtest)$")


# ---------------------------------------------------------------- uç noktalar

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "time": _iso(datetime.now(timezone.utc))}


@app.get("/api/status")
def status() -> dict[str, Any]:
    c = con()
    jobs = [dict(r) for r in c.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 12")]
    counts = {
        "matches": c.execute("SELECT COUNT(*) n FROM matches").fetchone()["n"],
        "completed": c.execute("SELECT COUNT(*) n FROM matches WHERE completed=1").fetchone()["n"],
        "summaries_ok": c.execute("SELECT COUNT(*) n FROM matches WHERE summary_status='ok'").fetchone()["n"],
        "player_rows": c.execute("SELECT COUNT(*) n FROM player_match").fetchone()["n"],
        "iddaa_events": c.execute("SELECT COUNT(*) n FROM iddaa_events WHERE kickoff_utc >= ?", (_iso(datetime.now(timezone.utc)),)).fetchone()["n"],
        "iddaa_matched": c.execute("SELECT COUNT(*) n FROM iddaa_events WHERE espn_match_id IS NOT NULL AND kickoff_utc >= ?", (_iso(datetime.now(timezone.utc)),)).fetchone()["n"],
        "odds_history": c.execute("SELECT COUNT(*) n FROM odds_history").fetchone()["n"],
        "predictions": c.execute("SELECT COUNT(DISTINCT match_id) n FROM predictions").fetchone()["n"],
    }
    return {
        "jobs": jobs,
        "running": _running_job(c),
        "counts": counts,
        "model_version": db.meta_get(c, "current_model_version"),
        "model_as_of": db.meta_get(c, "current_model_as_of"),
        "iddaa_last_fetch": db.meta_get(c, "iddaa_last_fetch"),
    }


@app.post("/api/refresh")
def refresh(req: RefreshRequest) -> dict[str, Any]:
    return start_job(req.command)


def _row_summary(p: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"match": p["match"], "covered": p.get("covered", False), "model_version": p.get("model_version"),
                           "created_at": p.get("created_at")}
    if not p.get("covered"):
        out["coverage_note"] = p.get("coverage_note")
        return out
    mkts = {(m["key"], m["line"]): m for m in p["markets"]}

    def outs(key: str, line: str | None) -> dict[str, float]:
        m = mkts.get((key, line))
        return {o["name"]: o["p_model"] for o in m["outcomes"]} if m else {}

    out.update({
        "lambda_home": p["model"]["lambda_home"], "lambda_away": p["model"]["lambda_away"],
        "confidence": p["model"]["confidence"],
        "ms": outs("ms", None), "au25": outs("au", "2.5"), "kg": outs("kg", None),
        "top_score": p["top_scores"][0] if p.get("top_scores") else None,
        "has_sim": "sim" in p,
    })
    if p.get("iddaa"):
        ms_odds = None
        for m in p["iddaa"]["markets"]:
            if m["key"] == "ms":
                ms_odds = {o["name"]: o["odd"] for o in m["outcomes"]}
        # Model önerisi: modelin maça bakışını yansıtan kademeli kural (coupons.model_pick) — kuponlarla aynı
        pk = coupons.model_pick(p)
        best = None
        if pk is not None:
            best = {"label": pk.label, "line": pk.line, "name": pk.outcome_name, "odd": pk.odd, "ev": pk.ev,
                    "p_blend": pk.p_model, "validated": pk.family_validated}
        out["iddaa"] = {"event_id": p["iddaa"]["event_id"], "mbs": p["iddaa"]["mbs"], "ms_odds": ms_odds, "best_value": best,
                        "n_markets": len(p["iddaa"]["markets"])}
    if "sim" in p:
        tops = []
        for side in ("home", "away"):
            for pl in p["sim"]["teams"][side]["players"][:2]:
                tops.append({"side": side, "name": pl["name"], "p_sot_1": pl["p_sot_1"], "p_goal": pl["p_goal"]})
        out["top_players"] = sorted(tops, key=lambda x: -x["p_sot_1"])[:3]
    return out


@app.get("/api/matches")
def matches(days: float = Query(7, ge=0.1, le=14), league: str | None = Query(None, max_length=40),
            include_market_only: bool = Query(True)) -> dict[str, Any]:
    c = con()
    preds = coupons.latest_predictions(c, days, min_lead_minutes=-180)
    items = [_row_summary(p) for p in preds if league is None or p["match"]["league"] == league]
    market_only: list[dict[str, Any]] = []
    if include_market_only:
        now = datetime.now(timezone.utc)
        rows = c.execute(
            """SELECT e.id, e.home_name, e.away_name, e.kickoff_utc, e.mbs, ic.name comp, ic.country_code cc
               FROM iddaa_events e LEFT JOIN iddaa_competitions ic ON ic.id=e.competition_id
               WHERE e.espn_match_id IS NULL AND e.is_live=0 AND e.kickoff_utc >= ? AND e.kickoff_utc <= ?
                 AND EXISTS (SELECT 1 FROM odds_current o WHERE o.event_id=e.id AND o.market_key='1:1:')
               ORDER BY e.kickoff_utc""",
            (_iso(now), _iso(now + timedelta(days=days))),
        ).fetchall()
        ms_odds = {}
        for r in c.execute("SELECT event_id, outcome_name, odd FROM odds_current WHERE market_key='1:1:'"):
            ms_odds.setdefault(r["event_id"], {})[r["outcome_name"]] = r["odd"]
        for r in rows:
            o = ms_odds.get(r["id"])
            q = None
            if o and all(k in o for k in ("1", "0", "2")):
                qq = mk.devig([o["1"], o["0"], o["2"]])
                q = {"1": qq[0], "0": qq[1], "2": qq[2]}
            market_only.append({"event_id": r["id"], "home": r["home_name"], "away": r["away_name"], "kickoff_utc": r["kickoff_utc"],
                                "competition": r["comp"], "country_code": r["cc"], "mbs": r["mbs"], "ms_odds": o, "ms_market_prob": q})
    leagues = sorted({(i["match"]["league"], i["match"]["league_name"], i["match"]["country"]) for i in items})
    return {"items": items, "market_only": market_only,
            "leagues": [{"slug": s, "name": n, "country": ct} for s, n, ct in leagues],
            "generated_at": _iso(datetime.now(timezone.utc))}


@app.get("/api/matches/{match_id}")
def match_detail(match_id: str) -> dict[str, Any]:
    if not match_id.isdigit() or len(match_id) > 20:
        raise HTTPException(400, "Geçersiz maç kimliği")
    c = con()
    r = c.execute(
        "SELECT payload FROM predictions WHERE match_id=? ORDER BY created_at DESC LIMIT 1", (match_id,)
    ).fetchone()
    if r is None:
        raise HTTPException(404, "Bu maç için tahmin bulunamadı (model kapsamı dışında ya da henüz hesaplanmadı)")
    p = json.loads(r["payload"])
    hist = []
    if p.get("iddaa"):
        for h in c.execute(
            "SELECT outcome_no, odd, fetched_at FROM odds_history WHERE event_id=? AND market_key='1:1:' ORDER BY fetched_at",
            (p["iddaa"]["event_id"],),
        ):
            hist.append(dict(h))
    p["odds_history_ms"] = hist
    # Son karşılaşmalar ve form
    m = p["match"]
    form = {}
    for side in ("home", "away"):
        tid = m[side]["id"]
        rows = c.execute(
            """SELECT m.id, m.date_utc, m.league, m.home_id, m.away_id, m.home_goals, m.away_goals, th.name hn, ta.name an
               FROM matches m JOIN teams th ON th.id=m.home_id JOIN teams ta ON ta.id=m.away_id
               WHERE m.completed=1 AND (m.home_id=? OR m.away_id=?) AND m.date_utc < ? ORDER BY m.date_utc DESC LIMIT 6""",
            (tid, tid, m["date_utc"]),
        ).fetchall()
        form[side] = [{**dict(x), "is_home": x["home_id"] == tid} for x in rows]
    p["form"] = form
    return p


@app.get("/api/coupons")
def get_coupons(days: float = Query(3, ge=0.2, le=7)) -> dict[str, Any]:
    return coupons.generate(con(), days, archive=False)


@app.get("/api/coupons/history")
def coupon_history() -> dict[str, Any]:
    return coupons.history(con())


@app.post("/api/coupons/evaluate")
def coupon_evaluate(body: CustomCoupon) -> dict[str, Any]:
    return coupons.evaluate_custom(con(), [p.model_dump() for p in body.picks])


@app.get("/api/players/top")
def players_top(days: float = Query(3, ge=0.2, le=7), limit: int = Query(60, ge=5, le=300)) -> dict[str, Any]:
    out = []
    for p in coupons.latest_predictions(con(), days):
        sim = p.get("sim")
        if not sim:
            continue
        for side in ("home", "away"):
            team = p["match"][side]
            opp = p["match"]["away" if side == "home" else "home"]
            for pl in sim["teams"][side]["players"]:
                if pl["p_play"] < 0.5:
                    continue
                out.append({**pl, "match_id": p["match"]["id"], "date_utc": p["match"]["date_utc"],
                            "league_name": p["match"]["league_name"], "team": team["name"], "team_logo": team.get("logo"),
                            "opponent": opp["name"], "side": side,
                            "lineup_source": sim["notes"]["lineup_source"][side]})
    out.sort(key=lambda x: -x["p_sot_1"])
    return {"items": out[:limit], "total": len(out)}


@app.get("/api/performance")
def performance() -> dict[str, Any]:
    c = con()
    return {
        "backtest": db.meta_get(c, "backtest"),
        "player_backtest": db.meta_get(c, "player_backtest"),
        "blend_calibration": db.meta_get(c, "blend_calibration"),
        "coupons": coupons.history(c, limit=500)["summary"],
        "league_names": {lg.slug: f"{lg.country} · {lg.name}" for lg in LEAGUES},
    }


@app.get("/api/coverage")
def coverage() -> dict[str, Any]:
    c = con()
    rows = c.execute(
        """SELECT league,
                  COUNT(*) total,
                  SUM(completed) completed,
                  SUM(CASE WHEN summary_status='ok' THEN 1 ELSE 0 END) summaries_ok,
                  SUM(CASE WHEN summary_status='missing_players' THEN 1 ELSE 0 END) summaries_missing,
                  SUM(CASE WHEN home_ht IS NOT NULL THEN 1 ELSE 0 END) with_ht,
                  MIN(date_utc) first, MAX(CASE WHEN completed=1 THEN date_utc END) last_completed,
                  SUM(CASE WHEN state='pre' THEN 1 ELSE 0 END) upcoming
           FROM matches GROUP BY league"""
    ).fetchall()
    stat_cov = {r["league"]: r for r in c.execute(
        """SELECT m.league, COUNT(*) n, SUM(CASE WHEN s.shots IS NOT NULL THEN 1 ELSE 0 END) shots,
                  SUM(CASE WHEN s.corners IS NOT NULL THEN 1 ELSE 0 END) corners
           FROM team_match_stats s JOIN matches m ON m.id=s.match_id GROUP BY m.league""")}
    linked = {r["league"]: r["n"] for r in c.execute(
        """SELECT m.league, COUNT(DISTINCT e.id) n FROM iddaa_events e JOIN matches m ON m.id=e.espn_match_id GROUP BY m.league""")}
    by_slug = {r["league"]: r for r in rows}
    out = []
    for lg in LEAGUES:
        r = by_slug.get(lg.slug)
        sc = stat_cov.get(lg.slug)
        out.append({
            "slug": lg.slug, "name": lg.name, "country": lg.country, "is_cup": lg.is_cup, "detail_months": lg.detail_months,
            "total": r["total"] if r else 0, "completed": (r["completed"] or 0) if r else 0,
            "summaries_ok": (r["summaries_ok"] or 0) if r else 0, "summaries_missing": (r["summaries_missing"] or 0) if r else 0,
            "with_ht": (r["with_ht"] or 0) if r else 0, "first": r["first"] if r else None,
            "last_completed": r["last_completed"] if r else None, "upcoming": (r["upcoming"] or 0) if r else 0,
            "team_stat_rows": sc["n"] if sc else 0, "shots_rows": (sc["shots"] or 0) if sc else 0,
            "corners_rows": (sc["corners"] or 0) if sc else 0, "iddaa_linked": linked.get(lg.slug, 0),
        })
    return {"leagues": out}


@app.get("/api/leagues")
def leagues() -> dict[str, Any]:
    return {"leagues": [{"slug": lg.slug, "name": lg.name, "country": lg.country, "is_cup": lg.is_cup} for lg in LEAGUES]}
