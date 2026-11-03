import difflib
import re
import unicodedata

LEAGUE_NAMES = {
    39: "England Premier League",
    40: "England Championship",
    43: "England National League",
    61: "France Ligue 1",
    62: "France Ligue 2",
    71: "Brazil Serie A",
    72: "Brazil Serie B",
    78: "Germany Bundesliga",
    79: "Germany 2. Bundesliga",
    80: "Germany 3. Liga",
    88: "Netherlands Eredivisie",
    89: "Netherlands Eerste Divisie",
    94: "Portugal Primeira Liga",
    95: "Portugal Liga 2",
    98: "Japan J1 League",
    100: "Japan J3 League",
    103: "Norway Eliteserien",
    104: "Norway OBOS-ligaen",
    106: "Poland Ekstraklasa",
    107: "Poland I Liga",
    109: "Poland II Liga",
    110: "Wales Cymru Premier",
    113: "Sweden Allsvenskan",
    114: "Sweden Superettan",
    119: "Denmark Superliga",
    120: "Denmark 1. Division",
    122: "Denmark 2. Division",
    135: "Italy Serie A",
    136: "Italy Serie B",
    140: "Spain La Liga",
    141: "Spain La Liga 2",
    144: "Belgium Jupiler Pro League",
    172: "Bulgaria efbet League",
    173: "Bulgaria Vtora Liga",
    179: "Scotland Premiership",
    186: "Algeria Ligue 1",
    197: "Greece Super League",
    203: "Turkey Super Lig",
    204: "Turkey 1. Lig",
    207: "Switzerland Super League",
    211: "Croatia Prva NL",
    218: "Austria Bundesliga",
    219: "Austria 2. Liga",
    221: "Austria Regionalliga East",
    233: "Egypt Premier League",
    235: "Russia Premier League",
    236: "Russia FNL",
    251: "Paraguay Division Intermedia",
    252: "Paraguay Copa de Primera Clausura",
    265: "Chile Liga de Primera",
    266: "Chile Liga de Ascenso",
    268: "Uruguay Liga AUF",
    269: "Uruguay Segunda División",
    271: "Hungary NB I",
    272: "Hungary NB II",
    274: "Indonesia Super League",
    275: "Indonesia Championship",
    281: "Peru Liga 1",
    283: "Romania SuperLiga",
    286: "Serbia Super Liga",
    287: "Serbia Prva Liga",
    288: "South Africa Betway Premiership",
    290: "Iran Persian Gulf Pro League",
    305: "Qatar Stars League",
    307: "Saudi Arabia Pro League",
    308: "Saudi Arabia Division 1",
    318: "Cyprus 1. Division",
    332: "Slovakia Niké liga",
    333: "Ukraine Premier League",
    334: "Ukraine Persha Liga",
    340: "Vietnam V.League 1",
    342: "Armenia Premier League",
    345: "Czech Chance Liga",
    346: "Czech Chance Narodni Liga",
    348: "Czech 3. CFL Group A",
    349: "Czech 3. MSFL",
    363: "Ethiopia Premier League",
    369: "Uzbekistan Super League",
    374: "Slovenia 2. SNL",
    382: "Israel Liga Leumit",
    383: "Israel Ligat Ha'Al",
    391: "Malawi Super League",
    392: "Malta Challenge League",
    417: "Bahrain Premier League",
    435: "Spain Primera RFEF Group 1",
    436: "Spain Primera RFEF Group 2",
    473: "Norway 2. Division Group 1",
    474: "Norway 2. Division Group 2",
    492: "Netherlands Tweede Divisie",
    496: "Israel Liga Alef South",
    506: "Slovakia 2. liga",
    542: "Iraq Stars League",
    549: "Sweden Damallsvenskan",
    563: "Sweden Division 1 Norra",
    564: "Sweden Division 1 Södra",
    592: "Sweden Division 2 Norra Götaland",
    596: "Sweden Division 2 Västra Götaland",
    668: "Czech 1. Liga U19",
    685: "Czech 3. CFL Group B",
    736: "Sweden Elitettan",
    774: "Norway 3. Division Group 1",
    862: "Denmark 3. Division",
}

