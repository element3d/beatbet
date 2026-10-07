import json
import os
import time
from datetime import datetime, timezone

from football_api import NOT_STARTED_STATUS, get_fixture_odds, get_round_fixtures
from leagues import league_name
from predictions import PATTERN_WEIGHT, PENALTY_PER_EXTRA_MATCH, favourite_odds, is_safe, make_prediction
from round_stats import (
    current_round, is_positive, list_league_ids, load_rounds, matches_per_round, positive_rounds_percentage,
)
from telegram import send_message

POSTED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted.json")
CHECK_INTERVAL_SECONDS = 60
# A waiting league's fixture and odds are refreshed hourly while kick-off is far or unknown,
# every 10 minutes on match day, and on every check from shortly before kick-off
FAR_REFRESH_SECONDS = 60 * 60
REFRESH_SECONDS = 10 * 60
FAR_KICKOFF_SECONDS = 6 * 60 * 60
NEAR_KICKOFF_SECONDS = 15 * 60
# Safe matches are posted from this long before kick-off
SAFE_POST_SECONDS = 3 * 60 * 60
# Dangerous matches are posted from this match minute, and no match is posted after the late limit
POST_FROM_MINUTE = 3
LATE_LIMIT_MINUTE = 10
FIRST_HALF_STATUS = "1H"
# Statuses of a match that is over or will not be played as scheduled
DONE_STATUSES = {"FT", "AET", "PEN", "PST", "CANC", "ABD", "AWD", "WO"}


def _log(text):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}", flush=True)


def _load_posted():
    if not os.path.exists(POSTED_FILE):
        return set()
    with open(POSTED_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def _save_posted(posted):
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(posted), f)


def _pending_round(league_id):
    """(round number, split, matches per round) when the data shows exactly one match left
    in the current round and that round does not fit the pattern yet, otherwise None."""
    current = current_round(league_id)
    if not current:
        return None
    number, split = current
    matches = matches_per_round(load_rounds(league_id))
    if matches - sum(split) != 1 or is_positive(split, matches):
        return None
    return number, split, matches


def _last_fixture(league_id, round_number):
    """The round's only fixture that is not over, or None if there is not exactly one."""
    remaining = [
        f for f in get_round_fixtures(league_id, round_number)
        if f["status"] not in DONE_STATUSES
    ]
    return remaining[0] if len(remaining) == 1 else None


def _refresh_interval(fixture):
    """Seconds between API refreshes of a waiting league, depending on how close kick-off is."""
    if not fixture:
        return FAR_REFRESH_SECONDS
    until_kickoff = fixture["timestamp"] - time.time()
    if until_kickoff > FAR_KICKOFF_SECONDS:
        return FAR_REFRESH_SECONDS
    if until_kickoff > NEAR_KICKOFF_SECONDS:
        return REFRESH_SECONDS
    return 0


def _odds_label(key):
    return {"w1": "W1", "x": "X", "w2": "W2"}[key]


