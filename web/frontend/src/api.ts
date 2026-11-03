import type { LastMatch, Meta, SyncState } from "./types";

const toUnix = (date: Date) => Math.floor(date.getTime() / 1000);

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `${response.status} ${response.statusText}`);
  }
  return response.json();
}

export const fetchLastMatches = (start: Date, end: Date) =>
  request<LastMatch[]>(`/api/last-matches?start=${toUnix(start)}&end=${toUnix(end)}`);

export const fetchMeta = () => request<Meta>("/api/meta");

export const startSync = () => request<SyncState>("/api/sync", { method: "POST" });

export const fetchSync = () => request<SyncState>("/api/sync");

/** force: read Soccerway's odds again for every match shown, however fresh (the Refresh button). */
export const fetchOdds = (start: Date, end: Date, force = false) =>
  request<{ fetched: number; errors: string[] }>(
    `/api/odds?start=${toUnix(start)}&end=${toUnix(end)}${force ? "&force=true" : ""}`,
    { method: "POST" },
  );

export const saveManualOdds = (fixtureId: number, favourite: "home" | "away", odds: number) =>
  request<{ saved: boolean }>(`/api/manual-odds/${fixtureId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ favourite, odds }),
  });

export const deleteManualOdds = (fixtureId: number) =>
  request<{ deleted: boolean }>(`/api/manual-odds/${fixtureId}`, { method: "DELETE" });

export const refreshRange = (start: Date, end: Date) =>
  request<{ updated: number }>(`/api/refresh?start=${toUnix(start)}&end=${toUnix(end)}`, { method: "POST" });
