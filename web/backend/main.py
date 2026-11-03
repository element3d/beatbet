"""BeatBet dashboard API.

    .venv\\Scripts\\python -m uvicorn main:app --reload --port 8000
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import paths  # noqa: F401  (puts the repo root on sys.path)
from db import SINGLE_LAST_MATCHES, connect
from leagues import league_season
from predictions import favourite_is_home, is_safe, make_prediction
from round_stats import (
    MIN_SIDE_BY_MATCHES, is_positive, load_rounds, matches_per_round, positive_rounds_percentage,
)
from odds import fetch_odds_if_stale, odds_dict, odds_lock
from soccerway import BOOKMAKER_LABEL, fetch_soccerway_odds
from sync import SyncState, full_sync, refresh_date

# Interrupted and suspended matches are shown as "other": the API can leave them in that state for weeks
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "LIVE"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}
# A day refresh may span at most this many UTC dates (one API request each)
MAX_REFRESH_DATES = 3
# Probability = (coef * pattern fit % + bookmaker %) / 2, with coef by the pattern compared with the default
PATTERN_COEFS = {"default": 1.0, "weaker": 0.8}
# Predictions with a lower probability (%) are shown greyed out and left out of the day summary
MIN_PROBABILITY = 55
# The Refresh button reads Soccerway's odds again only for matches kicking off within this (or started);
# later ones keep the usual 30-minute refresh
FORCE_ODDS_BEFORE_KICKOFF_SECONDS = 2 * 60 * 60
# Odds are fetched for at most this long a range at once (one request per fixture)
MAX_ODDS_RANGE_SECONDS = 2 * 24 * 60 * 60
FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"

app = FastAPI(title="BeatBet")
sync_state = SyncState()


def _league_stats(league_id):
    """Matches per round, pattern minimum and positive % of a league's data file, or None without data."""
    try:
        rounds = load_rounds(league_id)
    except FileNotFoundError:
        return None
    if not rounds:
        return None
    matches = matches_per_round(rounds)
    min_side = MIN_SIDE_BY_MATCHES.get(matches)
    # Like positive_rounds_count: every round but an unfinished latest one
    latest = max(rounds)
    finished = [split for number, split in rounds.items() if number != latest or sum(split) == matches]
    patterns = _patterns(finished, matches, min_side) if min_side else []
    return {
        "rounds": rounds,
        "matches": matches,
        "min_side": min_side,
        "positive_pct": positive_rounds_percentage(league_id) if min_side else None,
        "patterns": patterns,
    }


def round_status(stats, round_number):
    """How the round stands in data/<league>.txt: its split, what is left and whether it fits the pattern."""
    if not stats or not stats["min_side"]:
        return None
    matches, min_side = stats["matches"], stats["min_side"]
    split = stats["rounds"].get(round_number)
    base = {
        "matches": matches,
        "min_side": min_side,
        "league_positive_pct": stats["positive_pct"],
        # Each pattern, with whether this round's split so far already fits it (None without round data)
        "patterns": [
            {**p, "round_fits": None if split is None else is_positive(split, matches, p["min_side"])}
            for p in stats["patterns"]
        ],
    }
    if split is None:
        return {**base, "state": "no_data"}

    wins, not_wins = split
    remaining = max(matches - wins - not_wins, 0)
    missing = max(min_side - min(wins, not_wins), 0)
    if is_positive(split, matches):
        state = "positive"
    elif remaining == 0:
        state = "negative"
    elif missing > remaining:
        state = "out_of_reach"
    else:
        state = "open"
    return {
        **base,
        "state": state,
        "wins": wins,
        "not_wins": not_wins,
        "remaining": remaining,
        "missing": missing,
        # The side the round is short of, None when the round already fits or both sides are short equally
        "short_side": None if missing == 0 or wins == not_wins else ("wins" if wins < not_wins else "not_wins"),
    }


def _phase(status):
    if status in LIVE_STATUSES:
        return "live"
    if status in FINISHED_STATUSES:
        return "finished"
    if status in {"NS", "TBD"}:
        return "upcoming"
    return "other"  # postponed, cancelled, abandoned, ...


