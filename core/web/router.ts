// Navigation is the URL hash: "#/notes/3f2a…". No router library: one hook, one function, one matcher.
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

const raw = () => decodeURI(location.hash.replace(/^#\/?/, ""));
const current = () => raw().split("?")[0];

const subscribe = (on: () => void) => {
  window.addEventListener("hashchange", on);
  return () => window.removeEventListener("hashchange", on);
};

// Where you are in your history. Each entry carries its place (history.state.at), so a hash change can tell Back or
// Forward from going somewhere new, and the buttons can tell whether there's anywhere to go.
let at = typeof history.state?.at === "number" ? history.state.at : 0;
let furthest = at;
let returned = false;
const stamp = () => history.replaceState({ ...history.state, at }, "");
stamp();

/** Changes the hash in place, staying on the same history entry. */
const swap = (hash: string) => {
  location.replace(hash);
  stamp();
};

// The filters of pages that asked (keepFilters), so opening one again finds it as you left it. Until the app quits.
const keeping = new Set<string>();
const kept = new Map<string, string>();

window.addEventListener("hashchange", () => {
  const seen = history.state?.at;
  returned = typeof seen === "number" && seen !== at;
  if (typeof seen === "number") {
    at = seen;
  } else {
    furthest = at = at + 1;
    stamp();
    const [path, query] = location.hash.split("?");
    const again = kept.get(path);
    if (!query && again) swap(`${path}?${again}`);
  }
  const [path, query = ""] = location.hash.split("?");
  if (keeping.has(path)) kept.set(path, query);
});

/** Opening this page again, with no filters of its own in the link, brings back the ones it had. */
export function keepFilters(path: string) {
  keeping.add(`#/${path}`);
}

/** Where you are in your history, and the way back and forward through it. `returned()` says the last move was one. */
export function useHistoryPlace() {
  const place = useSyncExternalStore(subscribe, () => `${at}/${furthest}`);
  const [here, end] = place.split("/").map(Number);
  return { at: here, canBack: here > 0, canForward: here < end, returned: () => returned };
}

/** The current path without "#/", e.g. "notes/3f2a…" ("" is Home). */
export function useRoute(): string {
  return useSyncExternalStore(subscribe, current);
}

/**
 * The query part of the hash ("#/crm/people?tier=strong") as URLSearchParams, and a setter that changes some of
 * its keys (null removes one) without adding a history entry. The path itself isn't touched.
 */
export function useQueryParams(): [URLSearchParams, (changes: Record<string, string | null>) => void] {
  const hash = useSyncExternalStore(subscribe, raw);
  const params = useMemo(() => new URLSearchParams(hash.split("?")[1] ?? ""), [hash]);
  const set = useCallback((changes: Record<string, string | null>) => {
    const [path, query = ""] = raw().split("?");
    const next = new URLSearchParams(query);
    for (const [k, v] of Object.entries(changes)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    const q = next.toString();
    swap(`#/${path}${q ? `?${q}` : ""}`);
  }, []);
  return [params, set];
}

/** A filter kept in the address: a value, its default (which the address leaves out), and a setter. */
export function useQueryValue<T extends string>(key: string, fallback: T): [T, (value: T) => void] {
  const [params, set] = useQueryParams();
  return [(params.get(key) as T | null) ?? fallback, useCallback((value: T) => set({ [key]: value === fallback ? null : value }), [set, key, fallback])];
}

/** How many rows a "Show more" list has opened, kept in the address so coming back finds the same place. */
export function useQueryLimit(page: number): [number, (value: number | ((was: number) => number)) => void] {
  const [params, set] = useQueryParams();
  const limit = Number(params.get("shown")) || page;
  return [limit, (value) => {
    const next = typeof value === "function" ? value(limit) : value;
    set({ shown: next === page ? null : String(next) });
  }];
}

/** A search box's text: answers as you type, and reaches the address a moment later. */
export function useQueryText(key = "q", ms = 250): [string, (value: string) => void] {
  const [params, set] = useQueryParams();
  const [text, setText] = useState(() => params.get(key) ?? "");
  useEffect(() => {
    if (text === (params.get(key) ?? "")) return;
    const t = setTimeout(() => set({ [key]: text || null }), ms);
    return () => clearTimeout(t);
  }, [text, params, key, ms, set]);
  return [text, setText];
}

export function navigate(path: string) {
  location.hash = `/${path.replace(/^#?\/?/, "")}`;
}

/** match("notes/:id", "notes/abc") -> { id: "abc" }; null when it doesn't fit. */
export function match(pattern: string, path: string): Record<string, string> | null {
  const want = pattern.split("/").filter(Boolean);
  const have = path.split("/").filter(Boolean);
  if (want.length !== have.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < want.length; i++) {
    if (want[i].startsWith(":")) params[want[i].slice(1)] = have[i];
    else if (want[i] !== have[i]) return null;
  }
  return params;
}
