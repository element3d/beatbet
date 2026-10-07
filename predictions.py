from round_stats import MIN_SIDE_BY_MATCHES, is_positive

# A favourite at or below these odds is unlikely to switch, so its match can be posted before kick-off
SAFE_FAVOURITE_ODDS = 2.15
# Confidence = this weight * pattern based chance + the rest * bookmaker implied probability
PATTERN_WEIGHT = 0.7
# The pattern based chance is multiplied by this for each match the short side misses beyond one
PENALTY_PER_EXTRA_MATCH = 0.5


def favourite_is_home(odds):
    return odds["w1"] <= odds["w2"]


def favourite_odds(odds):
    return min(odds["w1"], odds["w2"])


def is_safe(odds):
    """The favourite is clear enough to post before kick-off."""
    return favourite_odds(odds) <= SAFE_FAVOURITE_ODDS


def make_prediction(split, matches, odds, pattern_percentage, home, away):
    """Prediction for a round's last match, or None if the round already fits the pattern.

    split is (fav wins, fav not wins) of the round's other matches. The pick is the side
    the round is short of: "fav wins" when fav wins are short, otherwise "fav does not win".
    Besides the pick, the result holds every number the confidence is calculated from.
    """
    if is_positive(split, matches):
        return None
    wins, not_wins = split
    min_side = MIN_SIDE_BY_MATCHES[matches]
    pick_fav_wins = wins < not_wins
    missing = min_side - min(wins, not_wins)

    # Bookmaker implied probabilities, then without the margin
    raw = {key: 1 / odds[key] for key in ("w1", "x", "w2")}
    total = sum(raw.values())
    probabilities = {key: value / total for key, value in raw.items()}
    home_fav = favourite_is_home(odds)
    fav_key, dog_key = ("w1", "w2") if home_fav else ("w2", "w1")

    if pick_fav_wins:
        implied = probabilities[fav_key]
        pick_odds = odds[fav_key]
        code = "W1" if home_fav else "W2"
        label = f"{home if home_fav else away} wins"
    else:
        implied = probabilities["x"] + probabilities[dog_key]
        # Fair double chance odds of draw or underdog win
        pick_odds = 1 / (raw["x"] + raw[dog_key])
        code = "X2" if home_fav else "1X"
        label = f"{away if home_fav else home} doesn't lose"

    penalty = PENALTY_PER_EXTRA_MATCH ** (missing - 1)
    pattern_chance = pattern_percentage * penalty
    confidence = PATTERN_WEIGHT * pattern_chance + (1 - PATTERN_WEIGHT) * implied * 100
    return {
        "code": code,
        "label": label,
        "odds": pick_odds,
        "pick_fav_wins": pick_fav_wins,
        "min_side": min_side,
        "missing": missing,
        "penalty": penalty,
        "pattern_percentage": pattern_percentage,
        "pattern_chance": pattern_chance,
        "margin": total - 1,
        "probabilities": probabilities,
        "fav_key": fav_key,
        "dog_key": dog_key,
        "implied": implied,
        "confidence": confidence,
    }