def _patterns(splits, matches, default_side):
    """Every pattern from "1 n-1 .. n-1 1" up to the most balanced one, with how many of splits fit it."""
    total = len(splits)
    patterns = []
    for side in range(1, matches // 2 + 1):
        positive = sum(1 for split in splits if is_positive(split, matches, side))
        patterns.append({
            "min_side": side,
            "text": f"{side} {matches - side} .. {matches - side} {side}",
            "positive": positive,
            "total": total,
            "pct": positive / total * 100 if total else 0.0,
            "default": side == default_side,
        })
    return patterns


def _strength(min_side, default_side):
    """The pattern compared with the league's default: a lower minimum is weaker, a higher one stronger."""
    if min_side == default_side:
        return "default"
    return "weaker" if min_side < default_side else "stronger"


def _decider(split, patterns):
    """The pattern a round's last match decides from split (fav wins, fav not wins) of its other matches.

    With a short side of s, patterns up to s already fit whatever happens, patterns above s + 1
    are out of reach, and pattern s + 1 fits exactly when the last match goes to the short side.
    None when the sides are equal (no short side to pick).
    """
    wins, not_wins = split
    if wins == not_wins:
        return None
    side = min(wins, not_wins) + 1
    return next((p for p in patterns if p["min_side"] == side), None)


def _favourite_is_home(odds, manual_row):
    """True / False when the favourite is known (entered by hand, else from the odds), otherwise None."""
    if manual_row:
        return manual_row["favourite"] == "home"
    if odds:
        return favourite_is_home(odds)
    return None


def _fav_won(row, fav_home):
    """Whether the favourite won the finished match, or None without a favourite or final score."""
    if fav_home is None or _phase(row["status"]) != "finished":
        return None
    if row["home_goals"] is None or row["away_goals"] is None:
        return None
    if fav_home:
        return row["home_goals"] > row["away_goals"]
    return row["away_goals"] > row["home_goals"]


def _rebuild_candidate(row, status):
    """The round is complete in the data and this match has a final score, so a prediction can be
    rebuilt once the favourite is known."""
    return (
        status is not None and status["state"] != "no_data" and status["remaining"] == 0
        and _phase(row["status"]) == "finished" and row["home_goals"] is not None and row["away_goals"] is not None
    )


def _prediction_input(row, stats, status, fav_home):
    """(split before the match, patterns, reconstructed) for a last match that gets a prediction, or None.

    Live: the round's data has every match but this one. Reconstructed: the round is complete in the
    data and this match has finished with a known favourite, so its result is taken back out of the
    final split; its patterns then count only earlier rounds, as known before the match.
    """
    if not status or status["state"] == "no_data":
        return None
    split = (status["wins"], status["not_wins"])
    if status["remaining"] == 1:
        return split, stats["patterns"], False
    if status["remaining"] != 0:
        return None
    fav_won = _fav_won(row, fav_home)
    if fav_won is None:
        return None
    wins, not_wins = split
    before = (wins - 1, not_wins) if fav_won else (wins, not_wins - 1)
    if min(before) < 0:
        return None  # the data disagrees with the result (e.g. a different favourite)
    earlier = [s for number, s in stats["rounds"].items() if number < row["round"]]
    return before, _patterns(earlier, stats["matches"], stats["min_side"]), True


def _pick(pick_fav_wins, fav_home, home, away):
    """(code, label) of the pick, as make_prediction names them."""
    fav, dog = (home, away) if fav_home else (away, home)
    if pick_fav_wins:
        return ("W1" if fav_home else "W2"), f"{fav} wins"
    return ("X2" if fav_home else "1X"), f"{dog} doesn't lose"


def _predicted_pattern(split, patterns, default_side):
    """The pattern decided from split, or None when there is none or it is stricter than the
    league's default (risky patterns get no prediction)."""
    pattern = _decider(split, patterns)
    if not pattern or _strength(pattern["min_side"], default_side) == "stronger":
        return None
    return pattern


def _risky(split, patterns, default_side):
    """Marker for a last match whose decided pattern is stricter than the league's default:
    shown as risky, without a prediction. None otherwise."""
    pattern = _decider(split, patterns)
    if not pattern or _strength(pattern["min_side"], default_side) != "stronger":
        return None
    return {
        "risky": True,
        "pending_rebuild": False,
        "pattern": {k: pattern[k] for k in ("min_side", "text", "pct", "positive", "total")},
    }


def _manual_options(row, stats, status):
    """{"home"/"away": {"code", "label"}}: the pick if that team is the favourite, for entering odds by hand.
    A side is missing when that favourite gives no prediction."""
    options = {}
    for side, fav_home in (("home", True), ("away", False)):
        given = _prediction_input(row, stats, status, fav_home)
        if given and _predicted_pattern(given[0], given[1], stats["min_side"]):
            wins, not_wins = given[0]
            code, label = _pick(wins < not_wins, fav_home, row["home_name"], row["away_name"])
            options[side] = {"code": code, "label": label}
    return options


def _choose_odds(odds_row, soccerway_row):
    """(odds, source, bookmaker, fetched_at, check) of the odds a prediction uses.

    Soccerway's 1xBet odds when there are some (the data files' favourites come from them), else
    API-Football's. check tells the card what to warn about: the API odds naming another favourite,
    or no Soccerway odds to confirm the API ones.
    """
    api, soccerway = odds_dict(odds_row), odds_dict(soccerway_row)
    check = {
        "soccerway_url": soccerway_row["match_url"] if soccerway_row else None,
        "soccerway_found": bool(soccerway_row and soccerway_row["match_url"]),
        "api_market": api,
        "favourite_conflict": bool(api and soccerway and favourite_is_home(api) != favourite_is_home(soccerway)),
    }
    if soccerway:
        return soccerway, "soccerway", BOOKMAKER_LABEL, soccerway_row["fetched_at"], check
    if api:
        return api, "api", odds_row["bookmaker"], odds_row["fetched_at"], check
    fetched = [r["fetched_at"] for r in (odds_row, soccerway_row) if r]
    return None, None, None, max(fetched) if fetched else None, check


def build_prediction(row, stats, status, odds_row, manual_row=None, soccerway_row=None):
    """Prediction for a decided last match, or None.

    Odds entered by hand take precedence over the bookmakers' ones, and Soccerway's 1xBet odds over
    API-Football's. Without any odds the prediction has only the pattern and pick side and asks for
    them ("needs_manual"); a complete round without a known favourite cannot even be rebuilt yet
    ("pending_rebuild").
    """
    odds, source, bookmaker, odds_fetched_at, check = _choose_odds(odds_row, soccerway_row)
    fav_home = _favourite_is_home(odds, manual_row)
    given = _prediction_input(row, stats, status, fav_home)
    if not given:
        if fav_home is None and _rebuild_candidate(row, status):
            # The pick for each possible favourite; none at all means no prediction either way
            options = _manual_options(row, stats, status)
            if options:
                return {"risky": False, "pending_rebuild": True, "needs_manual": True, "has_odds": False, "options": options}
            # Risky whichever team was the favourite
            for fav in (True, False):
                guess = _prediction_input(row, stats, status, fav)
                marker = guess and _risky(guess[0], guess[1], stats["min_side"])
                if marker:
                    return marker
        return None
    split, patterns, reconstructed = given
    pattern = _predicted_pattern(split, patterns, stats["min_side"])
    if not pattern:
        return _risky(split, patterns, stats["min_side"])
    wins, not_wins = split
    pick_fav_wins = wins < not_wins
    strength = _strength(pattern["min_side"], stats["min_side"])
    coef = PATTERN_COEFS[strength]
    fav_won = _fav_won(row, fav_home)
    base = {
        "risky": False,
        "pending_rebuild": False,
        "pattern": {k: pattern[k] for k in ("min_side", "text", "pct", "positive", "total")},
        "strength": strength,
        "pick_fav_wins": pick_fav_wins,
        "before": {"wins": wins, "not_wins": not_wins},
        "reconstructed": reconstructed,
        "odds_fetched_at": odds_fetched_at,
        "result": None if fav_won is None else ("won" if fav_won == pick_fav_wins else "lost"),
        "odds_check": check,
    }

    if manual_row:
        code, label = _pick(pick_fav_wins, fav_home, row["home_name"], row["away_name"])
        # 1 / odds still holds the bookmaker's margin: without the 1X2 odds it cannot be removed
        bookmaker_probability = 100 / manual_row["pick_odds"]
        return {
            **base,
            "has_odds": True,
            "needs_manual": False,
            "odds_source": "manual",
            "code": code,
            "label": label,
            "odds": manual_row["pick_odds"],
            "bookmaker_probability": bookmaker_probability,
            "pattern_coef": coef,
            "probability": (coef * pattern["pct"] + bookmaker_probability) / 2,
            "bookmaker": None,
            "market": None,
            "favourite": "home" if fav_home else "away",
            "safe": None,
        }
    if not odds:
        return {**base, "has_odds": False, "needs_manual": True, "options": _manual_options(row, stats, status)}

    p = make_prediction(split, stats["matches"], odds, pattern["pct"], row["home_name"], row["away_name"], pattern["min_side"])
    # Mean of the bookmaker's chance and the pattern's fit %, the latter weighted by the pattern's strength
    bookmaker_probability = p["implied"] * 100
    return {
        **base,
        "has_odds": True,
        "needs_manual": False,
        "odds_source": source,
        "code": p["code"],
        "label": p["label"],
        "odds": round(p["odds"], 2),
        "bookmaker_probability": bookmaker_probability,
        "pattern_coef": coef,
        "probability": (coef * pattern["pct"] + bookmaker_probability) / 2,
        "bookmaker": bookmaker,
        "market": odds,
        "favourite": "home" if fav_home else "away",
        "safe": is_safe(odds),
    }


def _match_items(start, end):
    """Single last matches kicking off in [start, end] with round status and prediction."""
    conn = connect()
    try:
        rows = conn.execute(SINGLE_LAST_MATCHES, {"start": start, "end": end}).fetchall()
        ids = [row["fixture_id"] for row in rows]
        marks = ",".join("?" * len(ids))
        odds_rows = {r["fixture_id"]: r for r in conn.execute(f"SELECT * FROM odds WHERE fixture_id IN ({marks})", ids)}
        manual_rows = {
            r["fixture_id"]: r for r in conn.execute(f"SELECT * FROM manual_odds WHERE fixture_id IN ({marks})", ids)
        }
        soccerway_rows = {
            r["fixture_id"]: r for r in conn.execute(f"SELECT * FROM soccerway_odds WHERE fixture_id IN ({marks})", ids)
        }
    finally:
        conn.close()

    stats_cache = {}
    items = []
    for row in rows:
        league_id = row["league_id"]
        if league_id not in stats_cache:
            stats_cache[league_id] = _league_stats(league_id)
        stats = stats_cache[league_id]
        # The data files describe the league's current season only
        status = round_status(stats, row["round"]) if row["season"] == league_season(league_id) else None
        fixture_id = row["fixture_id"]
        prediction = (
            build_prediction(
                row, stats, status, odds_rows.get(fixture_id), manual_rows.get(fixture_id), soccerway_rows.get(fixture_id)
            )
            if status else None
        )
        items.append((row, status, prediction))
    return items


class ManualOdds(BaseModel):
    favourite: Literal["home", "away"]
    odds: float = Field(gt=1, le=1000)


@app.put("/api/manual-odds/{fixture_id}")
def save_manual_odds(fixture_id: int, body: ManualOdds):
    """Save the favourite and pick odds entered by hand for a prediction without bookmaker odds."""
    conn = connect()
    try:
        if not conn.execute("SELECT 1 FROM fixtures WHERE fixture_id = ?", (fixture_id,)).fetchone():
            raise HTTPException(404, "unknown fixture")
        with conn:
            conn.execute(
                "INSERT INTO manual_odds (fixture_id, favourite, pick_odds, saved_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT (fixture_id) DO UPDATE SET favourite = excluded.favourite, "
                "pick_odds = excluded.pick_odds, saved_at = excluded.saved_at",
                (fixture_id, body.favourite, round(body.odds, 2), int(time.time())),
            )
    finally:
        conn.close()
    return {"saved": True}


@app.delete("/api/manual-odds/{fixture_id}")
def delete_manual_odds(fixture_id: int):
    conn = connect()
    try:
        with conn:
            deleted = conn.execute("DELETE FROM manual_odds WHERE fixture_id = ?", (fixture_id,)).rowcount
    finally:
        conn.close()
    return {"deleted": bool(deleted)}


def _shown_prediction(prediction):
    """The prediction as the dashboard gets it: marked low_probability below MIN_PROBABILITY
    (shown greyed out, not counted in the day summary)."""
    if prediction and prediction.get("probability") is not None:
        return {**prediction, "low_probability": prediction["probability"] < MIN_PROBABILITY}
    return prediction


def _is_shown(row, prediction):
    """Whether the dashboard lists the match: finished ones only with a non-risky prediction of at
    least MIN_PROBABILITY."""
    prediction = _shown_prediction(prediction)
    return not (
        _phase(row["status"]) == "finished"
        and (not prediction or prediction.get("risky") or prediction.get("low_probability"))
    )


@app.post("/api/odds")
def fetch_odds(start: int = Query(...), end: int = Query(...), force: bool = False):
    """Fetch odds of last matches in [start, end] that have none or stale ones (one API request per
    fixture): decided last matches (refreshed every 30 minutes until kick-off), and matches already
    played that were never fetched, so a complete round's prediction can be rebuilt from them.

    force (the Refresh button): also read Soccerway's odds again, however fresh, for every match the
    dashboard shows that kicks off within FORCE_ODDS_BEFORE_KICKOFF_SECONDS or has started (not when
    its closing odds are already saved); API-Football's keep their 30 minutes, to spare requests.
    """
    if end - start > MAX_ODDS_RANGE_SECONDS:
        raise HTTPException(400, "range too long; fetch odds one day at a time")
    now = time.time()
    fetched, errors, soccerway_jobs = 0, [], []
    with odds_lock:
        conn = connect()
        try:
            for row, status, prediction in _match_items(start, end):
                played = _phase(row["status"]) == "finished"
                complete = status is not None and status["state"] != "no_data" and status["remaining"] == 0
                wanted = not (prediction and prediction.get("risky")) and (prediction or (played and complete))
                forced = force and _is_shown(row, prediction) and row["kickoff"] <= now + FORCE_ODDS_BEFORE_KICKOFF_SECONDS
                if wanted:
                    try:
                        fetched += fetch_odds_if_stale(conn, row["fixture_id"], row["status"])
                    except Exception as error:  # one failing fixture must not stop the others
                        errors.append(f"{row['home_name']} - {row['away_name']}: {error}")
                if wanted or forced:
                    soccerway_jobs.append((row, forced))
        finally:
            conn.close()
        read, soccerway_errors = fetch_soccerway_odds(soccerway_jobs, connect)
    return {"fetched": fetched + read, "errors": errors + soccerway_errors}


@app.get("/api/last-matches")
def last_matches(start: int = Query(..., description="unix timestamp"), end: int = Query(...)):
    """Single last matches of rounds kicking off in [start, end]."""
    if end < start:
        raise HTTPException(400, "end must not be before start")
    result = []
    for row, status, prediction in _match_items(start, end):
        prediction = _shown_prediction(prediction)
        league_id = row["league_id"]
        result.append({
            "fixture_id": row["fixture_id"],
            "kickoff": row["kickoff"],
            "status": row["status"],
            "phase": _phase(row["status"]),
            "elapsed": row["elapsed"],
            "round": row["round"],
            "league": {
                "id": league_id,
                "name": row["league_name"],
                "country": row["country"],
                "logo": row["league_logo"],
                "flag": row["flag"],
            },
            "home": {"id": row["home_id"], "name": row["home_name"], "logo": row["home_logo"], "goals": row["home_goals"]},
            "away": {"id": row["away_id"], "name": row["away_name"], "logo": row["away_logo"], "goals": row["away_goals"]},
            "round_status": status,
            "prediction": prediction,
        })
    return result


@app.get("/api/meta")
def meta():
    conn = connect()
    try:
        leagues = conn.execute("SELECT COUNT(*), MAX(synced_at) FROM leagues").fetchone()
        fixtures = conn.execute("SELECT COUNT(*) FROM fixtures").fetchone()[0]
    finally:
        conn.close()
    return {
        "leagues": leagues[0],
        "last_synced_at": leagues[1],
        "fixtures": fixtures,
        "sync": sync_state.snapshot(),
    }


@app.post("/api/sync")
def start_sync():
    """Start syncing the window in the background (one API request per tracked league)."""
    if sync_state.snapshot()["running"]:
        raise HTTPException(409, "A sync is already running")
    threading.Thread(target=full_sync, args=(sync_state,), daemon=True).start()
    return sync_state.snapshot()


@app.get("/api/sync")
def sync_status():
    return sync_state.snapshot()


@app.post("/api/refresh")
def refresh(start: int = Query(...), end: int = Query(...)):
    """Refresh scores and statuses of the UTC dates covering [start, end] (one API request per date)."""
    first = datetime.fromtimestamp(start, timezone.utc).date()
    last = datetime.fromtimestamp(end, timezone.utc).date()
    days = (last - first).days + 1
    if not 1 <= days <= MAX_REFRESH_DATES:
        raise HTTPException(400, f"range must span 1..{MAX_REFRESH_DATES} UTC dates")
    conn = connect()
    try:
        updated = sum(refresh_date(conn, (first + timedelta(days=i)).isoformat()) for i in range(days))
    except RuntimeError as error:
        raise HTTPException(502, str(error))
    finally:
        conn.close()
    return {"updated": updated}


# Serve the built frontend when it exists (npm run build); in development Vite serves it instead
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        file = FRONTEND_DIST / path
        if path and file.is_file() and FRONTEND_DIST in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(FRONTEND_DIST / "index.html")
