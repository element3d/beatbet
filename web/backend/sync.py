"""Copy fixtures of the tracked leagues from API-Football into SQLite.

    py -3 sync.py                      sync the window (past 2 to next 10 days): one request per tracked league,
                                       then odds of its single last matches: one request per match without fresh odds
    py -3 sync.py --date 2026-11-02    refresh one UTC day (scores, statuses), one request
"""
import argparse
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import paths  # noqa: F401  (puts the repo root on sys.path)
from db import UPSERT_FIXTURE, UPSERT_LEAGUE, connect
from football_api import get_fixture_items_on_date, get_season_fixture_items, tracked_round_number
from leagues import league_name, league_season
from odds import fetch_odds_if_stale, odds_lock, single_last_matches
from retry import with_retry
from round_stats import list_league_ids

# Fixtures kicking off before this are not stored
KEEP_FROM = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
# A league sync downloads only fixtures from this many days ago (to settle recent results)
# to this many days ahead; fixtures stored outside the window are kept as they are
SYNC_DAYS_BACK = 2
SYNC_DAYS_AHEAD = 10


def sync_window():
    """(first, last) UTC dates of the sync window, inclusive."""
    today = datetime.now(timezone.utc).date()
    return today - timedelta(days=SYNC_DAYS_BACK), today + timedelta(days=SYNC_DAYS_AHEAD)


def _log(text):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}", flush=True)


def window_range():
    """(start, end) unix timestamps of the sync window."""
    first, last = sync_window()
    start = int(datetime.combine(first, datetime.min.time(), timezone.utc).timestamp())
    end = int(datetime.combine(last + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()) - 1
    return start, end


def _fixture_row(item, league_id, now):
    """DB row of an API fixture item, or None if it is not in a numbered round of the tracked group
    or kicks off before KEEP_FROM."""
    round_number = tracked_round_number(league_id, item["league"]["round"])
    if round_number is None or item["fixture"]["timestamp"] < KEEP_FROM:
        return None
    fixture, home, away = item["fixture"], item["teams"]["home"], item["teams"]["away"]
    return {
        "fixture_id": fixture["id"],
        "league_id": league_id,
        "season": item["league"]["season"],
        "round": round_number,
        "kickoff": fixture["timestamp"],
        "status": fixture["status"]["short"],
        "elapsed": fixture["status"]["elapsed"],
        "home_id": home["id"],
        "home_name": home["name"],
        "home_logo": home.get("logo"),
        "away_id": away["id"],
        "away_name": away["name"],
        "away_logo": away.get("logo"),
        "home_goals": item["goals"]["home"],
        "away_goals": item["goals"]["away"],
        "updated_at": now,
    }


def sync_league(conn, league_id):
    """Replace the league's current season fixtures within the sync window; returns the number stored."""
    season = league_season(league_id)
    first, last = sync_window()
    items = with_retry(get_season_fixture_items, league_id, season, first.isoformat(), last.isoformat())
    now = int(time.time())
    rows = [row for row in (_fixture_row(item, league_id, now) for item in items) if row]

    info = items[0]["league"] if items else {}
    with conn:
        conn.execute(UPSERT_LEAGUE, {
            "league_id": league_id,
            "name": league_name(league_id),
            "country": info.get("country"),
            "logo": info.get("logo"),
            "flag": info.get("flag"),
            "season": season,
            "synced_at": now,
        })
        conn.executemany(UPSERT_FIXTURE, rows)
        # Drop stored fixtures of the window the API no longer lists there (rescheduled out of it,
        # or moved to an unnumbered round); they come back when a sync window includes their new date
        ids = [row["fixture_id"] for row in rows]
        window_start, window_end = window_range()
        conn.execute(
            f"DELETE FROM fixtures WHERE league_id = ? AND season = ? AND kickoff BETWEEN ? AND ? "
            f"AND fixture_id NOT IN ({','.join('?' * len(ids))})",
            [league_id, season, window_start, window_end, *ids],
        )
    return len(rows)


def refresh_date(conn, date):
    """Update the tracked leagues' fixtures on a UTC date ("YYYY-MM-DD"); returns the number updated."""
    tracked = set(list_league_ids())
    items = with_retry(get_fixture_items_on_date, date)
    now = int(time.time())
    rows = []
    for item in items:
        league_id = item["league"]["id"]
        if league_id in tracked and item["league"]["season"] == league_season(league_id):
            row = _fixture_row(item, league_id, now)
            if row:
                rows.append(row)
    with conn:
        # Only leagues already synced once, so every fixture has its league row for the dashboard
        known = {r[0] for r in conn.execute("SELECT league_id FROM leagues")}
        rows = [row for row in rows if row["league_id"] in known]
        conn.executemany(UPSERT_FIXTURE, rows)
    return len(rows)


class SyncState:
    """Progress of the full sync running in the background for the web server."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.done = 0
        self.total = 0
        self.current = None
        self.errors = []
        self.started_at = None
        self.finished_at = None

    def snapshot(self):
        with self.lock:
            return {
                "running": self.running,
                "done": self.done,
                "total": self.total,
                "current": self.current,
                "errors": list(self.errors),
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


def full_sync(state=None, log=_log):
    """Sync every tracked league, then save the odds of the window's single last matches.
    One failing league or fixture does not stop the others."""
    state = state or SyncState()
    league_ids = list_league_ids()
    with state.lock:
        state.running, state.done, state.total = True, 0, len(league_ids)
        state.errors, state.started_at, state.finished_at = [], int(time.time()), None
    conn = connect()
    try:
        for league_id in league_ids:
            with state.lock:
                state.current = league_name(league_id)
            try:
                count = sync_league(conn, league_id)
                log(f"{league_name(league_id)} ({league_id}): {count} fixtures")
            except Exception as error:
                log(f"{league_name(league_id)} ({league_id}): {error}")
                with state.lock:
                    state.errors.append(f"{league_name(league_id)}: {error}")
            with state.lock:
                state.done += 1
        _save_window_odds(conn, state, log)
    finally:
        conn.close()
        with state.lock:
            state.running, state.current, state.finished_at = False, None, int(time.time())
    return state


def _save_window_odds(conn, state, log):
    """Fetch odds of the window's single last matches that have none, or stale ones before kick-off.

    Saved while the matches are upcoming, because API-Football drops a match's odds about a week later.
    """
    rows = single_last_matches(conn, *window_range())
    with state.lock:
        state.total += len(rows)
    fetched = 0
    for row in rows:
        name = f"{row['home_name']} - {row['away_name']}"
        with state.lock:
            state.current = f"Odds: {name}"
        try:
            with odds_lock:
                fetched += fetch_odds_if_stale(conn, row["fixture_id"], row["status"])
        except Exception as error:
            log(f"Odds of {name} ({row['fixture_id']}): {error}")
            with state.lock:
                state.errors.append(f"Odds of {name}: {error}")
        with state.lock:
            state.done += 1
    log(f"Odds: {fetched} fetched for {len(rows)} single last matches")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", help="refresh only this UTC date (YYYY-MM-DD)")
    args = parser.parse_args()

    if args.date:
        conn = connect()
        try:
            _log(f"{args.date}: {refresh_date(conn, args.date)} fixtures updated")
        finally:
            conn.close()
        return

    state = full_sync()
    _log(f"Done: {state.done - len(state.errors)}/{state.total} leagues and odds synced, {len(state.errors)} failed")


if __name__ == "__main__":
    main()
