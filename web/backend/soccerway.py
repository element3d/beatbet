"""1xBet 1X2 odds of single last matches, read from Soccerway and cached in the soccerway_odds table.

The data files' favourites are taken from Soccerway's 1xBet odds, and API-Football's odds can name
another favourite, so predictions prefer these.

A match is found on its league's Soccerway fixtures and results pages (plain HTML, which lists every
match with its id, kick-off and teams). Its odds page builds the odds table in the browser, so it is
opened in headless Chromium (Playwright) and the 1xBet row is read from it.
"""
import difflib
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse

import truststore

import paths  # noqa: F401  (puts the repo root on sys.path)
from leagues import _words, soccerway_league

BASE_URL = "https://www.soccerway.com"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ONE_X_BET_ID = "417"  # Soccerway's bookmaker id of 1xBet
BOOKMAKER_LABEL = "1xBet (Soccerway)"

# A league's match list is downloaded again when older than this
LEAGUE_CACHE_SECONDS = 10 * 60
# Odds of a match not started yet are read again when older than this
ODDS_TTL_SECONDS = 30 * 60
# A match without odds (or not found) after kick-off is retried this often, for this long
MISSING_RETRY_SECONDS = 30 * 60
MISSING_RETRY_FOR_SECONDS = 3 * 24 * 60 * 60
NOT_STARTED_STATUSES = {"NS", "TBD"}

# Matching a fixture to a Soccerway match: each team at least this similar (0..1), the kick-off at most this far
MIN_TEAM_SCORE = 0.75
MAX_MOVE_SECONDS = 3 * 24 * 60 * 60
# Or one team surely the same (a team plays once at a time): at this similarity with the same kick-off,
# or at a higher one up to SAME_TIME_SECONDS apart, the other team then looking a little alike too
SAME_KICKOFF_SECONDS = 15 * 60
SURE_TEAM_SCORE_SAME_KICKOFF = 0.9
SURE_TEAM_SCORE = 0.9
MIN_OTHER_TEAM_SCORE = 0.4
SAME_TIME_SECONDS = 12 * 60 * 60
# Ignored when comparing team names, so "Polokwane City" matches "Polokwane"
GENERIC_TEAM_WORDS = {
    "fc", "fk", "cf", "sc", "ac", "afc", "cd", "sk", "nk", "club", "de", "the", "utd", "united", "city", "al", "w",
}
# Reserve team markers, made one word: "Real Madrid II" / "Real Madrid B", "Almere City II" / "Jong Almere City"
RESERVE_WORDS = {"ii", "b", "2", "jong"}

# Matches read at once, each in its own headless browser: rendering is the bottleneck, and more
# browsers only slow each page down (38 matches: 1 browser 65 s, 2 browsers 49 s, 4 browsers no faster)
WORKERS = 2
# Hosts the odds pages need (the site, its scripts and its data feeds); everything else is blocked
NEEDED_HOSTS = ("soccerway.com", "flashscore.com", "flashscore.ninja", "lsapp.eu")
SKIPPED_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}
PAGE_TIMEOUT_MS = 30_000
ODDS_TABLE_TIMEOUT_MS = 15_000

_league_cache = {}
_league_cache_lock = threading.Lock()


