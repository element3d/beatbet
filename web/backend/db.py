import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "beatbet.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS leagues (
    league_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    country   TEXT,
    logo      TEXT,
    flag      TEXT,
    season    INTEGER,
    synced_at INTEGER
);

CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id INTEGER PRIMARY KEY,
    league_id  INTEGER NOT NULL,
    season     INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    kickoff    INTEGER NOT NULL,  -- unix timestamp
    status     TEXT NOT NULL,     -- API-Football short status: NS, 1H, HT, 2H, FT, PST, ...
    elapsed    INTEGER,
    home_id    INTEGER,
    home_name  TEXT,
    home_logo  TEXT,
    away_id    INTEGER,
    away_name  TEXT,
    away_logo  TEXT,
    home_goals INTEGER,
    away_goals INTEGER,
    updated_at INTEGER
);

-- Pre-match 1X2 odds of fixtures that get a prediction; w1/x/w2 are NULL when no bookmaker had odds
CREATE TABLE IF NOT EXISTS odds (
    fixture_id INTEGER PRIMARY KEY,
    bookmaker  TEXT,
    w1         REAL,
    x          REAL,
    w2         REAL,
    fetched_at INTEGER NOT NULL
);

-- 1xBet 1X2 odds read from Soccerway (the data files' source); match_url is NULL when the match was not
-- found there, w1/x/w2 are NULL when 1xBet had no odds. swapped: Soccerway lists the teams the other way
-- round (w1/w2 are stored already exchanged back)
CREATE TABLE IF NOT EXISTS soccerway_odds (
    fixture_id INTEGER PRIMARY KEY,
    match_url  TEXT,
    swapped    INTEGER NOT NULL DEFAULT 0,
    w1         REAL,
    x          REAL,
    w2         REAL,
    fetched_at INTEGER NOT NULL
);

-- Odds entered by hand for a prediction without bookmaker odds: which team was the favourite
-- and the odds of the pick
CREATE TABLE IF NOT EXISTS manual_odds (
    fixture_id INTEGER PRIMARY KEY,
    favourite  TEXT NOT NULL CHECK (favourite IN ('home', 'away')),
    pick_odds  REAL NOT NULL CHECK (pick_odds > 1),
    saved_at   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS fixtures_round ON fixtures (league_id, season, round, kickoff);
CREATE INDEX IF NOT EXISTS fixtures_kickoff ON fixtures (kickoff);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    # Added after the table was first made
    if "swapped" not in {r[1] for r in conn.execute("PRAGMA table_info(soccerway_odds)")}:
        conn.execute("ALTER TABLE soccerway_odds ADD COLUMN swapped INTEGER NOT NULL DEFAULT 0")
    return conn


UPSERT_FIXTURE = """
INSERT INTO fixtures (
    fixture_id, league_id, season, round, kickoff, status, elapsed,
    home_id, home_name, home_logo, away_id, away_name, away_logo, home_goals, away_goals, updated_at
) VALUES (
    :fixture_id, :league_id, :season, :round, :kickoff, :status, :elapsed,
    :home_id, :home_name, :home_logo, :away_id, :away_name, :away_logo, :home_goals, :away_goals, :updated_at
)
ON CONFLICT (fixture_id) DO UPDATE SET
    league_id = excluded.league_id, season = excluded.season, round = excluded.round,
    kickoff = excluded.kickoff, status = excluded.status, elapsed = excluded.elapsed,
    home_id = excluded.home_id, home_name = excluded.home_name, home_logo = excluded.home_logo,
    away_id = excluded.away_id, away_name = excluded.away_name, away_logo = excluded.away_logo,
    home_goals = excluded.home_goals, away_goals = excluded.away_goals, updated_at = excluded.updated_at
"""

UPSERT_LEAGUE = """
INSERT INTO leagues (league_id, name, country, logo, flag, season, synced_at)
VALUES (:league_id, :name, :country, :logo, :flag, :season, :synced_at)
ON CONFLICT (league_id) DO UPDATE SET
    name = excluded.name,
    country = COALESCE(excluded.country, leagues.country),
    logo = COALESCE(excluded.logo, leagues.logo),
    flag = COALESCE(excluded.flag, leagues.flag),
    season = excluded.season,
    synced_at = excluded.synced_at
"""

# A round's last match must kick off at least this long after the round's previous kick-off;
# otherwise the matches overlap and the round has no single last match
MIN_LAST_MATCH_GAP_SECONDS = 90 * 60

# Fixtures kicking off in [start, end] that are their round's single last match: the only match
# at the round's latest kick-off, starting at least MIN_LAST_MATCH_GAP_SECONDS after the previous one.
# Rounds whose last kick-off is shared by several matches, or comes too soon after the previous, are skipped.
SINGLE_LAST_MATCHES = f"""
WITH last AS (
    SELECT league_id, season, round, MAX(kickoff) AS kickoff
    FROM fixtures
    GROUP BY league_id, season, round
),
single AS (
    SELECT f.league_id, f.season, f.round, f.kickoff
    FROM fixtures f
    JOIN last l USING (league_id, season, round, kickoff)
    GROUP BY f.league_id, f.season, f.round
    HAVING COUNT(*) = 1
),
previous AS (
    SELECT f.league_id, f.season, f.round, MAX(f.kickoff) AS kickoff
    FROM fixtures f
    JOIN last l USING (league_id, season, round)
    WHERE f.kickoff < l.kickoff
    GROUP BY f.league_id, f.season, f.round
)
SELECT f.*, lg.name AS league_name, lg.country, lg.logo AS league_logo, lg.flag
FROM fixtures f
JOIN single s USING (league_id, season, round, kickoff)
LEFT JOIN previous p ON p.league_id = s.league_id AND p.season = s.season AND p.round = s.round
JOIN leagues lg ON lg.league_id = f.league_id
WHERE f.kickoff BETWEEN :start AND :end
  AND (p.kickoff IS NULL OR s.kickoff - p.kickoff >= {MIN_LAST_MATCH_GAP_SECONDS})
ORDER BY f.kickoff, lg.name
"""
