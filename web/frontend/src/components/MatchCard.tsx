import { format } from "date-fns";
import { useState } from "react";
import { deleteManualOdds, saveManualOdds } from "../api";
import type { LastMatch, Pattern, PickOptions, Prediction, RoundStatus, Team } from "../types";

const STATUS_LABELS: Record<string, string> = {
  PST: "Postponed", CANC: "Cancelled", ABD: "Abandoned", SUSP: "Suspended",
  INT: "Interrupted", AWD: "Awarded", WO: "Walkover", TBD: "Time TBD", HT: "Half-time",
};

function Logo({ src, name, size = 22 }: { src: string | null; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) {
    return (
      <span
        style={{ width: size, height: size }}
        className="grid shrink-0 place-items-center rounded-full bg-white/10 text-[10px] font-semibold text-zinc-400"
      >
        {name.slice(0, 1)}
      </span>
    );
  }
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={() => setFailed(true)}
      className="shrink-0 object-contain"
      style={{ width: size, height: size }}
    />
  );
}

function TimeColumn({ match }: { match: LastMatch }) {
  if (match.phase === "live") {
    return (
      <div className="flex flex-col items-center gap-1">
        <span className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-rose-400">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-rose-400 opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-rose-500" />
          </span>
          Live
        </span>
        <span className="font-mono text-lg font-semibold text-white tabular">
          {match.status === "HT" ? "HT" : `${match.elapsed ?? 0}'`}
        </span>
      </div>
    );
  }
  const kickoff = new Date(match.kickoff * 1000);
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="font-mono text-lg font-semibold text-white tabular">{format(kickoff, "HH:mm")}</span>
      {match.phase === "finished" && (
        <span className="rounded-md bg-white/10 px-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-300">
          {match.status}
        </span>
      )}
      {match.phase === "upcoming" && (
        <span className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">Kick-off</span>
      )}
      {match.phase === "other" && (
        <span className="rounded-md bg-amber-500/15 px-1.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
          {STATUS_LABELS[match.status] ?? match.status}
        </span>
      )}
    </div>
  );
}

function TeamRow({ team, opponent, showScore }: { team: Team; opponent: Team; showScore: boolean }) {
  const won = showScore && team.goals !== null && opponent.goals !== null && team.goals > opponent.goals;
  const lost = showScore && team.goals !== null && opponent.goals !== null && team.goals < opponent.goals;
  return (
    <div className="flex items-center gap-3">
      <Logo src={team.logo} name={team.name} />
      <span className={["truncate", won ? "font-semibold text-white" : lost ? "text-zinc-400" : "text-zinc-100"].join(" ")}>
        {team.name}
      </span>
      {showScore && (
        <span className={["ml-auto font-mono text-base font-semibold tabular", won ? "text-white" : "text-zinc-400"].join(" ")}>
          {team.goals ?? "–"}
        </span>
      )}
    </div>
  );
}

const STATE_STYLES = {
  positive: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
  negative: "bg-rose-500/15 text-rose-300 ring-rose-500/30",
  open: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
  out_of_reach: "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30",
  no_data: "bg-zinc-500/10 text-zinc-400 ring-zinc-500/20",
} as const;

function stateLabel(status: RoundStatus) {
  switch (status.state) {
    case "positive":
      return "Fits pattern";
    case "negative":
      return "Missed";
    case "out_of_reach":
      return "Out of reach";
    case "no_data":
      return "No round data";
    case "open": {
      const missing = status.missing ?? 0;
      if (!status.short_side) return `Needs ${missing} each`;
      const side = status.short_side === "wins" ? "fav win" : "fav not-win";
      return `Needs ${missing} ${side}${missing > 1 ? "s" : ""}`;
    }
  }
}

/** One cell per match of the round: fav wins, fav not-wins, then matches still to play. */
function RoundBar({ status }: { status: RoundStatus }) {
  const wins = status.wins ?? 0;
  const notWins = status.not_wins ?? 0;
  const cells = Array.from({ length: Math.max(status.matches, wins + notWins) }, (_, i) =>
    i < wins ? "win" : i < wins + notWins ? "notwin" : "left",
  );
  return (
    <div className="flex gap-0.5">
      {cells.map((kind, i) => (
        <span
          key={i}
          className={[
            "h-2 flex-1 rounded-sm",
            kind === "win" ? "bg-emerald-400" : kind === "notwin" ? "bg-rose-400" : "border border-dashed border-zinc-600",
          ].join(" ")}
        />
      ))}
    </div>
  );
}

