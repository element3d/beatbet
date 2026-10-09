import sys

from football_api import get_fixture_odds, get_last_round_fixtures
from leagues import find_leagues, league_name
from round_stats import (
    current_round, list_league_ids, load_rounds, matches_per_round, positive_rounds_count, positive_rounds_percentage,
)

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


def pattern_text(league_id, min_side):
    """E.g. 10 matches with min_side 3: "3 7 .. 7 3"."""
    matches = matches_per_round(load_rounds(league_id))
    return f"{min_side} {matches - min_side} .. {matches - min_side} {min_side}"


def print_league_stats(league_id, with_last_matches, min_side=None):
    positive, total = positive_rounds_count(league_id, min_side)
    percentage = positive_rounds_percentage(league_id, min_side)
    pattern = f" {pattern_text(league_id, min_side)}" if min_side is not None else ""
    print(
        f"{league_name(league_id)} ({league_id}): {positive} positive, {total - positive} negative, "
        f"{total} total ({percentage:.2f}% fit the pattern{pattern})"
    )
    current = current_round(league_id)
    if current:
        number, (wins, not_wins) = current
        print(f"    current round r{number}: {wins} {not_wins}")
        if with_last_matches:
            print_last_matches(league_id, number)


def main():
    # Windows consoles default to a legacy encoding that cannot print names like "Horní Ředice"
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if sys.argv[1:2] == ["run"]:
        from tracker import run
        run(dry_run="--dry-run" in sys.argv[2:])
        return

    args = sys.argv[1:]
    # Optional trailing min count: main.py "<league>" 3 counts 3 7 .. 7 3 as positive
    min_side = None
    if len(args) > 1 and args[-1].isdigit():
        min_side = int(args.pop())

    league_ids = list_league_ids()
    # Last matches and their odds cost API requests, so they are fetched only for a searched league
    league_searched = bool(args)

    if league_searched:
        query = " ".join(args)
        league_ids = find_leagues(query, league_ids)
        if not league_ids:
            print(f'No league found for "{query}". Available leagues:')
            for league_id in list_league_ids():
                print(f"    {league_name(league_id)} ({league_id})")
            sys.exit(1)

    if min_side is not None:
        for league_id in league_ids:
            matches = matches_per_round(load_rounds(league_id))
            if not 1 <= min_side <= matches // 2:
                print(f"{league_name(league_id)} ({league_id}): min count must be 1..{matches // 2} for {matches} matches per round")
                sys.exit(1)

    def percentage(league_id):
        return positive_rounds_percentage(league_id, min_side)

    for league_id in sorted(league_ids, key=percentage, reverse=True):
        print_league_stats(league_id, with_last_matches=league_searched, min_side=min_side)
        print()


if __name__ == "__main__":
    main()
