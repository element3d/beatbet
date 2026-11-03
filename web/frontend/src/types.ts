export type Phase = "upcoming" | "live" | "finished" | "other";

export type RoundState = "positive" | "negative" | "open" | "out_of_reach" | "no_data";

export interface Pattern {
  min_side: number;
  text: string;
  positive: number;
  total: number;
  pct: number;
  default: boolean;
  round_fits: boolean | null;
}

export interface RoundStatus {
  matches: number;
  min_side: number;
  league_positive_pct: number | null;
  patterns: Pattern[];
  state: RoundState;
  wins?: number;
  not_wins?: number;
  remaining?: number;
  missing?: number;
  short_side?: "wins" | "not_wins" | null;
}

export interface Team {
  id: number;
  name: string;
  logo: string | null;
  goals: number | null;
}

export interface LastMatch {
  fixture_id: number;
  kickoff: number;
  status: string;
  phase: Phase;
  elapsed: number | null;
  round: number;
  league: { id: number; name: string; country: string | null; logo: string | null; flag: string | null };
  home: Team;
  away: Team;
  round_status: RoundStatus | null;
  prediction: Prediction | null;
}

/** The pick if that team is the favourite, for entering odds by hand. */
export type PickOptions = Partial<Record<"home" | "away", { code: string; label: string }>>;

/** A complete round whose last match has no odds: the favourite and pick odds must be entered by hand
 *  before its prediction can be rebuilt. */
export interface PendingRebuild {
  risky: false;
  pending_rebuild: true;
  needs_manual: true;
  has_odds: false;
  options: PickOptions;
}

/** The last match decides a pattern stricter than the league's default: no prediction is made. */
export interface RiskyMarker {
  risky: true;
  pending_rebuild: false;
  pattern: { min_side: number; text: string; pct: number; positive: number; total: number };
}

export type Prediction = FullPrediction | PendingRebuild | RiskyMarker;

export interface OddsCheck {
  /** The match's Soccerway odds page, null when not looked up yet or not found. */
  soccerway_url: string | null;
  soccerway_found: boolean;
  /** API-Football's 1X2 odds, to compare with Soccerway's. */
  api_market: { w1: number; x: number; w2: number } | null;
  /** Soccerway and API-Football name different favourites. */
  favourite_conflict: boolean;
}

export interface FullPrediction {
  risky: false;
  pending_rebuild: false;
  /** No odds yet: enter the favourite and the pick's odds by hand. */
  needs_manual: boolean;
  options?: PickOptions;
  /** Where the odds come from: Soccerway's 1xBet (the data files' source), API-Football, or entered by hand. */
  odds_source?: "soccerway" | "api" | "manual";
  odds_check: OddsCheck;
  /** Probability below the minimum (55%): shown greyed out, not counted in the day summary. */
  low_probability?: boolean;
  /** The pattern this last match decides: it fits exactly when the pick comes in. */
  pattern: { min_side: number; text: string; pct: number; positive: number; total: number };
  /** The pattern compared with the league's default one. */
  strength: "default" | "weaker";
  pick_fav_wins: boolean;
  /** The round's split of its other matches, which the prediction is made from. */
  before: { wins: number; not_wins: number };
  /** Rebuilt after the round completed: this match's result was taken back out of the final split,
   *  and the pattern counts only earlier rounds. */
  reconstructed: boolean;
  odds_fetched_at: number | null;
  has_odds: boolean;
  code?: string;
  label?: string;
  odds?: number;
  /** Chance of the pick in %: (pattern_coef * pattern.pct + bookmaker_probability) / 2. */
  probability?: number;
  /** Chance of the pick from the bookmaker's 1X2 odds with the margin removed, in %. */
  bookmaker_probability?: number;
  /** Weight of the pattern's fit %: 1 for the default pattern, lower for the weaker one. */
  pattern_coef?: number;
  bookmaker?: string | null;
  market?: { w1: number; x: number; w2: number } | null;
  favourite?: "home" | "away";
  /** null for odds entered by hand: without the favourite's own odds it cannot be judged. */
  safe?: boolean | null;
  result?: "won" | "lost" | null;
}

export interface SyncState {
  running: boolean;
  done: number;
  total: number;
  current: string | null;
  errors: string[];
  started_at: number | null;
  finished_at: number | null;
}

export interface Meta {
  leagues: number;
  fixtures: number;
  last_synced_at: number | null;
  sync: SyncState;
}
