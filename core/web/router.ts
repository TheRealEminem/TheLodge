// Navigation is the URL hash: "#/notes/3f2a…". No router library: one hook, one function, one matcher.
import { useCallback, useMemo, useSyncExternalStore } from "react";

const raw = () => decodeURI(location.hash.replace(/^#\/?/, ""));
const current = () => raw().split("?")[0];

const subscribe = (on: () => void) => {
  window.addEventListener("hashchange", on);
  return () => window.removeEventListener("hashchange", on);
};

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
    location.replace(`#/${path}${q ? `?${q}` : ""}`);
  }, []);
  return [params, set];
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
