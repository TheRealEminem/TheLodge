import { useEffect, useState } from "react";
import identity from "../../app.json";

export type ThemePref = "system" | "light" | "dusk";
const KEY = `${identity.id}.theme`;

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dusk" ? v : "system";
  } catch {
    return "system";
  }
}

const systemDark = () => window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;

/** Light ("Day") by day, dusk after dark: follows the OS unless you pick one. Remembered per browser. */
export function useTheme() {
  const [pref, setPrefState] = useState<ThemePref>(read);
  const [sysDark, setSysDark] = useState(systemDark);

  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const on = () => setSysDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const dusk = pref === "dusk" || (pref === "system" && sysDark);

  useEffect(() => {
    document.documentElement.dataset.theme = dusk ? "dusk" : "light";
    // The window's color is the page's own background, from the identity's tokens.
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", bg);
  }, [dusk]);

  const setPref = (p: ThemePref) => {
    setPrefState(p);
    try {
      localStorage.setItem(KEY, p);
    } catch {
      /* ignore */
    }
  };

  return { pref, setPref, dusk };
}