def format_breakdown(prediction, odds, bookmaker):
    """Every step of the confidence calculation, so each number of the post can be checked."""
    p = prediction
    probabilities = p["probabilities"]
    total = 1 + p["margin"]
    raw = " + ".join(f"{probabilities[key] * total * 100:.1f}%" for key in ("w1", "x", "w2"))
    fair = " · ".join(f"{_odds_label(key)} {probabilities[key] * 100:.1f}%" for key in ("w1", "x", "w2"))

    if p["pick_fav_wins"]:
        pick_line = f"Pick {p['code']} = {p['implied'] * 100:.1f}%"
    else:
        draw, dog = probabilities["x"], probabilities[p["dog_key"]]
        pick_line = (
            f"Pick {p['code']} = X {draw * 100:.1f}% + {_odds_label(p['dog_key'])} {dog * 100:.1f}% "
            f"= {p['implied'] * 100:.1f}%\n"
            f"   Fair {p['code']} odds = 1 / (1/{odds['x']:.2f} + 1/{odds[p['dog_key']]:.2f}) = {p['odds']:.2f}"
        )

    short_side = "fav wins" if p["pick_fav_wins"] else "fav not wins"
    if p["missing"] == 1:
        penalty_line = "   Missing 1 → last match can complete the pattern → ×1"
    else:
        penalty_line = (
            f"   Missing {p['missing']} → ⚠️ pattern can't be completed this round → "
            f"×{PENALTY_PER_EXTRA_MATCH}^{p['missing'] - 1} = ×{p['penalty']:g}"
        )

    weight = PATTERN_WEIGHT
    pattern_part = weight * p["pattern_chance"]
    bookmaker_part = (1 - weight) * p["implied"] * 100
    return (
        f"📐 How the confidence is calculated\n"
        f"1) Pattern chance\n"
        f"   League fits pattern in {p['pattern_percentage']:.1f}% of rounds (both sides ≥ {p['min_side']})\n"
        f"   Short side: {short_side}, needs {p['missing']} more to reach {p['min_side']}\n"
        f"{penalty_line}\n"
        f"   = {p['pattern_percentage']:.1f}% × {p['penalty']:g} = {p['pattern_chance']:.1f}%\n"
        f"2) Bookmaker chance ({bookmaker} {odds['w1']:.2f} / {odds['x']:.2f} / {odds['w2']:.2f})\n"
        f"   1/odds = {raw} = {total * 100:.1f}% (margin {p['margin'] * 100:.1f}%)\n"
        f"   Without margin (÷ {total:.3f}): {fair}\n"
        f"   {pick_line}\n"
        f"3) Confidence = {weight:g} × {p['pattern_chance']:.1f}% + {1 - weight:g} × {p['implied'] * 100:.1f}%\n"
        f"   = {pattern_part:.1f} + {bookmaker_part:.1f} = {p['confidence']:.1f}%"
    )


def format_post(league_id, round_number, split, fixture, prediction, odds, bookmaker):
    wins, not_wins = split
    kickoff = datetime.fromtimestamp(fixture["timestamp"], timezone.utc)
    if fixture["status"] == NOT_STARTED_STATUS:
        when = f"🕒 Kick-off {kickoff:%d.%m %H:%M} UTC"
    else:
        when = f"🔴 Live, minute {fixture['elapsed']} (odds from before kick-off)"
    return (
        f"⚽ {league_name(league_id)} · Round {round_number} (last match)\n"
        f"{fixture['home']['name']} vs {fixture['away']['name']}\n"
        f"{when}\n\n"
        f"Round so far: {wins} fav wins · {not_wins} fav not wins\n\n"
        f"✅ Pick: {prediction['label']} ({prediction['code']}) @ {prediction['odds']:.2f}\n"
        f"📊 Confidence: {prediction['confidence']:.1f}%\n\n"
        f"{format_breakdown(prediction, odds, bookmaker)}"
    )