/** How often the league's finished rounds fit each pattern; ✓ when this round already fits it. */
function PatternList({ patterns }: { patterns: Pattern[] }) {
  return (
    <div className="space-y-1 border-t border-white/5 pt-2">
      <div className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">League fits</div>
      {patterns.map((p) => (
        <div
          key={p.min_side}
          title={`${p.positive} of ${p.total} finished rounds fit ${p.text}${p.default ? " (default pattern)" : ""}`}
          className={[
            "flex items-center gap-2 rounded-md px-1.5 py-0.5 text-[11px]",
            p.default ? "bg-indigo-500/10 ring-1 ring-indigo-400/30" : "",
          ].join(" ")}
        >
          <span className={["w-[72px] shrink-0 font-mono tabular", p.default ? "text-indigo-200" : "text-zinc-400"].join(" ")}>
            {p.text}
          </span>
          <div className="h-1 flex-1 overflow-hidden rounded-full bg-white/5">
            <div
              className={["h-full rounded-full", p.default ? "bg-indigo-400" : "bg-zinc-500"].join(" ")}
              style={{ width: `${p.pct}%` }}
            />
          </div>
          <span className={["w-9 text-right font-semibold tabular", p.default ? "text-white" : "text-zinc-300"].join(" ")}>
            {p.pct.toFixed(0)}%
          </span>
          <span className="w-10 text-right text-zinc-500 tabular">{p.positive}/{p.total}</span>
          <span className="w-3 text-center">
            {p.round_fits === true && <span className="text-emerald-400">✓</span>}
          </span>
        </div>
      ))}
    </div>
  );
}

function RoundPanel({ match }: { match: LastMatch }) {
  const status = match.round_status;
  return (
    <div className="flex flex-col gap-2 rounded-xl bg-black/20 p-3 ring-1 ring-white/5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-zinc-400">Round {match.round}</span>
        {status && (
          <span className={["rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1", STATE_STYLES[status.state]].join(" ")}>
            {stateLabel(status)}
          </span>
        )}
      </div>
      {status && status.state !== "no_data" ? (
        <>
          <RoundBar status={status} />
          <div className="flex items-center justify-between text-[11px] text-zinc-400 tabular">
            <span>
              <span className="font-semibold text-emerald-300">{status.wins}</span> W
              <span className="mx-1 text-zinc-600">·</span>
              <span className="font-semibold text-rose-300">{status.not_wins}</span> NW
              {(status.remaining ?? 0) > 0 && (
                <>
                  <span className="mx-1 text-zinc-600">·</span>
                  {status.remaining} left
                </>
              )}
            </span>
            <span title="Each side needs at least this many for the round to fit">min {status.min_side}</span>
          </div>
        </>
      ) : (
        <div className="text-[11px] text-zinc-500">
          {status ? "This round is not in the data file yet" : "No data for this league/season"}
        </div>
      )}
      {status && status.patterns.length > 0 && <PatternList patterns={status.patterns} />}
    </div>
  );
}

/** Prediction colours by the pattern used: default green, weaker yellow. Stricter (risky) patterns get no prediction. */
const STRENGTH_STYLES = {
  default: {
    panel: "border-emerald-500/30 from-emerald-500/10",
    title: "text-emerald-300/80",
    chip: "bg-emerald-400",
    bar: "bg-emerald-400",
    tag: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30",
    label: "Default pattern",
    hint: "Uses the league's default pattern",
  },
  weaker: {
    panel: "border-amber-500/30 from-amber-500/10",
    title: "text-amber-300/80",
    chip: "bg-amber-400",
    bar: "bg-amber-400",
    tag: "bg-amber-500/15 text-amber-300 ring-amber-500/30",
    label: "Weaker pattern",
    hint: "Uses a weaker pattern than the league's default (lower minimum per side)",
  },
} as const;

