from __future__ import annotations

import sqlite3

import pytest

from app.db import SCHEMA
from app.live_picks import SCHEMA as LIVE_SCHEMA
from app.live_picks import LiveState, live_joint, outcome_prob, settle_live_picks
from app.model import markets as mk


def _state(**kw) -> LiveState:
    base = dict(started=False, finished=False, period=0, halftime=False, minute=0, home=0, away=0, ht_home=None,
                ht_away=None, red_home=0, red_away=0)
    base.update(kw)
    return LiveState(**base)


def _ms1(s: LiveState) -> float:
    j, rh, ra, eh, ea = live_joint(1.5, 1.1, 0.44, 1.0, s)
    return float(j.P[mk.outcome_mask("ms", None, "1", j)].sum())


def test_live_model_matches_browser_model():
    # web/lib/live-model.ts ile aynı sayılar (tarayıcıda doğrulandı)
    assert _ms1(_state()) == pytest.approx(0.4642, abs=1e-4)
    s70 = _state(started=True, period=2, minute=70, home=1, away=0, ht_home=1, ht_away=0)
    assert _ms1(s70) == pytest.approx(0.827, abs=1e-3)
    assert _ms1(_state(started=True, period=2, minute=70, home=1, away=0, ht_home=1, ht_away=0, red_home=1)) == pytest.approx(0.765, abs=1e-3)
    j, rh, ra, eh, ea = live_joint(1.5, 1.1, 0.44, 1.0, s70)
    ng = [outcome_prob(34, "2", n, j, rh, ra, eh, ea) for n in ("1", "Olmaz", "2")]
    assert sum(ng) == pytest.approx(1.0)
    rest = [outcome_prob(23, "1:0", n, j, rh, ra, eh, ea) for n in ("1", "0", "2")]
    assert sum(rest) == pytest.approx(1.0)


def test_live_pick_settlement():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    con.execute("ALTER TABLE matches ADD COLUMN neutral INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE matches ADD COLUMN extra_time INTEGER NOT NULL DEFAULT 0")
    con.execute("ALTER TABLE matches ADD COLUMN ft90_home INTEGER")
    con.execute("ALTER TABLE matches ADD COLUMN ft90_away INTEGER")
    con.executescript(LIVE_SCHEMA)
    con.execute(
        """INSERT INTO matches(id, league, date_utc, state, completed, home_id, away_id, home_goals, away_goals,
           scoreboard_fetched_at, ft90_home, ft90_away) VALUES('m','eng.1','2026-10-15T19:00:00Z','post',1,'H','A',2,1,'x',2,1)"""
    )
    # goller: ev 10', dep 50', ev 80'
    for seq, (tid, per, minute) in enumerate([("H", 1, 10), ("A", 2, 50), ("H", 2, 80)]):
        con.execute("INSERT INTO goal_events VALUES('m',?,?,NULL,?,?,0,0)", (seq, tid, minute, per))
    picks = [
        (4, "", "1", "won"),           # maç sonucu ev
        (14, "2.5", "Üst", "won"),     # 3 gol
        (23, "1:0", "0", "won"),       # 1-0'dan sonra kalan süre 1-1
        (34, "2", "2", "won"),         # 2. golü deplasman attı
        (34, "3", "2", "lost"),        # 3. golü ev attı
        (34, "4", "Olmaz", "won"),     # 4. gol yok
    ]
    for st, sov, name, _ in picks:
        con.execute(
            """INSERT INTO live_picks(match_id, created_at, minute, score_home, score_away, red_home, red_away, st, sov,
               outcome, odd, p_model, ev) VALUES('m','t',30,1,0,0,0,?,?,?,2.0,0.5,0.0)""",
            (st, sov, name),
        )
    settle_live_picks(con)
    got = {(r["st"], r["sov"], r["outcome"]): r["status"] for r in con.execute("SELECT st, sov, outcome, status FROM live_picks")}
    for st, sov, name, want in picks:
        assert got[(st, sov, name)] == want, (st, sov, name)