class Tracker:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.posted = set() if dry_run else _load_posted()
        # league id -> {"round", "split", "matches", "fixture", "odds", "bookmaker", "refreshed"}
        # of leagues waiting for their last match
        self.waiting = {}
        self._last_upcoming = None

    def check_all(self):
        for league_id in list_league_ids():
            try:
                self.check_league(league_id)
            except Exception as error:  # one failing league must not stop the loop
                _log(f"{league_name(league_id)} ({league_id}): {error}")

    def check_league(self, league_id):
        pending = _pending_round(league_id)
        if not pending:
            self.waiting.pop(league_id, None)
            return
        number, split, matches = pending

        state = self.waiting.get(league_id)
        if not state or state["round"] != number:
            state = self.waiting[league_id] = {
                "round": number, "split": split, "matches": matches,
                "fixture": None, "odds": None, "bookmaker": None, "refreshed": 0,
            }
        if not self._refresh(league_id, state):
            return

        fixture = state["fixture"]
        if fixture["fixture_id"] in self.posted:
            return
        odds = state["odds"]
        if not odds or None in odds.values():
            return

        pattern_percentage = positive_rounds_percentage(league_id)
        prediction = make_prediction(
            split, matches, odds, pattern_percentage, fixture["home"]["name"], fixture["away"]["name"]
        )
        text = format_post(league_id, number, split, fixture, prediction, odds, state["bookmaker"])

        if fixture["status"] == NOT_STARTED_STATUS:
            if not is_safe(odds):
                # Dangerous: the favourite may switch, so wait for the match to start
                if self.dry_run:
                    print(f"(waiting, fav odds {favourite_odds(odds)}: posts at minute {POST_FROM_MINUTE})\n{text}\n")
                return
            if fixture["timestamp"] - time.time() > SAFE_POST_SECONDS:
                # Odds can still move a lot, so judge the favourite only shortly before kick-off
                if self.dry_run:
                    print(f"(waiting, fav odds {favourite_odds(odds)}: safe posts start 3h before kick-off)\n{text}\n")
                return
        elif fixture["status"] == FIRST_HALF_STATUS:
            elapsed = fixture["elapsed"] or 0
            if elapsed < POST_FROM_MINUTE:
                return
            if elapsed > LATE_LIMIT_MINUTE:
                _log(f"{league_name(league_id)}: too late to post fixture {fixture['fixture_id']} (minute {elapsed})")
                self._mark_posted(fixture["fixture_id"])
                return
        else:
            return

        if self.dry_run:
            print(f"(would post now)\n{text}\n")
            return
        send_message(text)
        self._mark_posted(fixture["fixture_id"])
        _log(f"Posted fixture {fixture['fixture_id']} (fav odds {favourite_odds(odds)})")

    def _refresh(self, league_id, state):
        """Update the waiting league's fixture and pre-match odds when due.

        False if there is no fixture or it is already posted, so nothing is left to do.
        """
        fixture = state["fixture"]
        if fixture and fixture["fixture_id"] in self.posted:
            return False
        if time.time() - state["refreshed"] < _refresh_interval(fixture):
            return fixture is not None

        fixture = state["fixture"] = _last_fixture(league_id, state["round"])
        state["refreshed"] = time.time()
        if not fixture:
            return False
        # Keep the last pre-match odds once the match starts; fetch them late only if never fetched
        if fixture["status"] == NOT_STARTED_STATUS or not state["odds"]:
            result = get_fixture_odds(fixture["fixture_id"])
            if result:
                state["bookmaker"], state["odds"] = result
        return True

    def _mark_posted(self, fixture_id):
        self.posted.add(fixture_id)
        if not self.dry_run:
            _save_posted(self.posted)

    def upcoming_lines(self):
        """One line per waiting, not yet posted last match, ordered by kick-off (local time)."""
        rows = []
        for league_id, state in self.waiting.items():
            fixture = state["fixture"]
            if not fixture or fixture["fixture_id"] in self.posted:
                continue
            wins, not_wins = state["split"]
            odds = state["odds"]
            if not odds or None in odds.values():
                plan = "no odds yet"
            else:
                prediction = make_prediction(
                    state["split"], state["matches"], odds, positive_rounds_percentage(league_id),
                    fixture["home"]["name"], fixture["away"]["name"],
                )
                when = "posts 3h before" if is_safe(odds) else f"dangerous, posts at minute {POST_FROM_MINUTE}"
                plan = (
                    f"{prediction['code']} @ {prediction['odds']:.2f}, {prediction['confidence']:.0f}% "
                    f"(fav {favourite_odds(odds):.2f}, {when})"
                )
            kickoff = datetime.fromtimestamp(fixture["timestamp"])
            rows.append((fixture["timestamp"], (
                f"  {kickoff:%a %d.%m %H:%M}  {league_name(league_id)} r{state['round']} ({wins} {not_wins})  "
                f"{fixture['home']['name']} vs {fixture['away']['name']}  -> {plan}"
            )))
        return [line for _, line in sorted(rows)]

    def print_upcoming(self, only_if_changed=False):
        lines = self.upcoming_lines()
        if only_if_changed and lines == self._last_upcoming:
            return
        self._last_upcoming = lines
        if lines:
            _log(f"Upcoming last matches ({len(lines)}):\n" + "\n".join(lines))
        else:
            _log("No upcoming last matches")


def run(dry_run=False):
    """Check all leagues in a loop and post predictions; with dry_run, check once and print them."""
    tracker = Tracker(dry_run)
    if dry_run:
        tracker.check_all()
        tracker.print_upcoming()
        return
    _log(f"Tracking {len(list_league_ids())} leagues, checking every {CHECK_INTERVAL_SECONDS}s")
    while True:
        tracker.check_all()
        tracker.print_upcoming(only_if_changed=True)
        time.sleep(CHECK_INTERVAL_SECONDS)
