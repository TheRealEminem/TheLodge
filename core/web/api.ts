// The host's API client. Each module has its own small client next to its views (modules/<id>/web/api.ts),
// built on request() and json() from here.

/** Fired when the server says we need to sign in (installs with an access token only). */
export const AUTH_EVENT = "app:auth-required";
/** Fired after this app changes something on the server, so screens refresh at once instead of on the next poll. */
export const CHANGED_EVENT = "app:changed";

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, { credentials: "same-origin", ...init });
  if (res.status === 401 && !path.startsWith("/login")) window.dispatchEvent(new Event(AUTH_EVENT));
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  if (init?.method && init.method !== "GET") window.dispatchEvent(new Event(CHANGED_EVENT)); // see live.ts
  return res.status === 204 ? (undefined as T) : res.json();
}

export const json = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export interface AppInfo {
  id: string;
  name: string;
  tagline: string;
  version: string;
  modules: { id: string; name: string }[];
  auth_required: boolean;
  /** Lockdown is on: nothing leaves this computer (core/server/lockdown.py). */
  lockdown: boolean;
  /** False until the first-run screens have been finished (or skipped); an install that was already in use starts true. */
  setup_done: boolean;
}

/** A thing's latest background job, as the server reports it next to the thing. */
export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "waiting" | "done" | "error";
  stage: string | null;
  wait_reason: string | null;
  error: string | null;
  updated_at: string;
}

/** Something in another module, described by that module. */
export interface Linked {
  ref: string;
  module: string;
  id: string;
  title: string;
  href: string;
  kind: string;
  direction: "to" | "from";
}

export interface SearchGroup {
  module: string;
  module_name: string;
  hits: { ref: string; id: string; title: string; snippet: string; href: string }[];
}

export type SettingValue = string | number | boolean | string[];
export interface SettingsState {
  values: Record<string, SettingValue>;
  secret_hints: Record<string, string | null>;
}

export type ProviderId = "ollama" | "anthropic" | "openai" | "gemini" | "deepseek" | "custom";
export interface ProviderInfo {
  id: ProviderId;
  label: string;
  kind: "local" | "cloud" | "custom";
  ready: boolean; // keyed (or reachable, for Ollama) and configured
  reason: string;
}

/** Running inside the Mac app's own window (rather than a browser): it can be asked to quit, or to show a file. */
type AppBridge = { postMessage: (message: string) => void };
const bridge = (window as unknown as { webkit?: { messageHandlers?: { app?: AppBridge } } }).webkit?.messageHandlers?.app;
export const inApp = !!bridge;
export const quitApp = () => bridge?.postMessage("quit");
export const revealInFinder = (path: string) => bridge?.postMessage(`reveal:${path}`);

/** Where the Mac app's updates stand (Updater.report in mac/), sent by its window as an "app-updates" event. */
export interface UpdateReport {
  enabled: boolean;
  current: string;
  state: "idle" | "checking" | "up-to-date" | "offline" | "available" | "downloading" | "installing" | "going-back" | "failed";
  version?: string;
  progress?: number | null;
  error?: string;
  prerelease?: boolean;
  beta: boolean;
  skipped?: string | null;
  previous?: string | null;
  working: boolean;
  checked_at?: string | null;
}
export type UpdateCommand = "get" | "check" | "install" | "skip" | "unskip" | "beta-on" | "beta-off" | "go-back" | "try-again";
export const sendUpdates = (what: UpdateCommand) => bridge?.postMessage(`updates:${what}`);

/** A family app installed on this Mac (core/server/family.py). */
export interface FamilyApp {
  id: string;
  name: string;
  version: string;
  running: boolean;
  offers: string[];
  seen_at: string;
  self: boolean;
}
export interface FamilyStatus {
  enabled: boolean;
  folder: string | null;
  sharing: boolean;
  apps: FamilyApp[];
}

/** Someone from the people directory (core/server/people.py): you as "core:me", or a module's or family app's ref. */
export interface Person {
  ref: string;
  name: string;
  email: string | null;
  detail: string | null;
  module: string; // the module that knows them, "core" for you, "family" for another family app
}
export interface PeopleResult {
  people: Person[];
  /** How to see people another family app knows, when it's closed ("Open The Lodge to see this here."). */
  note: string | null;
}
/** What a PersonPicker gives back: a ref from the directory, or null for a name typed in by hand. */
export interface PersonChoice {
  ref: string | null;
  name: string;
}

