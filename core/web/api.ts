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
  modules: { id: string; name: string; /** A connection to an outside tool: off until it is set up. */ optional: boolean; active: boolean }[];
  auth_required: boolean;
  /** Lockdown is on: nothing leaves this computer (core/server/lockdown.py). */
  lockdown: boolean;
  /** False until the first-run screens have been finished (or skipped); an install that was already in use starts true. */
  setup_done: boolean;
  /** Which system this is and what the shell can do. */
  computer: PlatformInfo;
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

/** Lockdown (core/server/lockdown.py): nothing leaves this Mac. `parked`: jobs waiting for it to be off. */
export interface LockdownStatus {
  on: boolean;
  parked: number;
}
export const LOCKDOWN = "Lockdown mode is on"; // lockdown.REASON

/** The job is parked until Lockdown is off: it goes ahead by itself then, so there's nothing to press. */
export function heldByLockdown(job: Job | null | undefined): boolean {
  return job?.status === "waiting" && !!job.wait_reason?.startsWith(LOCKDOWN);
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

/** What AI calls cost (core/server/pricing.py). Costs are US dollars; `unknown` counts calls at a price nobody
 * published, which aren't in `cost`; `stopped` counts calls Lockdown stopped, which aren't in `failed`. */
export interface UsageTotals {
  calls: number;
  cost: number;
  failed: number;
  stopped: number;
  unknown: number;
  input_tokens: number;
  output_tokens: number;
}
export interface UsageGroup extends UsageTotals {
  id: string; // a provider id, or a module id ("core" for Settings, "" for calls made outside a job)
  label: string;
}
export interface UsageCall {
  at: string;
  module: string;
  module_label: string;
  job: string;
  call: "complete" | "structured";
  provider: string;
  provider_label: string;
  model: string;
  input_tokens: number | null;
  cached_tokens: number | null;
  output_tokens: number | null;
  cost: number | null; // null: unknown, or a failure that spent nothing
  failed: boolean;
  stopped: boolean; // Lockdown stopped it before anything was sent
  unknown: boolean;
  error: string | null;
}
export interface AIUsage {
  month: UsageTotals & { start: string };
  last_30_days: UsageTotals & { by_provider: UsageGroup[]; by_module: UsageGroup[] };
  recent: UsageCall[];
  prices_checked: string;
}

/** Running inside the app's own window (the Mac app, or the desktop app for Windows and Linux) rather than a
 *  browser. Both shells offer the same bridge; `can()` says what this one can do. */
type AppBridge = { postMessage: (message: string) => void };
const bridge = (window as unknown as { webkit?: { messageHandlers?: { app?: AppBridge } } }).webkit?.messageHandlers?.app;
export const inApp = !!bridge;
export const quitApp = () => bridge?.postMessage("quit");
/** Shows a file or folder in Finder, File Explorer or the file manager (`words.files`). */
export const revealFile = (path: string) => bridge?.postMessage(`reveal:${path}`);

/** Which system this is, and what the app's shell can do (core/server/computer.py). */
export type ShellCan = "quit" | "reveal" | "updates" | "login";
export interface Words {
  /** "this Mac", "this PC" or "this computer" */
  here: string;
  /** "Finder", "File Explorer" or "your file manager" */
  files: string;
  /** "the menu bar" or "the system tray" */
  tray: string;
  /** "the Mac app" or "the desktop app" */
  app: string;
  /** Where apps are opened from: "Applications", "the Start menu" or "your apps menu" */
  apps: string;
  /** "Terminal", "PowerShell" or "a terminal" */
  terminal: string;
}
export interface PlatformInfo {
  os: "mac" | "windows" | "linux";
  words: Words;
  shell: "mac" | "desktop" | null;
  can: ShellCan[];
}
/** The words for this system, set from the app info as it loads (the Mac's until then). Write `On ${words.here}`,
 *  never "this Mac", in anything a person reads. */
export const words: Words = { here: "this Mac", files: "Finder", tray: "the menu bar", app: "the Mac app", apps: "Applications", terminal: "Terminal" };
export let computer: PlatformInfo = { os: "mac", words, shell: null, can: [] };
export function setSystem(info: PlatformInfo | undefined) {
  if (!info) return;
  Object.assign(words, info.words);
  computer = { ...info, words };
}
/** Whether the app's own window can do this here. False in a browser, and for what a platform's shell lacks. */
export const can = (what: ShellCan) => inApp && computer.can.includes(what);
/** A file in a folder the server named, with this system's separator (Windows wants "\\"). */
export const joinPath = (folder: string, name: string) => `${folder}${computer.os === "windows" ? "\\" : "/"}${name}`;
/** "this Mac" → "This Mac", for the start of a sentence. */
export const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);
export const showInAppMenu = (sections: { label: string; path: string }[]) => bridge?.postMessage(`menu:${JSON.stringify(sections)}`);

