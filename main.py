import sys

from football_api import get_fixture_odds, get_last_round_fixtures
from leagues import find_leagues, league_name
from round_stats import current_round, list_league_ids, positive_rounds_count, positive_rounds_percentage

# The round's last matches are printed only when at most this many kick off at the last time
MAX_LAST_MATCHES = 2


def print_last_matches(league_id, round_number):
    last_fixtures = get_last_round_fixtures(league_id, round_number)
    if len(last_fixtures) > MAX_LAST_MATCHES:
        return
    for fixture in last_fixtures:
        result = get_fixture_odds(fixture["fixture_id"])
        if result:
            bookmaker, odds = result
            odds_text = f"{odds['w1']} {odds['x']} {odds['w2']} ({bookmaker})"
        else:
            odds_text = "no odds"
        print(
            f"        [fixture {fixture['fixture_id']}] "
            f"{fixture['home']['name']} vs {fixture['away']['name']}  {odds_text}"
        )


def print_league_stats(league_id, with_last_matches):
    positive, total = positive_rounds_count(league_id)
    percentage = positive_rounds_percentage(league_id)
    print(
        f"{league_name(league_id)} ({league_id}): {positive} positive, {total - positive} negative, "
        f"{total} total ({percentage:.2f}% fit the pattern)"
    )
    current = current_round(league_id)
    if current:
        number, (wins, not_wins) = current
        print(f"    current round r{number}: {wins} {not_wins}")
        if with_last_matches:
            print_last_matches(league_id, number)


def main():
    league_ids = list_league_ids()
    # Last matches and their odds cost API requests, so they are fetched only for a searched league
    league_searched = len(sys.argv) > 1

    if league_searched:
        query = " ".join(sys.argv[1:])
        league_ids = find_leagues(query, league_ids)
        if not league_ids:
            print(f'No league found for "{query}". Available leagues:')
            for league_id in list_league_ids():
                print(f"    {league_name(league_id)} ({league_id})")
            sys.exit(1)

    for league_id in sorted(league_ids, key=positive_rounds_percentage, reverse=True):
        print_league_stats(league_id, with_last_matches=league_searched)
        print()


if __name__ == "__main__":
    main()
