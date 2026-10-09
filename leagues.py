import difflib
import re
import unicodedata

LEAGUE_NAMES = {
    39: "England Premier League",
    40: "England Championship",
    61: "France Ligue 1",
    62: "France Ligue 2",
    71: "Brazil Serie A",
    72: "Brazil Serie B",
    78: "Germany Bundesliga",
    79: "Germany 2. Bundesliga",
    80: "Germany 3. Liga",
    88: "Netherlands Eredivisie",
    94: "Portugal Primeira Liga",
    98: "Japan J1 League",
    100: "Japan J3 League",
    103: "Norway Eliteserien",
    104: "Norway OBOS-ligaen",
    106: "Poland Ekstraklasa",
    107: "Poland I Liga",
    109: "Poland II Liga",
    113: "Sweden Allsvenskan",
    119: "Denmark Superliga",
    120: "Denmark 1. Division",
    135: "Italy Serie A",
    136: "Italy Serie B",
    140: "Spain La Liga",
    144: "Belgium Jupiler Pro League",
    173: "Bulgaria Vtora Liga",
    204: "Turkey 1. Lig",
    211: "Croatia Prva NL",
    219: "Austria 2. Liga",
    221: "Austria Regionalliga East",
    235: "Russia Premier League",
    236: "Russia FNL",
    251: "Paraguay Division Intermedia",
    252: "Paraguay Copa de Primera Clausura",
    266: "Chile Liga de Ascenso",
    271: "Hungary NB I",
    272: "Hungary NB II",
    281: "Peru Liga 1",
    283: "Romania SuperLiga",
    287: "Serbia Prva Liga",
    305: "Qatar Stars League",
    307: "Saudi Arabia Pro League",
    308: "Saudi Arabia Division 1",
    318: "Cyprus 1. Division",
    333: "Ukraine Premier League",
    334: "Ukraine Persha Liga",
    342: "Armenia Premier League",
    345: "Czech Chance Liga",
    346: "Czech Chance Narodni Liga",
    348: "Czech 3. CFL Group A",
    369: "Uzbekistan Super League",
    374: "Slovenia 2. SNL",
    417: "Bahrain Premier League",
    436: "Spain Primera RFEF Group 2",
    492: "Netherlands Tweede Divisie",
    506: "Slovakia 2. liga",
    563: "Sweden Division 1 Norra",
    592: "Sweden Division 2 Norra Götaland",
    596: "Sweden Division 2 Västra Götaland",
    668: "Czech 1. Liga U19",
    685: "Czech 3. CFL Group B",
    862: "Denmark 3. Division",
}

# API-Football season of a league, labelled by the year it starts
DEFAULT_SEASON = 2026
# Leagues whose current season has a different label than DEFAULT_SEASON
LEAGUE_SEASONS = {
    # J1 moved to autumn-spring: 2026 is the short Feb-Jun 2026 tournament, Aug 2026 - Jun 2027 is 2027
    98: 2027,
}

# Minimum average word similarity (0..1) for a fuzzy match
FUZZY_THRESHOLD = 0.6


def league_name(league_id):
    return LEAGUE_NAMES.get(league_id, f"League {league_id}")


def league_season(league_id):
    return LEAGUE_SEASONS.get(league_id, DEFAULT_SEASON)


def _words(text):
    """Lowercase words without accents or punctuation: "Norra Götaland" -> ["norra", "gotaland"]"""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", text.lower())


def _fuzzy_score(query_words, name_words):
    """Average, over query words, of the best similarity to any word of the name."""
    return sum(
        max(difflib.SequenceMatcher(None, q, n).ratio() for n in name_words)
        for q in query_words
    ) / len(query_words)


def find_leagues(query, league_ids):
    """League ids matching a possibly misspelled or partial league name, or a league id.

    Exact (accent and case insensitive) substring matches win; otherwise the single
    closest fuzzy match is returned, if it is close enough.
    """
    query = query.strip()
    if query.isdigit():
        return [int(query)] if int(query) in league_ids else []

    query_words = _words(query)
    if not query_words:
        return []

    names = {league_id: _words(league_name(league_id)) for league_id in league_ids}
    joined_query = " ".join(query_words)
    exact = [league_id for league_id, words in names.items() if joined_query in " ".join(words)]
    if exact:
        return exact

    scores = {league_id: _fuzzy_score(query_words, words) for league_id, words in names.items()}
    best = max(scores, key=scores.get)
    return [best] if scores[best] >= FUZZY_THRESHOLD else []
