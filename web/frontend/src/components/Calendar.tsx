import {
  addMonths, eachDayOfInterval, format, isSameDay, isSameMonth, isToday, subMonths,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { calendarRange, dayKey } from "../dates";
import type { LastMatch } from "../types";

const WEEKDAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

interface Props {
  month: Date;
  selected: Date;
  byDay: Map<string, LastMatch[]>;
  onMonthChange: (month: Date) => void;
  onSelect: (day: Date) => void;
}

export default function Calendar({ month, selected, byDay, onMonthChange, onSelect }: Props) {
  const { start, end } = calendarRange(month);
  const days = eachDayOfInterval({ start, end });

  return (
    <div className="rounded-2xl border border-white/10 bg-zinc-900/60 p-4 shadow-xl shadow-black/20 backdrop-blur">
      <div className="mb-4 flex items-center justify-between">
        <button
          onClick={() => onMonthChange(subMonths(month, 1))}
          className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/5 hover:text-white"
          aria-label="Previous month"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="text-sm font-semibold tracking-wide">{format(month, "MMMM yyyy")}</div>
        <button
          onClick={() => onMonthChange(addMonths(month, 1))}
          className="rounded-lg p-2 text-zinc-400 transition hover:bg-white/5 hover:text-white"
          aria-label="Next month"
        >
          <ChevronRight size={18} />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-medium uppercase tracking-wider text-zinc-500">
        {WEEKDAYS.map((d) => <div key={d} className="pb-2">{d}</div>)}
      </div>

      <div className="grid grid-cols-7 gap-1">
        {days.map((day) => {
          const matches = byDay.get(dayKey(day)) ?? [];
          const deciders = matches.filter((m) => m.round_status?.state === "open").length;
          const live = matches.some((m) => m.phase === "live");
          const isSelected = isSameDay(day, selected);
          const inMonth = isSameMonth(day, month);
          return (
            <button
              key={day.toISOString()}
              onClick={() => onSelect(day)}
              className={[
                "relative flex aspect-square flex-col items-center justify-center rounded-xl text-sm transition",
                isSelected
                  ? "bg-emerald-500 font-semibold text-zinc-950 shadow-lg shadow-emerald-500/30"
                  : "hover:bg-white/5",
                !isSelected && !inMonth ? "text-zinc-600" : "",
                !isSelected && isToday(day) ? "ring-1 ring-emerald-400/60 ring-inset" : "",
              ].join(" ")}
            >
              <span className="tabular">{format(day, "d")}</span>
              {matches.length > 0 && (
                <span
                  className={[
                    "mt-0.5 rounded-full px-1.5 text-[10px] font-semibold leading-4 tabular",
                    isSelected ? "bg-zinc-950/20 text-zinc-950" : "bg-white/10 text-zinc-300",
                  ].join(" ")}
                >
                  {matches.length}
                </span>
              )}
              {deciders > 0 && (
                <span
                  className={[
                    "absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full",
                    isSelected ? "bg-zinc-950" : "bg-amber-400",
                    live ? "animate-pulse" : "",
                  ].join(" ")}
                />
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-4 flex items-center gap-4 border-t border-white/5 pt-3 text-[11px] text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="rounded-full bg-white/10 px-1.5 leading-4 text-zinc-300">3</span> last matches
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" /> has deciders
        </span>
      </div>
    </div>
  );
}
