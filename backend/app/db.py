"""SQLite erişimi. Tek yazıcı (ingest/job) + çok okuyucu (API); WAL modu."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .config import DATA_DIR, DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    short_name TEXT,
    abbreviation TEXT,
    logo TEXT,
    color TEXT
);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    league TEXT NOT NULL,
    season INTEGER,
    date_utc TEXT NOT NULL,
    state TEXT NOT NULL,              -- pre | in | post
    completed INTEGER NOT NULL DEFAULT 0,
    status_detail TEXT,
    home_id TEXT NOT NULL,
    away_id TEXT NOT NULL,
    home_goals INTEGER,
    away_goals INTEGER,
    home_ht INTEGER,
    away_ht INTEGER,
    venue TEXT,
    scoreboard_fetched_at TEXT NOT NULL,
    summary_fetched_at TEXT,
    summary_status TEXT,              -- ok | missing_players | error
    lineup_confirmed INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_matches_date ON matches(date_utc);
CREATE INDEX IF NOT EXISTS ix_matches_league ON matches(league, date_utc);
CREATE INDEX IF NOT EXISTS ix_matches_home ON matches(home_id, date_utc);
CREATE INDEX IF NOT EXISTS ix_matches_away ON matches(away_id, date_utc);

CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    is_home INTEGER NOT NULL,
    shots INTEGER,
    shots_on_target INTEGER,
    corners INTEGER,
    possession REAL,
    yellow INTEGER,
    red INTEGER,
    fouls INTEGER,
    PRIMARY KEY (match_id, team_id)
);

CREATE TABLE IF NOT EXISTS players (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position TEXT
);
CREATE TABLE IF NOT EXISTS player_match (
    match_id TEXT NOT NULL,
    team_id TEXT NOT NULL,
    player_id TEXT NOT NULL,
    in_squad INTEGER NOT NULL,
    starter INTEGER NOT NULL,
    min_on INTEGER,
    min_off INTEGER,
    minutes INTEGER NOT NULL,
    minutes_quality TEXT NOT NULL,    -- exact | inferred
    position TEXT,
    pos_group TEXT,                   -- G | D | M | F
    shots INTEGER,
    shots_on_target INTEGER,
    goals INTEGER,
    assists INTEGER,
    own_goals INTEGER,
    yellow INTEGER,
    red INTEGER,
    PRIMARY KEY (match_id, player_id)
);
CREATE INDEX IF NOT EXISTS ix_pm_player ON player_match(player_id);
CREATE INDEX IF NOT EXISTS ix_pm_team ON player_match(team_id);

CREATE TABLE IF NOT EXISTS goal_events (
    match_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    team_id TEXT NOT NULL,            -- golün yazıldığı takım
    player_id TEXT,
    minute INTEGER,
    period INTEGER,
    own_goal INTEGER NOT NULL DEFAULT 0,
    penalty INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (match_id, seq)
);

CREATE TABLE IF NOT EXISTS raw_summaries (
    match_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload BLOB NOT NULL             -- zlib(json)
);

CREATE TABLE IF NOT EXISTS iddaa_competitions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country_code TEXT,
    short_name TEXT,
    icon TEXT
);
CREATE TABLE IF NOT EXISTS iddaa_events (
    id INTEGER PRIMARY KEY,
    competition_id INTEGER,
    home_name TEXT NOT NULL,
    away_name TEXT NOT NULL,
    kickoff_utc TEXT NOT NULL,
    mbs INTEGER,
    is_live INTEGER NOT NULL DEFAULT 0,
    espn_match_id TEXT,
    match_score REAL,
    last_seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_iddaa_espn ON iddaa_events(espn_match_id);
CREATE INDEX IF NOT EXISTS ix_iddaa_kickoff ON iddaa_events(kickoff_utc);

CREATE TABLE IF NOT EXISTS odds_current (
    event_id INTEGER NOT NULL,
    market_key TEXT NOT NULL,         -- t:st:sov
    outcome_no INTEGER NOT NULL,
    outcome_name TEXT NOT NULL,
    odd REAL NOT NULL,
    mbs INTEGER,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (event_id, market_key, outcome_no)
);
CREATE TABLE IF NOT EXISTS odds_history (
    event_id INTEGER NOT NULL,
    market_key TEXT NOT NULL,
    outcome_no INTEGER NOT NULL,
    odd REAL NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_odds_hist ON odds_history(event_id, market_key);

CREATE TABLE IF NOT EXISTS team_alias (
    source TEXT NOT NULL,
    alias TEXT NOT NULL,
    team_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    PRIMARY KEY (source, alias)
);

CREATE TABLE IF NOT EXISTS predictions (
    match_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    PRIMARY KEY (match_id, model_version)
);

CREATE TABLE IF NOT EXISTS coupons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    stake REAL NOT NULL,
    total_odds REAL NOT NULL,
    prob REAL NOT NULL,
    ev REAL NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | void
    settled_at TEXT
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,             -- running | ok | error
    message TEXT
);
"""

_local = threading.local()


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("matches", "neutral", "ALTER TABLE matches ADD COLUMN neutral INTEGER NOT NULL DEFAULT 0"),
    ("matches", "extra_time", "ALTER TABLE matches ADD COLUMN extra_time INTEGER NOT NULL DEFAULT 0"),
    ("matches", "ft90_home", "ALTER TABLE matches ADD COLUMN ft90_home INTEGER"),
    ("matches", "ft90_away", "ALTER TABLE matches ADD COLUMN ft90_away INTEGER"),
    ("iddaa_events", "active", "ALTER TABLE iddaa_events ADD COLUMN active INTEGER NOT NULL DEFAULT 1"),
)


def init_db() -> None:
    con = connect()
    try:
        con.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                con.execute(ddl)
    finally:
        con.close()


def get_conn() -> sqlite3.Connection:
    con: sqlite3.Connection | None = getattr(_local, "con", None)
    if con is None:
        con = connect()
        _local.con = con
    return con


@contextmanager
def tx(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
    except BaseException:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def meta_get(con: sqlite3.Connection, key: str) -> Any | None:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def meta_set(con: sqlite3.Connection, key: str, value: Any) -> None:
    con.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
