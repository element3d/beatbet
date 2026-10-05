import difflib
import re
import unicodedata

LEAGUE_NAMES = {
    39: "England Premier League",
    72: "Brazil Serie B",
    104: "Norway OBOS-ligaen",
    119: "Denmark Superliga",
    120: "Denmark 1. Division",
    144: "Belgium Jupiler Pro League",
    173: "Bulgaria Vtora Liga",
    211: "Croatia Prva NL",
    219: "Austria 2. Liga",
    221: "Austria Regionalliga East",
    251: "Paraguay Division Intermedia",
    252: "Paraguay Copa de Primera Clausura",
    266: "Chile Liga de Ascenso",
    281: "Peru Liga 1",
    283: "Romania SuperLiga",
    287: "Serbia Prva Liga",
    305: "Qatar Stars League",
    308: "Saudi Arabia Division 1",
    345: "Czech Chance Liga",
    346: "Czech Chance Narodni Liga",
    348: "Czech 3. CFL Group A",
    369: "Uzbekistan Super League",
    417: "Bahrain Premier League",
    506: "Slovakia 2. liga",
    592: "Sweden Division 2 Norra Götaland",
    668: "Czech 1. Liga U19",
    685: "Czech 3. CFL Group B",
    862: "Denmark 3. Division",
}

# Minimum average word similarity (0..1) for a fuzzy match
FUZZY_THRESHOLD = 0.6


def league_name(league_id):
    return LEAGUE_NAMES.get(league_id, f"League {league_id}")


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
