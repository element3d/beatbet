import json
import os
import ssl
import urllib.parse
import urllib.request

import truststore

BASE_URL = "https://v3.football.api-sports.io"
FINISHED_STATUS = "FT"
NOT_STARTED_STATUS = "NS"
MATCH_WINNER_BET_ID = 1
ONE_X_BET_BOOKMAKER_ID = 11
MARATHONBET_BOOKMAKER_ID = 2
BET365_BOOKMAKER_ID = 8
# Bookmakers to take fixture odds from, in order of preference
PREFERRED_BOOKMAKER_IDS = (ONE_X_BET_BOOKMAKER_ID, MARATHONBET_BOOKMAKER_ID, BET365_BOOKMAKER_ID)
CURRENT_SEASON = 2026
# Verify certificates with the OS trust store: Python's own store rejects the API's certificate chain
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env_file():
    """Load KEY=VALUE lines from .env into os.environ, without overriding existing variables."""
    if not os.path.exists(ENV_FILE):
        return
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


def _get(endpoint, **params):
    api_key = os.environ.get("API_FOOTBALL_KEY")
    if not api_key:
        raise RuntimeError("Set the API_FOOTBALL_KEY environment variable")

    url = f"{BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"x-apisports-key": api_key})
    with urllib.request.urlopen(request, context=SSL_CONTEXT) as response:
        data = json.load(response)

    # API-Football returns HTTP 200 even on errors, reporting them in "errors"
    if data.get("errors"):
        raise RuntimeError(f"API-Football error: {data['errors']}")
    return data


def _round_number(round_name):
    """"Regular Season - 7" or "Norra Götaland - 7" -> 7"""
    return int(round_name.rsplit(" - ", 1)[1])


def get_current_round(league_id, season):
    current = _get("fixtures/rounds", league=league_id, season=season, current="true")["response"]
    if not current:
        raise ValueError(f"No current round found for league {league_id}, season {season}")
    return _round_number(current[-1])


def get_match_winner_odds(league_id, season, bookmaker_id=ONE_X_BET_BOOKMAKER_ID):
    """Pre-match 1X2 odds keyed by fixture id, from the given bookmaker."""
    params = {
        "league": league_id,
        "season": season,
        "bet": MATCH_WINNER_BET_ID,
        "bookmaker": bookmaker_id,
    }

    odds_by_fixture = {}
    page = 1
    while True:
        data = _get("odds", page=page, **params)
        for item in data["response"]:
            if item["bookmakers"]:
                odds_by_fixture[item["fixture"]["id"]] = _parse_match_winner(item["bookmakers"][0])
        if page >= data["paging"]["total"]:
            return odds_by_fixture
        page += 1


def _parse_match_winner(bookmaker):
    values = {v["value"]: float(v["odd"]) for v in bookmaker["bets"][0]["values"]}
    return {"w1": values.get("Home"), "x": values.get("Draw"), "w2": values.get("Away")}


def get_fixture_odds(fixture_id, bookmaker_ids=PREFERRED_BOOKMAKER_IDS):
    """(bookmaker name, 1X2 odds) of one fixture from the first available bookmaker
    in bookmaker_ids, or None if none of them has odds. Uses a single request."""
    data = _get("odds", fixture=fixture_id, bet=MATCH_WINNER_BET_ID)
    available = {b["id"]: b for item in data["response"] for b in item["bookmakers"]}
    for bookmaker_id in bookmaker_ids:
        if bookmaker_id in available:
            bookmaker = available[bookmaker_id]
            return bookmaker["name"], _parse_match_winner(bookmaker)
    return None


def get_round_fixtures(league_id, round_number, season=CURRENT_SEASON):
    """All fixtures of a round, ordered by kick-off."""
    # Round names differ between leagues, so fetch the whole season and match by number
    fixtures = _get("fixtures", league=league_id, season=season)["response"]
    round_fixtures = [
        {
            "fixture_id": item["fixture"]["id"],
            "date": item["fixture"]["date"],
            "timestamp": item["fixture"]["timestamp"],
            "status": item["fixture"]["status"]["short"],
            "home": {"id": item["teams"]["home"]["id"], "name": item["teams"]["home"]["name"]},
            "away": {"id": item["teams"]["away"]["id"], "name": item["teams"]["away"]["name"]},
        }
        for item in fixtures
        if _round_number(item["league"]["round"]) == round_number
    ]
    round_fixtures.sort(key=lambda f: f["timestamp"])
    return round_fixtures


def get_last_round_fixtures(league_id, round_number, season=CURRENT_SEASON):
    """Not started fixtures sharing the round's latest kick-off time (several if they kick off together)."""
    fixtures = get_round_fixtures(league_id, round_number, season)
    if not fixtures:
        return []
    last_kickoff = fixtures[-1]["timestamp"]
    return [
        f for f in fixtures
        if f["timestamp"] == last_kickoff and f["status"] == NOT_STARTED_STATUS
    ]


def get_finished_league_matches(league_id, season=CURRENT_SEASON, bookmaker_id=ONE_X_BET_BOOKMAKER_ID):
    """Finished matches of a league from the first round to the current one, inclusive."""
    # TODO: restore after testing; only round 1 is processed to save API requests
    # current_round = get_current_round(league_id, season)
    current_round = 1
    fixtures = _get("fixtures", league=league_id, season=season, status=FINISHED_STATUS)["response"]
    odds = get_match_winner_odds(league_id, season, bookmaker_id)

    matches = []
    for item in fixtures:
        if _round_number(item["league"]["round"]) > current_round:
            continue
        fixture_id = item["fixture"]["id"]
        home, away = item["teams"]["home"], item["teams"]["away"]
        matches.append({
            "fixture_id": fixture_id,
            "round": item["league"]["round"],
            "date": item["fixture"]["date"],
            "home": {"id": home["id"], "name": home["name"]},
            "away": {"id": away["id"], "name": away["name"]},
            "odds": odds.get(fixture_id),
        })

    matches.sort(key=lambda m: m["date"])
    return matches
