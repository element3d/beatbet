# BeatBet web dashboard

A calendar of each round's **single last match** (rounds whose last kick-off is shared by 2+ matches are skipped),
with the round's status from `data/<league>.txt`.

- `backend/` FastAPI + SQLite (`web/beatbet.db`), reuses `football_api.py`, `leagues.py`, `round_stats.py`
- `frontend/` React + Vite + Tailwind

## First-time setup

```
cd web/backend
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

cd ../frontend
npm install
```

## Run

```
cd web/frontend && npm run build          # once, or after UI changes
cd web/backend && .venv\Scripts\python -m uvicorn main:app --port 8000
```

Open http://localhost:8000

For UI development, run uvicorn as above and `npm run dev` in `web/frontend` (http://localhost:5173, hot reload).

## Data

- **Sync all** (button, or `.venv\Scripts\python sync.py`) fetches every tracked league's matches from 2 days ago
  to 10 days ahead (`SYNC_DAYS_BACK` / `SYNC_DAYS_AHEAD` in `backend/sync.py`): one API request per league.
  Fixtures already stored outside that window are kept. Nothing before `KEEP_FROM` (1 Oct 2026) is stored.
  It then saves the 1X2 odds of every single last match in the window (one request per match without
  fresh odds; refreshed until kick-off, then kept), since API-Football drops odds about a week after a match.
- **Refresh** (button next to the day) updates scores and statuses of the selected day: 1-2 requests
  (or `.venv\Scripts\python sync.py --date 2026-11-02`, a UTC date).
- Round status is read from the `data/` files on every request, so edits there show up immediately.

## Odds

Predictions use, in this order: odds entered by hand, **1xBet odds from Soccerway** (where the `data/` files'
favourites come from), then API-Football's odds. The card shows the source: "Soccerway ↗" (links to the
match's odds page) or an orange "API odds" when the match was not found on Soccerway or 1xBet has no odds
there, and a red warning when API-Football names the other favourite.

- `backend/soccerway.py` finds the match on the league's Soccerway fixtures/results pages
  (`SOCCERWAY_LEAGUES` in `leagues.py`, e.g. `brazil/serie-b`) by kick-off and team names, then reads the
  1xBet row of its odds page in headless Chromium (Playwright). Saved in the `soccerway_odds` table.
- Read when the dashboard shows a day (about 5 s per match the first time): refreshed every 30 minutes
  until kick-off, once more after kick-off (the closing odds Soccerway keeps showing), then kept.
  Sync does not read them: Soccerway keeps a match's odds after it is played.
- **Refresh** also reads them again right away (shown as "Updating odds…") for the matches shown that kick
  off within 2 hours or have started, unless their closing odds are already saved. A match found once is
  reopened by its saved link; 2 headless browsers read at once, loading only Soccerway's own scripts.
- A new league needs its Soccerway path in `SOCCERWAY_LEAGUES` (the part of the URL before `/fixtures/`).
- First-time setup: `.venv\Scripts\python -m pip install -r requirements.txt` then
  `.venv\Scripts\python -m playwright install chromium`.