def _get(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(request, context=SSL_CONTEXT, timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def parse_events(html):
    """Matches embedded in a Soccerway competition page: records "~AA÷<id>¬AD÷<kick-off>¬...",
    fields "key÷value" separated by "¬"."""
    events = {}
    for record in html.split("~AA÷")[1:]:
        record = record.split("~", 1)[0]
        fields = dict(part.split("÷", 1) for part in ("AA÷" + record).split("¬") if "÷" in part)
        if not all(fields.get(k) for k in ("AA", "AD", "AE", "AF", "WU", "WV", "PX", "PY")):
            continue
        events[fields["AA"]] = {
            "id": fields["AA"],
            "kickoff": int(fields["AD"]),
            "home": fields["AE"],
            "away": fields["AF"],
            "url": (
                f"{BASE_URL}/match/{fields['WU']}-{fields['PX']}/{fields['WV']}-{fields['PY']}"
                f"/odds/1x2-odds/full-time/?mid={fields['AA']}"
            ),
        }
    return list(events.values())


def league_events(path):
    """Matches on the league's Soccerway fixtures and results pages (cached for a few minutes)."""
    with _league_cache_lock:
        cached = _league_cache.get(path)
        if cached and time.time() - cached[0] < LEAGUE_CACHE_SECONDS:
            return cached[1]
    events = {}
    for page in ("fixtures", "results"):
        try:
            html = _get(f"{BASE_URL}/{path}/{page}/")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                raise RuntimeError(f"Soccerway has no page {path}/{page}/ (check SOCCERWAY_LEAGUES)")
            raise
        for event in parse_events(html):
            events[event["id"]] = event
    events = list(events.values())
    with _league_cache_lock:
        _league_cache[path] = (time.time(), events)
    return events


def _team_words(name):
    """Words of a team name without generic ones ("FC", "United", ...) or numbers ("05", "1905"),
    unless nothing else is left; reserve markers become "reserve"."""
    words = ["reserve" if w in RESERVE_WORDS else w for w in _words(name)]
    return [w for w in words if w not in GENERIC_TEAM_WORDS and not w.isdigit()] or words


def _word_similarity(a, b):
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 2 and (a.startswith(b) or b.startswith(a)):
        return 0.95  # abbreviation: "Dyn." / "Dynamo"
    return difflib.SequenceMatcher(None, a, b).ratio()


def _directed_score(query, name):
    return sum(max(_word_similarity(q, n) for n in name) for q in query) / len(query)


def team_score(a, b):
    """Similarity of two team names (0..1), in both directions so extra words on either side count."""
    wa, wb = _team_words(a), _team_words(b)
    if not wa or not wb:
        return 0.0
    return (_directed_score(wa, wb) + _directed_score(wb, wa)) / 2


def _pairing_matches(home, away, sw_home, sw_away, gap):
    """Whether the fixture's teams are the Soccerway match's teams in this order.

    Both teams similar enough, or one team almost surely the same at nearly the same time: a team
    plays one match at a time, so the other team is then the same one under another name
    ("Stade Brestois 29" / "Brest").
    """
    h, a = team_score(home, sw_home), team_score(away, sw_away)
    weaker, stronger = sorted((h, a))
    if weaker >= MIN_TEAM_SCORE:
        return True
    if gap is None:
        return False  # kick-off unknown (a live match): both teams must match
    if gap <= SAME_KICKOFF_SECONDS:
        return stronger >= SURE_TEAM_SCORE_SAME_KICKOFF
    # The two sites' schedules can differ (a team playing someone else that day there): further apart
    # in time, the other team must look somewhat alike too
    return gap <= SAME_TIME_SECONDS and stronger >= SURE_TEAM_SCORE and weaker >= MIN_OTHER_TEAM_SCORE


def find_event(events, kickoff, home, away):
    """(event, swapped) of the Soccerway match of a fixture, or (None, False). The closest kick-off wins.

    swapped: Soccerway lists the teams the other way round, so its 1 and 2 odds are exchanged.
    An event's kickoff may be None (a live match on the rendered league page): it comes last.
    """
    best = (None, None, False)
    for event in events:
        gap = None if event["kickoff"] is None else abs(event["kickoff"] - kickoff)
        if gap is not None and gap > MAX_MOVE_SECONDS:
            continue
        for is_swapped, (sw_home, sw_away) in ((False, (event["home"], event["away"])), (True, (event["away"], event["home"]))):
            if not _pairing_matches(home, away, sw_home, sw_away, gap):
                continue
            # Straight before swapped at the same kick-off
            rank = (MAX_MOVE_SECONDS + 1 if gap is None else gap, is_swapped)
            if best[0] is None or rank < best[0]:
                best = (rank, event, is_swapped)
    return best[1], best[2]


def _row_kickoff(text):
    """Unix kick-off of a league page row's time ("06.11. 22:00", or "22:00" for today, in UTC), or None
    when it shows the minute of a live match or a result. The year is the one closest to now."""
    now = datetime.now(timezone.utc)
    text = " ".join(text.split())
    dated = re.match(r"^(\d\d)\.(\d\d)\. (\d\d):(\d\d)$", text)
    today = re.match(r"^(\d\d):(\d\d)$", text)
    if dated:
        day, month, hour, minute = map(int, dated.groups())
        candidates = []
        for year in (now.year - 1, now.year, now.year + 1):
            try:
                candidates.append(datetime(year, month, day, hour, minute, tzinfo=timezone.utc))
            except ValueError:
                pass
        if not candidates:
            return None
        return int(min(candidates, key=lambda c: abs(c - now)).timestamp())
    if today:
        hour, minute = map(int, today.groups())
        return int(now.replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp())
    return None


def _route_needed_only(route):
    """Let through only the site's own scripts and data: ads, trackers, the cookie banner, images,
    fonts and styles only slow the page down."""
    request = route.request
    host = urlparse(request.url).hostname or ""
    if host.endswith(NEEDED_HOSTS) and request.resource_type not in SKIPPED_RESOURCE_TYPES:
        route.continue_()
    else:
        route.abort()


class OddsBrowser:
    """Headless Chromium for reading odds pages, started on first use.

    Playwright's sync API is bound to the thread that started it: create, use and close it in one thread.
    """

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._league_rows = {}

    def _start(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        # UTC, so the kick-off times on league pages read as UTC
        context = self._browser.new_context(user_agent=USER_AGENT, locale="en-GB", timezone_id="UTC")
        context.route("**/*", _route_needed_only)
        self._page = context.new_page()

    def odds(self, url):
        """{"w1", "x", "w2"} of 1xBet on a Soccerway odds page, or None when 1xBet has no complete odds."""
        if self._page is None:
            self._start()
        page = self._page
        page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        try:
            page.wait_for_selector(".ui-table__row", timeout=ODDS_TABLE_TIMEOUT_MS)
        except Exception:
            return None  # no odds table: no bookmaker has odds for the match
        row = page.query_selector(f'.ui-table__row:has([data-analytics-bookmaker-id="{ONE_X_BET_ID}"])')
        if row is None:
            return None
        values = []
        for cell in row.query_selector_all(".oddsCell__odd"):
            try:
                values.append(float(cell.inner_text().strip()))
            except ValueError:
                return None  # a market closed ("-")
        if len(values) != 3 or min(values) <= 1:
            return None
        return {"w1": values[0], "x": values[1], "w2": values[2]}

    def league_rows(self, path):
        """Matches on the rendered league page, which unlike the plain HTML also lists today's and live
        ones. Same shape as parse_events; kickoff is None when the row shows the minute or a result."""
        if path in self._league_rows:
            return self._league_rows[path]
        if self._page is None:
            self._start()
        page = self._page
        page.goto(f"{BASE_URL}/{path}/", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        events = []
        try:
            page.wait_for_selector("[id^='g_1_']", timeout=ODDS_TABLE_TIMEOUT_MS)
        except Exception:
            self._league_rows[path] = events
            return events
        for row in page.query_selector_all("[id^='g_1_']"):
            link, home, away = (
                row.query_selector(s) for s in ("a.eventRowLink", ".event__homeParticipant", ".event__awayParticipant")
            )
            href = link.get_attribute("href") if link else None
            if not (href and "?mid=" in href and home and away):
                continue
            time_cell = row.query_selector(".event__time, .event__stageTime")
            events.append({
                "id": row.get_attribute("id")[len("g_1_"):],
                "kickoff": _row_kickoff(time_cell.inner_text() if time_cell else ""),
                "home": home.inner_text().strip(),
                "away": away.inner_text().strip(),
                "url": href.replace("/?mid=", "/odds/1x2-odds/full-time/?mid="),
            })
        self._league_rows[path] = events
        return events

    def close(self):
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._playwright = self._browser = self._page = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _needs_fetch(cached, fixture, now):
    if cached is None:
        return True
    if fixture["status"] in NOT_STARTED_STATUSES:
        return now - cached["fetched_at"] >= ODDS_TTL_SECONDS
    if cached["fetched_at"] < fixture["kickoff"]:
        return True  # once after kick-off: the closing odds, as Soccerway keeps showing them
    if cached["w1"] is None:
        return (
            now - cached["fetched_at"] >= MISSING_RETRY_SECONDS
            and now - fixture["kickoff"] < MISSING_RETRY_FOR_SECONDS
        )
    return False


def _cached_row(conn, fixture_id):
    return conn.execute("SELECT * FROM soccerway_odds WHERE fixture_id = ?", (fixture_id,)).fetchone()


def _final(cached, fixture):
    """The match has started and its odds were read after kick-off: Soccerway's closing odds, which no
    longer change."""
    return (
        cached is not None and cached["w1"] is not None
        and fixture["status"] not in NOT_STARTED_STATUSES and cached["fetched_at"] >= fixture["kickoff"]
    )


def _wants_read(conn, fixture, force):
    """Whether the fixture's Soccerway odds are to be read now: when stale, or with force unless final."""
    if not soccerway_league(fixture["league_id"]):
        return False
    cached = _cached_row(conn, fixture["fixture_id"])
    if force:
        return not _final(cached, fixture)
    return _needs_fetch(cached, fixture, int(time.time()))


def _read_and_store(conn, fixture, browser):
    """Read the fixture's 1xBet odds and save them. A match found before is opened by its saved link."""
    fixture_id = fixture["fixture_id"]
    cached = _cached_row(conn, fixture_id)
    if cached is not None and cached["match_url"]:
        url, swapped = cached["match_url"], bool(cached["swapped"])
    else:
        path = soccerway_league(fixture["league_id"])
        teams = (fixture["kickoff"], fixture["home_name"], fixture["away_name"])
        event, swapped = find_event(league_events(path), *teams)
        if event is None:
            # The plain HTML lists only finished matches up to yesterday and ones not started from about
            # two days on; today's and live ones are only on the rendered page
            event, swapped = find_event(browser.league_rows(path), *teams)
        url = event["url"] if event else None
    odds = browser.odds(url) if url else None
    if odds and swapped:
        odds = {"w1": odds["w2"], "x": odds["x"], "w2": odds["w1"]}
    now = int(time.time())
    with conn:
        if odds is None and cached is not None and cached["w1"] is not None:
            # 1xBet took the market down; keep the odds we had
            conn.execute("UPDATE soccerway_odds SET fetched_at = ? WHERE fixture_id = ?", (now, fixture_id))
            return
        odds = odds or {"w1": None, "x": None, "w2": None}
        conn.execute(
            "INSERT INTO soccerway_odds (fixture_id, match_url, swapped, w1, x, w2, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (fixture_id) DO UPDATE SET match_url = excluded.match_url, swapped = excluded.swapped, "
            "w1 = excluded.w1, x = excluded.x, w2 = excluded.w2, fetched_at = excluded.fetched_at",
            (fixture_id, url, int(swapped), odds["w1"], odds["x"], odds["w2"], now),
        )


def fetch_soccerway_odds(jobs, connect):
    """Read Soccerway's 1xBet odds of fixtures that need it: when never read, when stale, or always
    when forced. jobs: [(fixtures row, force)]; connect: opens a DB connection.

    Up to WORKERS matches are read at once, each worker with its own browser and connection
    (Playwright's sync API and SQLite connections stay in the thread that made them).
    Returns (number read, errors).
    """
    conn = connect()
    try:
        todo = [fixture for fixture, force in jobs if _wants_read(conn, fixture, force)]
    finally:
        conn.close()
    if not todo:
        return 0, []

    lock = threading.Lock()
    queue = list(todo)
    read, errors = [0], []

    def work():
        conn = connect()
        try:
            with OddsBrowser() as browser:
                while True:
                    with lock:
                        if not queue:
                            return
                        fixture = queue.pop(0)
                    try:
                        _read_and_store(conn, fixture, browser)
                        with lock:
                            read[0] += 1
                    except Exception as error:  # one failing fixture must not stop the others
                        with lock:
                            errors.append(f"{fixture['home_name']} - {fixture['away_name']} (Soccerway): {error}")
        finally:
            conn.close()

    threads = [threading.Thread(target=work, daemon=True) for _ in range(min(WORKERS, len(todo)))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return read[0], errors