/** Choose the favourite, see the pick it gives, and save that pick's odds by hand. */
function ManualOddsForm({ match, options, onChanged }: { match: LastMatch; options: PickOptions; onChanged: () => void }) {
  const sides = (["home", "away"] as const).filter((s) => options[s]);
  const [favourite, setFavourite] = useState<"home" | "away" | null>(sides.length === 1 ? sides[0] : null);
  const [odds, setOdds] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = Number(odds.replace(",", "."));
  const valid = favourite !== null && Number.isFinite(value) && value > 1;
  const pick = favourite ? options[favourite] : undefined;

  const save = async () => {
    if (!valid || !favourite) return;
    setSaving(true);
    setError(null);
    try {
      await saveManualOdds(match.fixture_id, favourite, value);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className="text-zinc-400">Favourite</span>
        <div className="flex rounded-lg border border-white/10 bg-black/20 p-0.5">
          {(["home", "away"] as const).map((s) => (
            <button
              key={s}
              disabled={!options[s]}
              onClick={() => setFavourite(s)}
              title={options[s] ? undefined : "No prediction with this favourite"}
              className={[
                "max-w-36 truncate rounded-md px-2 py-1 font-medium transition disabled:cursor-not-allowed disabled:opacity-30",
                favourite === s ? "bg-white/15 text-white" : "text-zinc-400 hover:text-white",
              ].join(" ")}
            >
              {s === "home" ? match.home.name : match.away.name}
            </button>
          ))}
        </div>
      </div>
      {pick && (
        <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="rounded-lg bg-zinc-200 px-2 py-0.5 font-mono text-xs font-bold text-zinc-950">{pick.code}</span>
          <span className="font-semibold text-white">{pick.label}</span>
        </div>
      )}
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        <input
          inputMode="decimal"
          placeholder={pick ? `Odds of ${pick.code}` : "Choose the favourite first"}
          disabled={!favourite}
          value={odds}
          onChange={(e) => setOdds(e.target.value)}
          className="w-36 rounded-lg border border-white/10 bg-black/30 px-2.5 py-1.5 font-mono text-sm text-white placeholder:font-sans placeholder:text-xs placeholder:text-zinc-500 focus:border-emerald-400/60 focus:outline-none disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={!valid || saving}
          className="rounded-lg bg-emerald-500 px-3 py-1.5 text-xs font-semibold text-zinc-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </form>
      {error && <div className="text-[11px] text-rose-300">{error}</div>}
    </div>
  );
}

function PredictionPanel({ prediction, match, onChanged }: { prediction: Prediction; match: LastMatch; onChanged: () => void }) {
  if (prediction.risky) {
    const pattern = prediction.pattern;
    return (
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-rose-500/30 bg-rose-500/[0.06] px-3 py-2"
        title="This match decides a pattern stricter than the league's default, so no prediction is made"
      >
        <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-rose-300 ring-1 ring-rose-500/30">
          Risky
        </span>
        <span className="text-[11px] text-zinc-400 tabular">
          Pattern <span className="font-mono font-semibold text-rose-200">{pattern.text}</span> · fits{" "}
          {pattern.pct.toFixed(0)}% ({pattern.positive}/{pattern.total}) · no prediction
        </span>
      </div>
    );
  }
  if (prediction.pending_rebuild) {
    return (
      <div className="rounded-xl border border-dashed border-white/15 bg-white/[0.02] p-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">Prediction</span>
          <span className="text-[10px] text-zinc-500">no odds · round complete</span>
        </div>
        <p className="mb-2 text-[11px] text-zinc-500">
          Enter who was the favourite and the pick's odds to rebuild this round's prediction.
        </p>
        <ManualOddsForm match={match} options={prediction.options} onChanged={onChanged} />
      </div>
    );
  }
  const p = prediction;
  const side = p.pick_fav_wins ? "fav wins" : "fav doesn't win";
  const style = STRENGTH_STYLES[p.strength];
  const clearManual = async () => {
    await deleteManualOdds(match.fixture_id).catch(() => null);
    onChanged();
  };
  return (
    <div
      className={[
        "rounded-xl border bg-gradient-to-br to-transparent p-3",
        style.panel,
        p.low_probability ? "opacity-50 grayscale" : "",
      ].join(" ")}
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className={["text-[10px] font-semibold uppercase tracking-wider", style.title].join(" ")}>Prediction</span>
        <div className="flex items-center gap-1.5">
          {p.low_probability && (
            <span
              title="Probability below 55%: shown for information, not counted in the day summary"
              className="rounded-full bg-zinc-500/20 px-2 py-0.5 text-[10px] font-semibold text-zinc-300 ring-1 ring-zinc-400/30"
            >
              Below 55%
            </span>
          )}
          <span title={style.hint} className={["rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1", style.tag].join(" ")}>
            {style.label}
          </span>
          {p.odds_source === "manual" && (
            <button
              onClick={clearManual}
              title="Odds entered by hand. Click to clear them and enter again"
              className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-500/30 transition hover:bg-violet-500/25"
            >
              Manual odds ✕
            </button>
          )}
          {p.odds_source === "soccerway" && (
            <a
              href={p.odds_check.soccerway_url ?? undefined}
              target="_blank"
              rel="noreferrer"
              title="1xBet odds from Soccerway, the source of the data files. Click to open the match's odds page"
              className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 ring-1 ring-emerald-500/30 transition hover:bg-emerald-500/20"
            >
              Soccerway ↗
            </a>
          )}
          {p.odds_source === "api" && (
            <span
              title={
                p.odds_check.soccerway_found
                  ? "1xBet has no odds for this match on Soccerway: these are API-Football's, the favourite may differ from your data"
                  : "Match not found on Soccerway: these are API-Football's odds, the favourite may differ from your data"
              }
              className="rounded-full bg-orange-500/10 px-2 py-0.5 text-[10px] font-semibold text-orange-300 ring-1 ring-orange-500/30"
            >
              API odds
            </span>
          )}
          {p.has_odds && p.safe != null && (
            <span
              title={p.safe ? "Clear favourite, unlikely to switch" : "Favourite odds above 2.15: the favourite may switch before kick-off"}
              className={[
                "rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1",
                p.safe ? "bg-sky-500/10 text-sky-300 ring-sky-500/30" : "bg-orange-500/10 text-orange-300 ring-orange-500/30",
              ].join(" ")}
            >
              {p.safe ? "Safe" : "Dangerous"}
            </span>
          )}
        </div>
      </div>

      {p.result && (
        <div
          className={[
            "mb-3 flex items-center justify-center gap-2 rounded-lg py-2 text-lg font-black uppercase tracking-widest shadow-lg",
            p.result === "won"
              ? "bg-emerald-500 text-emerald-950 shadow-emerald-500/30"
              : "bg-rose-500 text-rose-950 shadow-rose-500/30",
          ].join(" ")}
        >
          {p.result === "won" ? "✓ Won" : "✗ Lost"}
        </div>
      )}

      {p.odds_check.favourite_conflict && p.odds_check.api_market && (
        <div className="mb-2 rounded-lg bg-rose-500/10 px-2 py-1 text-[11px] text-rose-300 ring-1 ring-rose-500/30">
          API-Football names the other favourite ({p.odds_check.api_market.w1.toFixed(2)} /{" "}
          {p.odds_check.api_market.x.toFixed(2)} / {p.odds_check.api_market.w2.toFixed(2)}): the prediction uses Soccerway's
        </div>
      )}
      {p.has_odds ? (
        <>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className={["rounded-lg px-2 py-0.5 font-mono text-sm font-bold text-zinc-950", style.chip].join(" ")}>{p.code}</span>
            <span className="font-semibold text-white">{p.label}</span>
            <span className="font-mono text-sm text-zinc-300 tabular">@ {p.odds?.toFixed(2)}</span>
          </div>
          <div
            className="mt-2.5 flex items-center gap-2 text-[11px]"
            title="Mean of the pattern's fit % (weighted by the pattern's strength) and the bookmaker's chance"
          >
            <span className="text-zinc-400">Probability</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
              <div className={["h-full rounded-full", style.bar].join(" ")} style={{ width: `${Math.min(p.probability ?? 0, 100)}%` }} />
            </div>
            <span className="font-semibold text-white tabular">{p.probability?.toFixed(1)}%</span>
          </div>
          <div className="mt-1 text-[10px] text-zinc-500 tabular">
            ({p.pattern_coef === 1 ? "" : `${p.pattern_coef} × `}pattern {p.pattern.pct.toFixed(1)}% +{" "}
            {p.odds_source === "manual" ? "1/odds" : "bookmaker"} {p.bookmaker_probability?.toFixed(1)}%) / 2
          </div>
        </>
      ) : (
        <div className="space-y-2">
          <div className="text-sm text-zinc-300">
            Pick: <span className="font-semibold text-white">{side}</span>
            <span className="ml-2 text-xs text-zinc-500">· no odds, enter them by hand</span>
            {p.odds_check.soccerway_url && (
              <a
                href={p.odds_check.soccerway_url}
                target="_blank"
                rel="noreferrer"
                className="ml-2 text-xs text-emerald-300 hover:underline"
              >
                Soccerway ↗
              </a>
            )}
          </div>
          {p.options && <ManualOddsForm match={match} options={p.options} onChanged={onChanged} />}
        </div>
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/5 pt-2 text-[11px] text-zinc-400">
        <span title="The round fits this pattern exactly when the pick comes in">
          Pattern <span className="font-mono font-semibold text-indigo-200">{p.pattern.text}</span>
          <span className="ml-1 tabular">
            · fits {p.pattern.pct.toFixed(0)}% ({p.pattern.positive}/{p.pattern.total}
            {p.reconstructed ? " earlier rounds" : ""})
          </span>
        </span>
        <span
          className="tabular"
          title={
            p.reconstructed
              ? "Rebuilt from the round's final split by taking this match's result back out"
              : "The round's other matches in the data file"
          }
        >
          Before: <span className="text-emerald-300">{p.before.wins}</span> W ·{" "}
          <span className="text-rose-300">{p.before.not_wins}</span> NW
          {p.reconstructed && <span className="ml-1 text-zinc-500">(rebuilt)</span>}
        </span>
        {p.market && (
          <span className="font-mono tabular">
            {p.bookmaker}: {p.market.w1.toFixed(2)} / {p.market.x.toFixed(2)} / {p.market.w2.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}

export default function MatchCard({ match, onChanged }: { match: LastMatch; onChanged: () => void }) {
  const showScore = match.phase === "live" || match.phase === "finished";
  const isDecider = match.round_status?.state === "open";
  // Low-probability predictions stay greyed out: no green / red card for them
  const result =
    match.prediction && !match.prediction.risky && !match.prediction.pending_rebuild && !match.prediction.low_probability
      ? match.prediction.result
      : null;
  return (
    <article
      className={[
        "group grid gap-4 rounded-2xl border bg-zinc-900/60 p-4 shadow-lg shadow-black/10 backdrop-blur transition",
        "hover:bg-zinc-900/80 sm:grid-cols-[72px_1fr_300px] sm:items-center",
        result === "won"
          ? "border-2 border-emerald-500/70 bg-emerald-950/30"
          : result === "lost"
            ? "border-2 border-rose-500/70 bg-rose-950/30"
            : match.phase === "live"
              ? "border-rose-500/30 hover:border-white/20"
              : isDecider
                ? "border-amber-500/20 hover:border-white/20"
                : "border-white/10 hover:border-white/20",
      ].join(" ")}
    >
      <TimeColumn match={match} />

      <div className="min-w-0 space-y-3">
        <div className="flex items-center gap-2 text-xs text-zinc-400">
          {match.league.flag ? (
            <img src={match.league.flag} alt="" className="h-3 w-4 rounded-[2px] object-cover" />
          ) : (
            <Logo src={match.league.logo} name={match.league.name} size={14} />
          )}
          <span className="truncate font-medium">{match.league.name}</span>
        </div>
        <div className="space-y-2 text-[15px]">
          <TeamRow team={match.home} opponent={match.away} showScore={showScore} />
          <TeamRow team={match.away} opponent={match.home} showScore={showScore} />
        </div>
        {match.prediction && <PredictionPanel prediction={match.prediction} match={match} onChanged={onChanged} />}
      </div>

      <RoundPanel match={match} />
    </article>
  );
}
