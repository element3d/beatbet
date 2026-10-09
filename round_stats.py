import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Matches per round -> minimum count on each side (favourite wins / does not win)
# for a round to be positive. E.g. 8 matches: 3 5, 4 4 and 5 3 are positive.
MIN_SIDE_BY_MATCHES = {12: 5, 10: 4, 9: 3, 8: 3, 7: 2, 6: 2}


def list_league_ids():
    """League ids that have a data/<league_id>.txt file."""
    return sorted(int(name[:-4]) for name in os.listdir(DATA_DIR) if name.endswith(".txt"))


def load_rounds(league_id):
    """Read data/<league_id>.txt into {round number: (fav wins, fav not wins)}."""
    rounds = {}
    current_round = None
    with open(os.path.join(DATA_DIR, f"{league_id}.txt"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("r"):
                current_round = int(line[1:])
            else:
                wins, not_wins = map(int, line.split())
                rounds[current_round] = (wins, not_wins)
    return rounds


def matches_per_round(rounds):
    """Largest round total, so an incomplete round does not lower it."""
    return max(wins + not_wins for wins, not_wins in rounds.values())


def is_positive(split, matches, min_side=None):
    """Both sides reach the minimum, even if some matches of the round are missing.
    min_side overrides the default minimum for the league's matches per round."""
    wins, not_wins = split
    if min_side is None:
        min_side = MIN_SIDE_BY_MATCHES[matches]
    return wins >= min_side and not_wins >= min_side


def _unfinished_current_round(rounds):
    """Number of the latest round if not all its matches are played yet, otherwise None."""
    if not rounds:
        return None
    number = max(rounds)
    if sum(rounds[number]) == matches_per_round(rounds):
        return None
    return number


def current_round(league_id):
    """(round number, split) of the latest round if it is unfinished, otherwise None."""
    rounds = load_rounds(league_id)
    number = _unfinished_current_round(rounds)
    if number is None:
        return None
    return number, rounds[number]


def positive_rounds_count(league_id, min_side=None):
    """(number of positive rounds, total number of rounds), excluding an unfinished current round."""
    rounds = load_rounds(league_id)
    if not rounds:
        return 0, 0
    matches = matches_per_round(rounds)
    if matches not in MIN_SIDE_BY_MATCHES:
        raise ValueError(f"League {league_id}: no pattern defined for {matches} matches per round")
    unfinished = _unfinished_current_round(rounds)
    if unfinished is not None:
        del rounds[unfinished]
    positive = sum(1 for split in rounds.values() if is_positive(split, matches, min_side))
    return positive, len(rounds)


def positive_rounds_percentage(league_id, min_side=None):
    """Percentage of positive rounds."""
    positive, total = positive_rounds_count(league_id, min_side)
    if not total:
        return 0.0
    return positive / total * 100
