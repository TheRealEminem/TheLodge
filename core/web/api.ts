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
  ready: boolean | null; // null: not in use, so not checked
  reason: string;
}

/** Running inside the Mac app's own window (rather than a browser): it can be asked to quit, or to show a file. */
type AppBridge = { postMessage: (message: string) => void };
const bridge = (window as unknown as { webkit?: { messageHandlers?: { app?: AppBridge } } }).webkit?.messageHandlers?.app;
export const inApp = !!bridge;
export const quitApp = () => bridge?.postMessage("quit");
export const revealInFinder = (path: string) => bridge?.postMessage(`reveal:${path}`);

export const api = {
  app: () => request<AppInfo>("/app"),
  auth: () => request<{ required: boolean; ok: boolean }>("/auth"),
  login: (token: string) => request<{ ok: true }>("/login", json("POST", { token })),
  logout: () => request<{ ok: true }>("/logout", json("POST")),
  shutdown: () => request<{ ok: true }>("/shutdown", json("POST")),
  changes: (since: number) => request<{ seq: number; names: string[] }>(`/changes?since=${since}`),

  settings: () => request<SettingsState>("/settings"),
  putSettings: (changes: Record<string, SettingValue>) => request<SettingsState>("/settings", json("PUT", changes)),
  providers: () => request<ProviderInfo[]>("/ai/providers"),
  providerModels: (id: ProviderId) => request<{ models: string[] }>(`/ai/providers/${id}/models`),
  providerTest: (id: ProviderId) => request<{ message: string }>(`/ai/providers/${id}/test`, json("POST")),

  search: (q: string) => request<SearchGroup[]>(`/search?q=${encodeURIComponent(q)}`),
  links: (ref: string) => request<Linked[]>(`/links?ref=${encodeURIComponent(ref)}`),
  jobGo: (id: string, force = false) => request<{ ok: true }>(`/jobs/${id}/go`, json("POST", { force })),
  jobRetry: (id: string) => request<{ ok: true }>(`/jobs/${id}/retry`, json("POST")),
};
