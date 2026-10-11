// Settings: the host's own sections (appearance, you, AI, the app), then one section per module.
import { useEffect, useState } from "react";
import { api, inApp, quitApp } from "../api";
import type { ProviderId, ProviderInfo } from "../api";
import { Section, SecretSetting, TextSetting } from "../components/blocks";
import { CheckIcon, AlertIcon, MonitorIcon, MoonIcon, PowerIcon, SparkleIcon, SunIcon, UsersIcon, LeafIcon } from "../components/icons";
import { ControlRow, PageHeader, Segmented, Select, Spinner } from "../components/ui";
import { useLive } from "../live";
import { modulesFor } from "../registry";
import { useSettings, useShell } from "../shell";
import type { ThemePref } from "../theme";

function ModelPicker({ provider, value, onSave }: { provider: ProviderId; value: string; onSave: (v: string) => void }) {
  const [models, setModels] = useState<string[] | null>(null);
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    setModels(null);
    api.providerModels(provider).then((r) => setModels(r.models), () => setModels([]));
  }, [provider]);
  if (models === null) return <Spinner className="text-ink-faint" />;
  if (typing || models.length === 0) {
    return <TextSetting label="Model" value={value} onSave={onSave} mono placeholder={provider === "ollama" ? "automatic" : "model id"} />;
  }
  const options = [
    ...(provider === "ollama" ? [{ value: "", label: "Automatic", hint: "The best installed model" }] : []),
    ...models.map((m) => ({ value: m, label: m })),
    ...(value && !models.includes(value) ? [{ value, label: value, hint: "Not found" }] : []),
    { value: "\u0000other", label: "Other…", hint: "Type a model id" },
  ];
  return <Select label="Model" size="sm" className="w-full sm:w-64" value={value} options={options} onChange={(v) => (v === "\u0000other" ? setTyping(true) : onSave(v))} />;
}

function ProviderFields({ id, values, hints, save }: { id: ProviderId; values: Record<string, unknown>; hints: Record<string, string | null>; save: (c: Record<string, string>) => void }) {
  const { toast } = useShell();
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const v = (k: string) => String(values[`ai.${k}`] ?? "");
  const test = async () => {
    setTesting(true);
    setResult(null);
    try {
      setResult({ ok: true, text: (await api.providerTest(id)).message });
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };
  return (
    <>
      {id === "ollama" && (
        <ControlRow label="Ollama address" hint="Another machine works too, e.g. your Mac over Tailscale.">
          <TextSetting label="Ollama address" value={v("ollama_url")} onSave={(x) => save({ "ai.ollama_url": x })} mono />
        </ControlRow>
      )}
      {id === "custom" && (
        <>
          <ControlRow label="Name" hint="How it's shown in the app.">
            <TextSetting label="Name" value={v("custom_name")} onSave={(x) => save({ "ai.custom_name": x })} />
          </ControlRow>
          <ControlRow label="Base URL" hint="Up to and including /v1, e.g. https://openrouter.ai/api/v1">
            <TextSetting label="Base URL" value={v("custom_base_url")} onSave={(x) => save({ "ai.custom_base_url": x })} mono />
          </ControlRow>
        </>
      )}
      {id !== "ollama" && (
        <ControlRow label="API key" hint="Saved on this machine and never shown again.">
          <SecretSetting label="API key" hint={hints[`ai.${id}_api_key`]} onSave={(x) => save({ [`ai.${id}_api_key`]: x })} />
        </ControlRow>
      )}
      <ControlRow label="Model">
        <ModelPicker provider={id} value={v(`${id}_model`)} onSave={(x) => save({ [`ai.${id}_model`]: x })} />
      </ControlRow>
      <div className="py-3.5">
        <button className="btn btn-sm btn-soft" disabled={testing} onClick={() => void test().catch((e) => toast(e.message, "error"))}>
          {testing ? <Spinner /> : <SparkleIcon size={16} />}
          Test the connection
        </button>
        {result && (
          <p className={`mt-2.5 flex animate-fade-in items-start gap-1.5 text-hint leading-snug ${result.ok ? "text-forest-deep" : "text-trail-deep"}`}>
            {result.ok ? <CheckIcon size={16} className="shrink-0" /> : <AlertIcon size={16} className="shrink-0" />}
            <span className="break-words">{result.text}</span>
          </p>
        )}
      </div>
    </>
  );
}

export default function Settings() {
  const { app, theme } = useShell();
  const { values, hints, save } = useSettings();
  const { data: providers } = useLive<ProviderInfo[]>(api.providers);
  const modules = modulesFor(app.modules.map((m) => m.id)).filter((m) => m.settings);
  if (!values) return null;
  const options = (providers ?? []).map((p) => ({ value: p.id, label: p.label, hint: p.kind === "local" ? "Runs on this Mac" : "Cloud" }));
  const primary = values["ai.provider"] as ProviderId;

  return (
    <>
      <PageHeader title="Settings" subtitle={`Everything ${app.name} keeps is on this machine.`} />

      <Section icon={<SunIcon size={16} />} title="Appearance" blurb="Dusk is the same trail after sunset.">
        <ControlRow label="Theme">
          <Segmented<ThemePref>
            label="Theme"
            size="sm"
            value={theme.pref}
            onChange={theme.setPref}
            options={[
              { id: "light", label: "Day", icon: <SunIcon size={16} /> },
              { id: "dusk", label: "Dusk", icon: <MoonIcon size={16} /> },
              { id: "system", label: "System", icon: <MonitorIcon size={16} /> },
            ]}
          />
        </ControlRow>
        <ControlRow icon={<UsersIcon size={16} />} label="Your name" hint="Used instead of “You” wherever people are named.">
          <TextSetting label="Your name" value={String(values["core.your_name"] ?? "")} onSave={(x) => save({ "core.your_name": x })} placeholder="e.g. Sam" />
        </ControlRow>
      </Section>

      <Section icon={<SparkleIcon size={16} />} title="AI" blurb="One choice for every part of the app. Local models never leave this Mac." delay={60}>
        <ControlRow label="Provider" hint={providers?.find((p) => p.id === primary)?.reason || "Used first."}>
          <Select label="Provider" size="sm" className="w-full sm:w-64" value={primary} options={options} onChange={(x) => save({ "ai.provider": x })} />
        </ControlRow>
        <ControlRow label="Fallback" hint="Tried if the first fails (offline, out of credit, and so on).">
          <Select
            label="Fallback"
            size="sm"
            className="w-full sm:w-64"
            value={String(values["ai.fallback"])}
            options={[{ value: "none", label: "None" }, ...options.filter((o) => o.value !== primary)]}
            onChange={(x) => save({ "ai.fallback": x })}
          />
        </ControlRow>
        <ProviderFields key={primary} id={primary} values={values} hints={hints} save={save} />
      </Section>

      {modules.map((m) => {
        const ModuleSettings = m.settings!;
        return <ModuleSettings key={m.id} />;
      })}

      <Section icon={<LeafIcon size={16} />} title={app.name} blurb={`Version ${app.version}`}>
        <ControlRow label={`Quit ${app.name}`} hint={inApp ? "Closes the window and the menu bar app." : "Stops the server; open the app again to come back."}>
          <button className="btn btn-sm btn-danger-ghost" onClick={() => (inApp ? quitApp() : void api.shutdown())}>
            <PowerIcon size={16} />
            Quit
          </button>
        </ControlRow>
      </Section>
    </>
  );
}
