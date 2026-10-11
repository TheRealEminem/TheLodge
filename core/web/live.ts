// Keeping screens fresh. The server counts every event any module publishes (GET /api/changes); the app
// polls that every 2 seconds while visible (and right after it changes something itself), and useLive()
// refetches whenever it moves. So a task created by the notes module shows up in the tasks badge without
// either module knowing about the other.
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { CHANGED_EVENT, api } from "./api";

let seq = 0;
const listeners = new Set<() => void>();
let started = false;

async function check() {
  try {
    const next = (await api.changes(seq)).seq;
    if (next !== seq) {
      seq = next;
      listeners.forEach((l) => l());
    }
  } catch {
    /* server restarting: try again next tick */
  }
}

export function startChangeFeed() {
  if (started) return;
  started = true;
  const tick = async () => {
    if (document.visibilityState === "visible") await check();
    setTimeout(tick, 2000);
  };
  void tick();
  window.addEventListener(CHANGED_EVENT, () => void check());
  document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && void check());
}

/** A number that changes whenever anything changed on the server. */
export function useChanges(): number {
  return useSyncExternalStore(
    (on) => {
      listeners.add(on);
      return () => listeners.delete(on);
    },
    () => seq,
  );
}

/** Loads data now, and again whenever the server reports a change (or `deps` change). */
export function useLive<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const changes = useChanges();
  const loadRef = useRef(load);
  loadRef.current = load;
  const reload = useCallback(
    () =>
      loadRef.current().then(
        (d) => {
          setData(d);
          setError(null);
        },
        (e: Error) => setError(e.message),
      ),
    [],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => void reload(), [changes, reload, ...deps]);
  return { data, error, reload, setData };
}
