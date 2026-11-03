import type { FullPrediction, LastMatch } from "../types";

/** Stake in USD per prediction, by the pattern it uses. A default-pattern prediction below
 *  lowProbability % gets lowStake instead. */
const STAKES = [
  { strength: "default", label: "Default", stake: 20, lowStake: 10, lowProbability: 60, dot: "bg-emerald-400" },
  { strength: "weaker", label: "Weaker", stake: 10, lowStake: 10, lowProbability: 0, dot: "bg-amber-400" },
] as const;

type Rule = (typeof STAKES)[number];

const stakeOf = (rule: Rule, p: FullPrediction) =>
  p.probability !== undefined && p.probability < rule.lowProbability ? rule.lowStake : rule.stake;

/** "$20" or "$20 / $10 under 60%" for the table. */
const stakeText = (rule: Rule) =>
  rule.lowStake === rule.stake ? `$${rule.stake}` : `$${rule.stake} / $${rule.lowStake} <${rule.lowProbability}%`;

type Strength = (typeof STAKES)[number]["strength"];

const usd = (value: number, sign = false) =>
  `${sign && value > 0 ? "+" : value < 0 ? "−" : ""}$${Math.abs(value).toFixed(2)}`;

const pct = (value: number | null) => (value === null ? "–" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`);

interface Bet {
  match: LastMatch;
  prediction: FullPrediction;
  stake: number;
  /** Profit of a settled bet, null while open. */
  profit: number | null;
}

/** Day's win / loss counts and flat-stake bets on predictions, by pattern. */
export default function DaySummary({ matches }: { matches: LastMatch[] }) {
  const bets: Bet[] = [];
  for (const match of matches) {
    const p = match.prediction;
    if (!p || p.risky || p.pending_rebuild || p.low_probability) continue;
    const rule = STAKES.find((s) => s.strength === p.strength);
    if (!rule) continue;
    const settled = p.result && p.odds;
    const stake = stakeOf(rule, p);
    bets.push({
      match,
      prediction: p,
      stake,
      profit: settled ? (p.result === "won" ? stake * ((p.odds ?? 0) - 1) : -stake) : null,
    });
  }

  const groups = STAKES.map((rule) => {
    const own = bets.filter((b) => b.prediction.strength === rule.strength);
    const settled = own.filter((b) => b.profit !== null);
    const won = own.filter((b) => b.prediction.result === "won").length;
    const lost = own.filter((b) => b.prediction.result === "lost").length;
    const staked = settled.reduce((sum, b) => sum + b.stake, 0);
    const profit = settled.reduce((sum, b) => sum + (b.profit ?? 0), 0);
    return { ...rule, total: own.length, won, lost, open: own.length - settled.length, staked, profit };
  });

  const settled = bets.filter((b) => b.profit !== null);
  const staked = groups.reduce((sum, g) => sum + g.staked, 0);
  const profit = groups.reduce((sum, g) => sum + g.profit, 0);
  const open = bets.length - settled.length;

  return (
    <div className="mb-4 rounded-2xl border border-emerald-500/20 bg-gradient-to-br from-emerald-500/[0.07] to-transparent p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-emerald-300/80">Day summary</span>
        <span className="text-xs text-zinc-500 tabular">
          {bets.length} prediction{bets.length === 1 ? "" : "s"}
        </span>
      </div>

      {bets.length ? (
        <>
          <div className="overflow-hidden rounded-xl ring-1 ring-white/5">
            <table className="w-full text-xs tabular">
              <thead className="bg-black/30 text-[11px] text-zinc-500">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">Pattern</th>
                  <th className="px-2 py-2 text-right font-medium">Won</th>
                  <th className="px-2 py-2 text-right font-medium">Lost</th>
                  <th className="px-2 py-2 text-right font-medium" title="Not finished yet, or no odds">Open</th>
                  <th className="px-2 py-2 text-right font-medium" title="Won out of won + lost">Hit rate</th>
                  <th className="px-2 py-2 text-right font-medium">Stake</th>
                  <th className="px-3 py-2 text-right font-medium">Result</th>
                </tr>
              </thead>
              <tbody className="bg-black/10">
                {groups.map((g) => (
                  <tr key={g.strength} className="border-t border-white/5">
                    <td className="px-3 py-2">
                      <span className="flex items-center gap-2 text-zinc-300">
                        <span className={`h-2 w-2 rounded-full ${g.dot}`} />
                        {g.label}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right font-semibold text-emerald-300">{g.won}</td>
                    <td className="px-2 py-2 text-right font-semibold text-rose-300">{g.lost}</td>
                    <td className="px-2 py-2 text-right text-zinc-400">{g.open}</td>
                    <td className="px-2 py-2 text-right text-zinc-200">
                      {g.won + g.lost ? `${Math.round((g.won / (g.won + g.lost)) * 100)}%` : "–"}
                    </td>
                    <td className="px-2 py-2 text-right text-zinc-400">{stakeText(g)}</td>
                    <td
                      className={[
                        "px-3 py-2 text-right font-semibold",
                        g.profit > 0 ? "text-emerald-300" : g.profit < 0 ? "text-rose-300" : "text-zinc-400",
                      ].join(" ")}
                    >
                      {g.staked ? usd(g.profit, true) : "–"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-3 rounded-xl bg-black/20 p-3 ring-1 ring-white/5">
            <div className="mb-2 flex items-center justify-between text-[11px]">
              <span className="font-semibold uppercase tracking-wider text-zinc-400">
                Bets · {STAKES.map((s) => `${s.label.toLowerCase()} ${stakeText(s)}`).join(" · ")}
              </span>
              <span className="text-zinc-500 tabular">
                {settled.length} settled{open ? ` · ${open} open` : ""}
              </span>
            </div>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <div
                  className={[
                    "text-3xl font-bold tabular",
                    profit > 0 ? "text-emerald-300" : profit < 0 ? "text-rose-300" : "text-zinc-300",
                  ].join(" ")}
                >
                  {usd(profit, true)}
                </div>
                <div className="text-[11px] text-zinc-500">Day result</div>
              </div>
              <div className="flex gap-5 text-right text-xs tabular">
                <div>
                  <div className="font-semibold text-zinc-200">{usd(staked)}</div>
                  <div className="text-[11px] text-zinc-500">Staked</div>
                </div>
                <div>
                  <div className="font-semibold text-zinc-200">{usd(staked + profit)}</div>
                  <div className="text-[11px] text-zinc-500">Returned</div>
                </div>
                <div>
                  <div className="font-semibold text-zinc-200">{pct(staked ? (profit / staked) * 100 : null)}</div>
                  <div className="text-[11px] text-zinc-500">ROI</div>
                </div>
              </div>
            </div>

            {settled.length > 0 && (
              <ul className="mt-3 space-y-1 border-t border-white/5 pt-2 text-[11px] tabular">
                {settled.map((b) => (
                  <li key={b.match.fixture_id} className="flex items-center justify-between gap-3">
                    <span className="flex min-w-0 items-center gap-1.5 text-zinc-400">
                      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotOf(b.prediction.strength as Strength)}`} />
                      <span className="font-mono text-zinc-300">{b.prediction.code}</span>
                      <span className="truncate">
                        {b.match.home.name} – {b.match.away.name}
                      </span>
                      <span className="shrink-0 text-zinc-500">
                        ${b.stake} @ {b.prediction.odds?.toFixed(2)}
                      </span>
                    </span>
                    <span className={(b.profit ?? 0) > 0 ? "text-emerald-300" : "text-rose-300"}>
                      {usd(b.profit ?? 0, true)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      ) : (
        <p className="text-sm text-zinc-500">No predictions on this day.</p>
      )}
    </div>
  );
}

const dotOf = (strength: Strength) => STAKES.find((s) => s.strength === strength)?.dot ?? "bg-zinc-500";