# Soccerway competition path of each league (https://www.soccerway.com/<path>/fixtures/): the data files'
# favourites come from Soccerway's 1xBet odds, so last-match odds are read there too
SOCCERWAY_LEAGUES = {
    39: "england/premier-league",
    40: "england/championship",
    43: "england/national-league",
    61: "france/ligue-1",
    62: "france/ligue-2",
    71: "brazil/serie-a",
    72: "brazil/serie-b",
    78: "germany/bundesliga",
    79: "germany/2-bundesliga",
    80: "germany/3-liga",
    88: "netherlands/eredivisie",
    89: "netherlands/eerste-divisie",
    94: "portugal/liga-portugal",
    95: "portugal/liga-portugal-2",
    98: "japan/j1-league",
    100: "japan/j3-league",
    103: "norway/eliteserien",
    104: "norway/obos-ligaen",
    106: "poland/ekstraklasa",
    107: "poland/division-1",
    109: "poland/division-2",
    110: "wales/cymru-premier",
    113: "sweden/allsvenskan",
    114: "sweden/superettan",
    119: "denmark/superliga",
    120: "denmark/1st-division",
    122: "denmark/2nd-division",
    135: "italy/serie-a",
    136: "italy/serie-b",
    140: "spain/laliga",
    141: "spain/laliga2",
    144: "belgium/jupiler-pro-league",
    172: "bulgaria/efbet-league",
    173: "bulgaria/vtora-liga",
    179: "scotland/premiership",
    186: "algeria/ligue-1",
    197: "greece/super-league",
    203: "turkey/super-lig",
    204: "turkey/1-lig",
    207: "switzerland/super-league",
    211: "croatia/prva-nl",
    218: "austria/bundesliga",
    219: "austria/2-liga",
    221: "austria/regionalliga-east",
    233: "egypt/premier-league",
    235: "russia/premier-league",
    236: "russia/fnl",
    251: "paraguay/division-intermedia",
    252: "paraguay/copa-de-primera",
    265: "chile/liga-de-primera",
    266: "chile/liga-de-ascenso",
    268: "uruguay/liga-auf-uruguaya",
    269: "uruguay/segunda-division",
    271: "hungary/nb-i",
    272: "hungary/nb-ii",
    274: "indonesia/super-league",
    275: "indonesia/championship",
    281: "peru/liga-1",
    283: "romania/superliga",
    286: "serbia/mozzart-bet-super-liga",
    287: "serbia/mozzart-bet-prva-liga",
    288: "south-africa/betway-premiership",
    290: "iran/persian-gulf-pro-league",
    305: "qatar/qsl",
    307: "saudi-arabia/saudi-professional-league",
    308: "saudi-arabia/division-1",
    318: "cyprus/cyprus-league",
    332: "slovakia/nike-liga",
    333: "ukraine/premier-league",
    334: "ukraine/persha-liga",
    340: "vietnam/v-league-1",
    342: "armenia/premier-league",
    345: "czech-republic/chance-liga",
    346: "czech-republic/chnl",
    348: "czech-republic/3-cfl-group-a",
    349: "czech-republic/3-msfl",
    363: "ethiopia/premier-league",
    369: "uzbekistan/super-league",
    374: "slovenia/2-snl",
    382: "israel/leumit-league",
    383: "israel/ligat-ha-al",
    391: "malawi/super-league",
    392: "malta/challenge-league",
    417: "bahrain/premier-league",
    435: "spain/primera-rfef-group-1",
    436: "spain/primera-rfef-group-2",
    473: "norway/division-2-group-1",
    474: "norway/division-2-group-2",
    492: "netherlands/tweede-divisie",
    496: "israel/liga-alef-south",
    506: "slovakia/2-liga",
    542: "iraq/stars-league",
    549: "sweden/allsvenskan-women",
    563: "sweden/division-1-norra",
    564: "sweden/division-1-sodra",
    592: "sweden/division-2-norra-gotaland",
    596: "sweden/division-2-vastra-gotaland",
    668: "czech-republic/u19-league",
    685: "czech-republic/3-cfl-group-b",
    736: "sweden/elitettan-women",
    774: "norway/division-3-group-1",
    862: "denmark/3rd-division",
}

# API-Football season of a league, labelled by the year it starts
DEFAULT_SEASON = 2026
# Leagues whose current season has a different label than DEFAULT_SEASON
LEAGUE_SEASONS = {
    # J1 moved to autumn-spring: 2026 is the short Feb-Jun 2026 tournament, Aug 2026 - Jun 2027 is 2027
    98: 2027,
}

# Leagues whose API-Football id holds several groups, mapped to the group we track:
# only rounds named "<group> - N" belong to the league
LEAGUE_ROUND_GROUPS = {
    496: "South",
}

# Minimum average word similarity (0..1) for a fuzzy match
FUZZY_THRESHOLD = 0.6


def league_name(league_id):
    return LEAGUE_NAMES.get(league_id, f"League {league_id}")


def league_season(league_id):
    return LEAGUE_SEASONS.get(league_id, DEFAULT_SEASON)


def soccerway_league(league_id):
    return SOCCERWAY_LEAGUES.get(league_id)


def league_round_group(league_id):
    return LEAGUE_ROUND_GROUPS.get(league_id)


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