/** Where the Mac app's updates stand (Updater.report in mac/), sent by its window as an "app-updates" event. */
export interface UpdateReport {
  enabled: boolean;
  current: string;
  state: "idle" | "checking" | "up-to-date" | "offline" | "locked-down" | "available" | "downloading" | "installing" | "going-back" | "failed";
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

/** Whether the Mac app may read your calendar: "unasked" until macOS has asked you, "unavailable" when this app
 *  doesn't use it (mac/Sources/AppHost/CalendarBridge.swift). */
export type CalendarAccess = "full" | "unasked" | "denied" | "restricted" | "write_only" | "unavailable";
/** An event from your Mac's Calendar. start and end carry the Mac's offset; free: it doesn't block time. */
export interface CalendarEvent {
  id: string;
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  calendar: string;
  free: boolean;
}
type CalendarBridge = { postMessage: (message: object) => Promise<unknown> };
const calendarBridge = (window as unknown as { webkit?: { messageHandlers?: { calendar?: CalendarBridge } } }).webkit?.messageHandlers?.calendar;
const askCalendar = <T>(message: object) => calendarBridge!.postMessage(message) as Promise<T>;

/** Your Mac's Calendar, read-only, through the Mac app's window: every account the Calendar app has. null in a browser
 *  (and in an app built before it could). Nothing is kept: each call reads it afresh. */
export const macCalendar = calendarBridge
  ? {
      access: () => askCalendar<{ access: CalendarAccess }>({ ask: "access" }).then((r) => r.access),
      /** macOS asks you, the first time; afterwards it answers for you (System Settings changes it). */
      request: () => askCalendar<{ access: CalendarAccess }>({ ask: "request" }).then((r) => r.access),
      events: (from: Date, to: Date) =>
        askCalendar<{ access: CalendarAccess; events: CalendarEvent[] }>({ ask: "events", from: from.toISOString(), to: to.toISOString() }),
      openSettings: () => askCalendar<unknown>({ ask: "settings" }),
    }
  : null;

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
  advice: { verdict: "local" | "mixed" | "cloud"; chip: string; gpu: string; npu: string; ram_gb: number; disk_free_gb: number; notes: string[] };
}