/** What this Mac can do (core/server/resources.py): its memory, disk and chip, and the path that suits it. */
export interface SystemInfo {
  snapshot: { chip: string; ram_total_gb: number; ram_available_gb: number; disk_free_gb: number; memory_pressure: number };
  advice: { verdict: "local" | "mixed" | "cloud"; chip: string; ram_gb: number; disk_free_gb: number; notes: string[] };
}

/** Ollama on this Mac (core/server/ollama_setup.py). */
export interface OllamaStatus {
  can_install: boolean;
  installed: boolean;
  reachable: boolean;
  models: string[];
  using: string;
  recommended: string;
  locked: boolean;
  install: { active: boolean; status: string; progress: number | null; error: string | null } | null;
  pull: { model: string; active: boolean; status: string; progress: number | null; error: string | null } | null;
}

/** The first-run screens' data (core/server/setup.py). */
export interface SetupJob {
  module: string;
  job: string;
  label: string;
  hint: string;
  weight: "light" | "heavy";
  provider: string;
  provider_label: string;
  model: string;
  ready: boolean;
  reason: string;
  local: boolean;
}
export type AiPath = "local" | "mixed" | "cloud";
export interface SetupState {
  done: boolean;
  path: AiPath | "";
  recommended: AiPath;
  snapshot: SystemInfo["snapshot"];
  advice: SystemInfo["advice"];
  jobs: SetupJob[];
  providers: ProviderInfo[];
}

export interface BackupItem {
  name: string;
  kind: "auto" | "manual" | "before-restore" | "before-update";
  created_at: string;
  bytes: number;
}

export const api = {
  app: () => request<AppInfo>("/app"),
  auth: () => request<{ required: boolean; ok: boolean }>("/auth"),
  login: (token: string) => request<{ ok: true }>("/login", json("POST", { token })),
  logout: () => request<{ ok: true }>("/logout", json("POST")),
  shutdown: () => request<{ ok: true }>("/shutdown", json("POST")),
  changes: (since: number) => request<{ seq: number; names: string[] }>(`/changes?since=${since}`),

  backups: () => request<{ items: BackupItem[]; folder: string }>("/backups"),
  backUpNow: () => request<BackupItem>("/backups", json("POST")),
  restoreBackup: (name: string) => request<{ restored: string; kept: string; counts: Record<string, number> }>(`/backups/${name}/restore`, json("POST")),
  deleteBackup: (name: string) => request<void>(`/backups/${name}`, { method: "DELETE" }),
  exportAll: () => request<{ name: string; folder: string; bytes: number; counts: Record<string, Record<string, number>> }>("/export", json("POST")),

  settings: () => request<SettingsState>("/settings"),
  putSettings: (changes: Record<string, SettingValue>) => request<SettingsState>("/settings", json("PUT", changes)),
  family: () => request<FamilyStatus>("/family"),
  providers: () => request<ProviderInfo[]>("/ai/providers"),
  providerModels: (id: ProviderId) => request<{ models: string[] }>(`/ai/providers/${id}/models`),
  providerTest: (id: ProviderId) => request<{ message: string }>(`/ai/providers/${id}/test`, json("POST")),

  setup: () => request<SetupState>("/setup"),
  setupPath: (path: AiPath, cloud = "") => request<SetupState>("/setup/path", json("PUT", { path, cloud })),
  setupDone: () => request<{ ok: true }>("/setup/done", json("POST")),
  setupReopen: () => request<{ ok: true }>("/setup/reopen", json("POST")),
  system: () => request<SystemInfo>("/system"),
  ollama: () => request<OllamaStatus>("/ollama"),
  ollamaInstall: () => request<{ started: boolean }>("/ollama/install", json("POST")),
  ollamaPull: (model = "") => request<{ started: boolean }>("/ollama/pull", json("POST", { model })),

  search: (q: string) => request<SearchGroup[]>(`/search?q=${encodeURIComponent(q)}`),
  people: (q: string, limit = 8) => request<PeopleResult>(`/people?q=${encodeURIComponent(q)}&limit=${limit}`),
  links: (ref: string) => request<Linked[]>(`/links?ref=${encodeURIComponent(ref)}`),
  jobGo: (id: string, force = false) => request<{ ok: true }>(`/jobs/${id}/go`, json("POST", { force })),
  jobRetry: (id: string) => request<{ ok: true }>(`/jobs/${id}/retry`, json("POST")),
};
