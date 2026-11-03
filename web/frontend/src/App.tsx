import { addDays, endOfDay, format, formatDistanceToNow, isSameMonth, isToday, startOfDay, startOfMonth } from "date-fns";
import { CalendarDays, ChevronLeft, ChevronRight, DatabaseZap, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchLastMatches, fetchMeta, fetchOdds, fetchSync, refreshRange, startSync } from "./api";
import Calendar from "./components/Calendar";
import DaySummary from "./components/DaySummary";
import MatchCard from "./components/MatchCard";
import { calendarRange, dayKey } from "./dates";
import type { LastMatch, Meta } from "./types";

type Filter = "all" | "deciders" | "live";

const POLL_MS = 60_000;

export default function App() {
  const [selected, setSelected] = useState(() => startOfDay(new Date()));
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [matches, setMatches] = useState<LastMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [refreshing, setRefreshing] = useState(false);
  const [updatingOdds, setUpdatingOdds] = useState(false);

  const range = useMemo(() => calendarRange(month), [month]);

  const load = useCallback(async () => {
    try {
      const [list, info] = await Promise.all([fetchLastMatches(range.start, range.end), fetchMeta()]);
      setMatches(list);
      setMeta(info);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => {
    setLoading(true);
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Fetch missing or stale odds of the selected day's predictions, then reload to show them.
  // The server only calls the API for odds older than 30 minutes, so polling this is cheap.
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const { fetched } = await fetchOdds(selected, endOfDay(selected));
        if (fetched && !cancelled) load();
      } catch {
        // odds are optional; the cards still show the pattern and pick side
      }
    };
    run();
    const timer = setInterval(run, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [selected, load]);

  // While a full sync runs, follow its progress and reload once it finishes
  const syncing = meta?.sync.running ?? false;
  useEffect(() => {
    if (!syncing) return;
    const timer = setInterval(async () => {
      const sync = await fetchSync().catch(() => null);
      if (!sync) return;
      setMeta((m) => (m ? { ...m, sync } : m));
      if (!sync.running) load();
    }, 1500);
    return () => clearInterval(timer);
  }, [syncing, load]);

  const byDay = useMemo(() => {
    const map = new Map<string, LastMatch[]>();
    for (const m of matches) {
      // A finished match without a prediction, marked risky, or below 55% has nothing left to show
      const p = m.prediction;
      if (m.phase === "finished" && (!p || p.risky || (!p.pending_rebuild && p.low_probability))) continue;
      const key = dayKey(new Date(m.kickoff * 1000));
      map.set(key, [...(map.get(key) ?? []), m]);
    }
    return map;
  }, [matches]);

  const selectDay = useCallback((day: Date) => {
    setSelected(startOfDay(day));
    setMonth((m) => (isSameMonth(day, m) ? m : startOfMonth(day)));
  }, []);

  // Arrow keys move between days
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === "ArrowLeft") selectDay(addDays(selected, -1));
      if (e.key === "ArrowRight") selectDay(addDays(selected, 1));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, selectDay]);

  const dayMatches = byDay.get(dayKey(selected)) ?? [];
  const deciders = dayMatches.filter((m) => m.round_status?.state === "open");
  const live = dayMatches.filter((m) => m.phase === "live");
  const shown = filter === "deciders" ? deciders : filter === "live" ? live : dayMatches;

  const onSync = async () => {
    try {
      const sync = await startSync();
      setMeta((m) => (m ? { ...m, sync } : m));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const onRefreshDay = async () => {
    setRefreshing(true);
    try {
      await refreshRange(selected, endOfDay(selected));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    } finally {
      setRefreshing(false);
    }
    // Then Soccerway's odds of the matches shown that kick off within 2 hours or have started
    // (after the scores, which decide what is shown); the new scores are already on screen meanwhile
    setUpdatingOdds(true);
    try {
      const { errors } = await fetchOdds(selected, endOfDay(selected), true);
      await load();
      if (errors.length) setError(`Odds: ${errors.join("; ")}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUpdatingOdds(false);
    }
  };

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:py-10">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="grid h-10 w-10 place-items-center rounded-xl bg-gradient-to-br from-emerald-400 to-emerald-600 shadow-lg shadow-emerald-500/30">
            <span className="h-4 w-4 rounded-full border-[3px] border-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight">BeatBet</h1>
            <p className="text-xs text-zinc-500">Single last matches of each round</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden text-right text-xs text-zinc-500 sm:block">
            {meta?.sync.running ? (
              <>
                <div className="text-zinc-300">
                  Syncing {meta.sync.done}/{meta.sync.total}
                </div>
                <div className="max-w-48 truncate">{meta.sync.current}</div>
              </>
            ) : meta?.last_synced_at ? (
              <>
                <div className="text-zinc-300">{meta.leagues} leagues · {meta.fixtures.toLocaleString()} fixtures</div>
                <div>synced {formatDistanceToNow(meta.last_synced_at * 1000, { addSuffix: true })}</div>
              </>
            ) : (
              <div>Not synced yet</div>
            )}
          </div>
          <button
            onClick={onSync}
            disabled={meta?.sync.running}
            title="Fetch every tracked league's matches from 2 days ago to 10 days ahead (one request per league), then save the odds of their single last matches (one request per match without fresh odds)"
            className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3.5 py-2 text-sm font-medium transition hover:bg-white/10 disabled:opacity-60"
          >
            <DatabaseZap size={16} className={meta?.sync.running ? "animate-pulse text-emerald-400" : ""} />
            {meta?.sync.running ? "Syncing…" : "Sync all"}
          </button>
        </div>
      </header>

      {meta?.sync.running && (
        <div className="mb-6 h-1 overflow-hidden rounded-full bg-white/5">
          <div
            className="h-full bg-emerald-400 transition-all"
            style={{ width: `${(meta.sync.done / Math.max(meta.sync.total, 1)) * 100}%` }}
          />
        </div>
      )}

      {error && (
        <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[340px_1fr]">
        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <Calendar month={month} selected={selected} byDay={byDay} onMonthChange={setMonth} onSelect={selectDay} />
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Last matches" value={dayMatches.length} />
            <Stat label="Deciders" value={deciders.length} tone="amber" />
            <Stat label="Live" value={live.length} tone="rose" />
          </div>
          {meta?.sync.errors.length ? (
            <details className="rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-xs text-rose-200">
              <summary className="cursor-pointer">{meta.sync.errors.length} leagues failed to sync</summary>
              <ul className="mt-2 space-y-1 text-rose-300/80">
                {meta.sync.errors.map((e) => <li key={e}>{e}</li>)}
              </ul>
            </details>
          ) : null}
        </aside>

        <main>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <button
                onClick={() => selectDay(addDays(selected, -1))}
                className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/5 hover:text-white"
                aria-label="Previous day"
              >
                <ChevronLeft size={18} />
              </button>
              <div>
                <h2 className="text-lg font-semibold tracking-tight">{format(selected, "EEEE, d MMMM")}</h2>
                <p className="text-xs text-zinc-500">
                  {isToday(selected) ? "Today · " : ""}
                  {dayMatches.length} last match{dayMatches.length === 1 ? "" : "es"}
                </p>
              </div>
              <button
                onClick={() => selectDay(addDays(selected, 1))}
                className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/5 hover:text-white"
                aria-label="Next day"
              >
                <ChevronRight size={18} />
              </button>
              {!isToday(selected) && (
                <button
                  onClick={() => selectDay(new Date())}
                  className="ml-1 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-zinc-300 transition hover:bg-white/5"
                >
                  Today
                </button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <div className="flex rounded-xl border border-white/10 bg-white/5 p-1 text-xs">
                {(["all", "deciders", "live"] as const).map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={[
                      "rounded-lg px-3 py-1.5 font-medium capitalize transition",
                      filter === f ? "bg-white/10 text-white" : "text-zinc-400 hover:text-white",
                    ].join(" ")}
                  >
                    {f}
                  </button>
                ))}
              </div>
              {updatingOdds && <span className="animate-pulse text-xs text-emerald-300">Updating odds…</span>}
              <button
                onClick={onRefreshDay}
                disabled={refreshing || updatingOdds}
                title="Update scores and statuses of this day (1–2 API requests), then read Soccerway odds again for the matches shown that kick off within 2 hours or have started"
                className="rounded-xl border border-white/10 bg-white/5 p-2 text-zinc-300 transition hover:bg-white/10 disabled:opacity-60"
                aria-label="Refresh day"
              >
                <RefreshCw size={16} className={refreshing ? "animate-spin" : ""} />
              </button>
            </div>
          </div>

          {!loading && <DaySummary matches={dayMatches} />}

          {loading ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-32 animate-pulse rounded-2xl border border-white/5 bg-zinc-900/60" />
              ))}
            </div>
          ) : shown.length ? (
            <div className="space-y-3">
              {shown.map((m) => <MatchCard key={m.fixture_id} match={m} onChanged={load} />)}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-white/10 py-20 text-center">
              <CalendarDays className="mb-3 text-zinc-600" size={32} />
              <p className="font-medium text-zinc-300">
                {dayMatches.length ? "Nothing matches this filter" : "No single last matches on this day"}
              </p>
              <p className="mt-1 text-sm text-zinc-500">
                {meta?.last_synced_at ? "Pick another day in the calendar." : "Run “Sync all” to load fixtures."}
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: "amber" | "rose" }) {
  const color = tone === "amber" ? "text-amber-300" : tone === "rose" ? "text-rose-300" : "text-white";
  return (
    <div className="rounded-xl border border-white/10 bg-zinc-900/60 px-3 py-2.5">
      <div className={`text-xl font-semibold tabular ${color}`}>{value}</div>
      <div className="text-[11px] text-zinc-500">{label}</div>
    </div>
  );
}
