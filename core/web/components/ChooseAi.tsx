// "Where should AI run?" The Mac's line first, then three choices with the one that suits this Mac marked. Used by the
// first-run screens and by the card an existing install sees in Settings → AI.
import { useState } from "react";
import { api } from "../api";
import type { AiPath, ProviderId, SetupState } from "../api";
import { SecretSetting } from "./blocks";
import { AlertIcon, CheckIcon, CloudIcon, LaptopIcon, SparkleIcon } from "./icons";
import { OllamaSetup } from "./OllamaSetup";
import { Select, Spinner } from "./ui";
import { useLive } from "../live";
import { useSettings, useShell } from "../shell";

const CLOUD: { id: ProviderId; label: string }[] = [
  { id: "anthropic", label: "Claude (Anthropic)" },
  { id: "gemini", label: "Google Gemini" },
  { id: "openai", label: "OpenAI" },
  { id: "deepseek", label: "DeepSeek" },
];

const CHOICES: { id: AiPath; title: string; use: string; icon: typeof CloudIcon; body: string }[] = [
  { id: "local", title: "On this Mac", use: "Use this Mac", icon: LaptopIcon, body: "Private and free. Everything runs here and nothing you write is sent anywhere. A model that fits in memory reads long documents less carefully than a cloud AI does." },
  { id: "mixed", title: "Mixed", use: "Use a mix", icon: SparkleIcon, body: "Most jobs run here. The careful ones, like reading a long document, use a cloud AI and your key. Only that text is sent." },
  { id: "cloud", title: "A cloud AI", use: "Use a cloud AI", icon: CloudIcon, body: "The best results. Text you add is sent to the provider you pick, with your key." },
];

export function macLine(s: SetupState): string {
  const a = s.advice;
  return [a.chip, `${a.ram_gb} GB memory`, `${a.disk_free_gb} GB free`].filter(Boolean).join(" · ");
}

/** Where each job will run, and whether it's ready or says plainly what it needs. */
function JobList({ state }: { state: SetupState }) {
  if (!state.jobs.length) return null;
  return (
    <ul className="mt-4 divide-y divide-line rounded-lg border border-line">
      {state.jobs.map((j) => (
        <li key={`${j.module}.${j.job}`} className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 px-4 py-3">
          <div className="min-w-0">
            <div className="text-label font-medium">{j.label}</div>
            <div className="text-hint text-ink-soft">{j.ready ? `${j.provider_label}${j.model ? ` · ${j.model}` : ""}` : j.reason}</div>
          </div>
          {j.ready ? <CheckIcon size={16} className="mt-1 shrink-0 text-forest-deep" /> : <AlertIcon size={16} className="mt-1 shrink-0 text-trail-deep" />}
        </li>
      ))}
    </ul>
  );
}

export function ChooseAi({ onChosen, skippable }: { onChosen?: (path: AiPath) => void; skippable?: () => void }) {
  const { toast } = useShell();
  const { hints, save } = useSettings();
  const { data: state, setData, reload } = useLive<SetupState>(api.setup);
  const [picked, setPicked] = useState<AiPath | null>(null);
  const [cloud, setCloud] = useState<ProviderId>("anthropic");
  const [busy, setBusy] = useState(false);
  if (!state) return <div className="py-6"><Spinner className="text-ink-faint" /></div>;

  const path = picked ?? (state.path || state.recommended);
  const keyed = state.providers.find((p) => p.id === cloud)?.ready ?? false;
  const apply = async () => {
    setBusy(true);
    try {
      setData(await api.setupPath(path, path === "local" ? "" : cloud));
      onChosen?.(path);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="text-label font-medium">{macLine(state)}</div>
      {state.advice.notes.map((n) => <p key={n} className="mt-1 text-hint text-ink-soft">{n}</p>)}
      <div role="radiogroup" aria-label="Where should AI run?" className="mt-4 grid gap-2.5">
        {CHOICES.map((c) => {
          const on = path === c.id;
          return (
            <button
              key={c.id}
              role="radio"
              aria-checked={on}
              className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-left transition-colors ${on ? "border-forest bg-forest-soft/40" : "border-line hover:bg-surface-subtle"}`}
              onClick={() => setPicked(c.id)}
            >
              <c.icon size={18} className="mt-0.5 shrink-0 text-ink-soft" />
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2 text-label font-semibold">
                  {c.title}
                  {state.recommended === c.id && <span className="chip bg-forest-soft text-forest-deep">Recommended for this Mac</span>}
                </span>
                <span className="mt-0.5 block text-hint text-ink-soft">{c.body}</span>
              </span>
            </button>
          );
        })}
      </div>

      {path === "local" && <div className="mt-2"><OllamaSetup onReady={() => void reload()} /></div>}
      {path !== "local" && (
        <div className="mt-4 space-y-3">
          <Select label="Which cloud AI" size="sm" className="w-full sm:w-64" value={cloud} options={CLOUD.map((c) => ({ value: c.id, label: c.label }))} onChange={(v) => setCloud(v as ProviderId)} />
          <SecretSetting label={`${CLOUD.find((c) => c.id === cloud)?.label} API key`} hint={hints[`ai.${cloud}_api_key`]}
            onSave={(x) => void save({ [`ai.${cloud}_api_key`]: x }).then(() => reload())} />
          <p className="text-hint text-ink-faint">Saved on this Mac, shared with your other family apps, and never shown again.</p>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button className="btn btn-md btn-primary" disabled={busy || (path !== "local" && !keyed)} onClick={() => void apply()}>
          {busy ? <Spinner /> : <CheckIcon size={16} />} {CHOICES.find((c) => c.id === path)?.use}
        </button>
        {skippable && <button className="btn btn-md btn-ghost" onClick={skippable}>Decide later</button>}
        {path !== "local" && !keyed && <span className="text-hint text-ink-soft">Add the key first.</span>}
      </div>
      {state.path && <JobList state={state} />}
    </div>
  );
}
