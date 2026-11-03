import { endOfMonth, endOfWeek, format, startOfMonth, startOfWeek } from "date-fns";

/** Local calendar day of a date, used to group matches by the day the user sees. */
export const dayKey = (date: Date) => format(date, "yyyy-MM-dd");

/** First and last moment of the 6-week style grid shown for a month (weeks start on Monday). */
export function calendarRange(month: Date) {
  return {
    start: startOfWeek(startOfMonth(month), { weekStartsOn: 1 }),
    end: endOfWeek(endOfMonth(month), { weekStartsOn: 1 }),
  };
}
