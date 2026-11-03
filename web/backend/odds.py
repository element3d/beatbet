"""Pre-match 1X2 odds of single last matches, cached in the odds table.

API-Football keeps a match's odds for only about a week, so they are saved while the match is
upcoming: by the dashboard for the day being viewed, and by the sync for the whole sync window.
"""
import threading
import time

import paths  # noqa: F401  (puts the repo root on sys.path)
from db import SINGLE_LAST_MATCHES
from football_api import get_fixture_odds
from retry import with_retry

# Odds of a match not started yet are refetched when older than this
ODDS_TTL_SECONDS = 30 * 60
NOT_STARTED_STATUSES = {"NS", "TBD"}

# The dashboard polls and the sync runs in a thread; never fetch the same odds twice in parallel
odds_lock = threading.Lock()


def odds_dict(odds_row):
    """{"w1", "x", "w2"} of a cached odds row, or None when it has no complete odds."""
    if not odds_row or None in (odds_row["w1"], odds_row["x"], odds_row["w2"]):
        return None
    return {"w1": odds_row["w1"], "x": odds_row["x"], "w2": odds_row["w2"]}


def fetch_odds_if_stale(conn, fixture_id, status):
    """Fetch the fixture's odds when never fetched, or when stale before kick-off. True if fetched.

    Once the match has started, the last pre-match odds are kept.
    """
    odds_row = conn.execute("SELECT * FROM odds WHERE fixture_id = ?", (fixture_id,)).fetchone()
    if odds_row is not None:
        if status not in NOT_STARTED_STATUSES:
            return False
        if time.time() - odds_row["fetched_at"] < ODDS_TTL_SECONDS:
            return False
    result = with_retry(get_fixture_odds, fixture_id)
    now = int(time.time())
    with conn:
        if result is None and odds_dict(odds_row):
            # The bookmakers took the market down; keep the odds we had
            conn.execute("UPDATE odds SET fetched_at = ? WHERE fixture_id = ?", (now, fixture_id))
            return True
        bookmaker, odds = result if result else (None, {"w1": None, "x": None, "w2": None})
        conn.execute(
            "INSERT INTO odds (fixture_id, bookmaker, w1, x, w2, fetched_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (fixture_id) DO UPDATE SET bookmaker = excluded.bookmaker, w1 = excluded.w1, "
            "x = excluded.x, w2 = excluded.w2, fetched_at = excluded.fetched_at",
            (fixture_id, bookmaker, odds["w1"], odds["x"], odds["w2"], now),
        )
    return True


def single_last_matches(conn, start, end):
    """Rows of the single last matches kicking off in [start, end]."""
    return conn.execute(SINGLE_LAST_MATCHES, {"start": start, "end": end}).fetchall()
