// What the host offers every module's views: toasts, confirm dialogs, the theme, who the app is, and settings.
import { createContext, useCallback, useContext } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { AppInfo, SettingValue, SettingsState } from "./api";
import { useLive } from "./live";
import type { ThemePref } from "./theme";

export interface Shell {
  app: AppInfo;
  toast: (text: string, tone?: "success" | "error") => void;
  confirm: (o: { title: string; body: string; confirmLabel: string; tone?: "danger" | "primary" }) => Promise<boolean>;
  theme: { pref: ThemePref; setPref: (p: ThemePref) => void; dusk: boolean };
}

const ShellContext = createContext<Shell | null>(null);

export function ShellProvider({ value, children }: { value: Shell; children: ReactNode }) {
  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}

export function useShell(): Shell {
  const shell = useContext(ShellContext);
  if (!shell) throw new Error("useShell() outside the app shell");
  return shell;
}

/** Settings, live. save() takes dotted keys: save({ "notes.auto_summarize": true }). */
export function useSettings() {
  const { toast } = useShell();
  const { data, setData } = useLive<SettingsState>(api.settings);
  const save = useCallback(
    async (changes: Record<string, SettingValue>) => {
      try {
        setData(await api.putSettings(changes));
        return true;
      } catch (e) {
        toast((e as Error).message, "error");
        return false;
      }
    },
    [setData, toast],
  );
  return {
    values: data?.values ?? null,
    hints: data?.secret_hints ?? {},
    get: <T extends SettingValue>(key: string) => data?.values[key] as T | undefined,
    save,
  };
}