/** Ollama on this Mac (core/server/ollama_setup.py). */
export interface OllamaStatus {
  can_install: boolean;
  installed: boolean;
  /** Linux: what to run yourself, since the app runs nothing as root. Null elsewhere. */
  install_command: string | null;
  install_page: string | null;
  start_command: string | null;
  reachable: boolean;
  models: string[];
  using: string;
  recommended: string;
  /** A newer model than the one in use, when the catalog has one that suits this computer; null otherwise. */
  suggestion: { model: string; replaces: string } | null;
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

/** Claude's access through the MCP server (core/server/mcp.py). The token itself comes back only inside `setup`, once. */
export interface McpStatus {
  on: boolean;
  hint: string | null;
  url: string;
  tools: { name: string; title: string; module: string; writes: boolean }[];
}
export interface McpSetup {
  claude_code: string;
  claude_desktop: string;
}

export type BackupKind = "auto" | "manual" | "before-restore" | "before-update";
export type BackupSlot = "latest" | "hour" | "day" | "week";

/** One copy on disk. `kind` is its main label; `kinds` all it holds, since the same data is never copied twice. */
export interface BackupFile {
  name: string;
  kind: BackupKind;
  kinds: BackupKind[];
  created_at: string;
  bytes: number;
  update?: string;
}

/** As the list gives it: what it holds, and which restore choices it fills. */
export interface BackupItem extends BackupFile {
  counts: Record<string, number>;
  slots: BackupSlot[];
}

export interface UsageSummary {
  this_month: { cost: number; calls: number; tokens: number; unpriced: number };
  last_month: { cost: number; calls: number; tokens: number; unpriced: number };
  warn_over: number;
  prices_as_of: string;
  by_source: { name: string; calls: number; cost: number; tokens: number }[];
  by_model: { provider: string; model: string; local: boolean; priced: boolean; calls: number; cost: number; tokens_in: number; tokens_out: number }[];
  by_day: { day: string; cost: number; calls: number }[];
}

export const api = {
  app: () => request<AppInfo>("/app"),
  auth: () => request<{ required: boolean; ok: boolean }>("/auth"),
  login: (token: string) => request<{ ok: true }>("/login", json("POST", { token })),
  logout: () => request<{ ok: true }>("/logout", json("POST")),
  shutdown: () => request<{ ok: true }>("/shutdown", json("POST")),
  changes: (since: number) => request<{ seq: number; names: string[] }>(`/changes?since=${since}`),

  backups: () => request<{ items: BackupItem[]; slots: Record<BackupSlot, string | null>; folder: string }>("/backups"),
  backUpNow: () => request<BackupFile>("/backups", json("POST")),
  restoreBackup: (name: string) => request<{ restored: string; kept: string; counts: Record<string, number> }>(`/backups/${name}/restore`, json("POST")),
  deleteBackup: (name: string) => request<void>(`/backups/${name}`, { method: "DELETE" }),
  exportAll: () => request<{ name: string; folder: string; bytes: number; counts: Record<string, Record<string, number>> }>("/export", json("POST")),

  settings: () => request<SettingsState>("/settings"),
  putSettings: (changes: Record<string, SettingValue>) => request<SettingsState>("/settings", json("PUT", changes)),
  family: () => request<FamilyStatus>("/family"),
  mcp: () => request<McpStatus>("/mcp"),
  mcpToken: () => request<McpStatus & { setup: McpSetup }>("/mcp/token", json("POST")),
  mcpOff: () => request<void>("/mcp/token", { method: "DELETE" }),
  providers: () => request<ProviderInfo[]>("/ai/providers"),
  providerModels: (id: ProviderId) => request<{ models: string[] }>(`/ai/providers/${id}/models`),
  usage: () => request<UsageSummary>("/ai/usage"),
  providerTest: (id: ProviderId, model = "") =>
    request<{ message: string }>(`/ai/providers/${id}/test${model ? `?model=${encodeURIComponent(model)}` : ""}`, json("POST")),
  aiUsage: () => request<AIUsage>("/ai/usage"),
  lockdown: () => request<LockdownStatus>("/lockdown"),

  setup: () => request<SetupState>("/setup"),
  setupPath: (path: AiPath, cloud = "") => request<SetupState>("/setup/path", json("PUT", { path, cloud })),
  setupDone: () => request<{ ok: true }>("/setup/done", json("POST")),
  setupReopen: () => request<{ ok: true }>("/setup/reopen", json("POST")),
  system: () => request<SystemInfo>("/system"),
  ollama: () => request<OllamaStatus>("/ollama"),
  ollamaInstall: () => request<{ started: boolean }>("/ollama/install", json("POST")),
  ollamaPull: (model = "") => request<{ started: boolean }>("/ollama/pull", json("POST", { model })),
  ollamaDismissSuggestion: (model: string) => request<{ ok: true }>("/ollama/dismiss-suggestion", json("POST", { model })),

  search: (q: string) => request<SearchGroup[]>(`/search?q=${encodeURIComponent(q)}`),
  people: (q: string, limit = 8) => request<PeopleResult>(`/people?q=${encodeURIComponent(q)}&limit=${limit}`),
  links: (ref: string) => request<Linked[]>(`/links?ref=${encodeURIComponent(ref)}`),
  jobGo: (id: string, force = false) => request<{ ok: true }>(`/jobs/${id}/go`, json("POST", { force })),
  jobRetry: (id: string) => request<{ ok: true }>(`/jobs/${id}/retry`, json("POST")),
};
