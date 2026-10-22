import { useEffect, useRef, useState } from "react";
import identity from "../../app.json";
import { api } from "./api";
import { useChanges } from "./live";

export type ThemePref = "system" | "light" | "dusk";
const KEY = `${identity.id}.theme`;
const SETTING = "core.appearance";

const valid = (v: unknown): v is ThemePref => v === "system" || v === "light" || v === "dusk";

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dusk" ? v : "system";
  } catch {
    return "system";
  }
}

function remember(p: ThemePref) {
  try {
    localStorage.setItem(KEY, p);
  } catch {
    /* ignore */
  }
}

const systemDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

/**
 * Light ("Day") by day, dusk after dark: follows the OS unless you pick one. The choice is a setting
 * (core.appearance), so it's shared with the other family apps on this Mac; the browser keeps a copy so the first
 * paint is already right.
 */
export function useTheme() {
  const [pref, setPrefState] = useState<ThemePref>(read);
  const [sysDark, setSysDark] = useState(systemDark);
  const changes = useChanges();
  const synced = useRef(false);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const on = () => setSysDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  // Follow the setting, which another family app may have changed. The first time, a choice this browser made
  // before the setting existed is kept rather than reset to "system".
  useEffect(() => {
    let cancelled = false;
    api
      .settings()
      .then((s) => {
        const stored = s.values[SETTING];
        if (cancelled || !valid(stored)) return;
        const local = read();
        if (!synced.current && stored === "system" && local !== "system") {
          void api.putSettings({ [SETTING]: local }).catch(() => undefined);
        } else if (stored !== local) {
          remember(stored);
          setPrefState(stored);
        }
        synced.current = true;
      })
      .catch(() => undefined); // signed out, or the server is restarting: the browser's copy stands
    return () => {
      cancelled = true;
    };
  }, [changes]);

  const dusk = pref === "dusk" || (pref === "system" && sysDark);

  useEffect(() => {
    document.documentElement.dataset.theme = dusk ? "dusk" : "light";
    // The window's color is the page's own background, from the identity's tokens.
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  }, [dusk]);

  const setPref = (p: ThemePref) => {
    setPrefState(p);
    remember(p);
    void api.putSettings({ [SETTING]: p }).catch(() => undefined);
  };

  return { pref, setPref, dusk };
}
