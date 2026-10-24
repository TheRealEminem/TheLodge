// Settings: the host's own sections (appearance, you, AI, the app), then one section per module.
import { useEffect, useState } from "react";
import { api, inApp, quitApp, sendUpdates } from "../api";
import type { FamilyStatus, ProviderId, ProviderInfo, SystemInfo, UpdateReport } from "../api";
import { Section, SecretSetting, TextSetting } from "../components/blocks";
import { ChooseAi } from "../components/ChooseAi";
import { OllamaSetup } from "../components/OllamaSetup";
import { CheckIcon, AlertIcon, BackIcon, DownloadIcon, LaptopIcon, LockIcon, MonitorIcon, MoonIcon, NetworkIcon, PowerIcon, RefreshIcon, SparkleIcon, SunIcon, UsersIcon, LeafIcon } from "../components/icons";
import { ControlRow, PageHeader, Segmented, Select, Spinner, StatusChip, SwitchRow } from "../components/ui";
import { useLive } from "../live";
import { modulesFor } from "../registry";
import { useSettings, useShell } from "../shell";
import type { ThemePref } from "../theme";
import YourData from "./YourData";

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

/** "Apple M4 · 16 GB memory · 20 GB free", for setup and Settings. */
export function macLine(info: SystemInfo): string {
  const a = info.advice;
  return [a.chip, `${a.ram_gb} GB memory`, `${a.disk_free_gb} GB free`].filter(Boolean).join(" · ");
}

/** What this Mac can do, and getting a model onto it. */
function OnThisMac() {
  const { data: info } = useLive<SystemInfo>(api.system);
  return (
    <Section
      icon={<LaptopIcon size={16} />}
      title="On this Mac"
      blurb="A model that runs here is free and private: nothing you write is sent anywhere."
      delay={30}
    >
      {info && (
        <div className="py-3.5">
          <div className="text-label font-medium">{macLine(info)}</div>
          {info.advice.notes.map((n) => <p key={n} className="mt-1 text-hint text-ink-soft">{n}</p>)}
        </div>
      )}
      <OllamaSetup />
    </Section>
  );
}

/** For an install that was already in use before setup existed: the one question it was never asked. */
function ChooseWhereAiRuns() {
  const [open, setOpen] = useState(false);
  return (
    <Section icon={<LaptopIcon size={16} />} title="You can now run everything on this Mac" blurb="Choose where AI runs: on this Mac, in the cloud, or a mix. Nothing changes until you choose." delay={20}>
      {open ? <div className="py-3.5"><ChooseAi onChosen={() => setOpen(false)} skippable={() => setOpen(false)} /></div> : (
        <div className="py-3.5"><button className="btn btn-sm btn-soft" onClick={() => setOpen(true)}>Choose where AI runs</button></div>
      )}
    </Section>
  );
}

/** Lockdown: one switch, shared by the family apps on this Mac. */
function Privacy({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <Section icon={<LockIcon size={16} />} title="Privacy" blurb="Everything is kept on this Mac. Lockdown makes sure nothing is sent out either.">
      <SwitchRow
        label="Lockdown"
        hint={
          on
            ? "On: only AI that runs on this Mac is used. No update checks of its own, no downloads, and anything that talks to another service (a research service, a note app, a calendar, a shared Sheet, picture look-ups) is switched off."
            : "Off: you choose which services to use, and each is described where you turn it on. Turn this on to switch them all off at once."
        }
        checked={on}
        onChange={onChange}
      />
    </Section>
  );
}

/** The other family apps on this Mac: whether keys and preferences are shared with them, and who's installed. */
function FamilyApps({ data, onSharing }: { data: FamilyStatus | null; onSharing: (on: boolean) => void }) {
  const { app } = useShell();
  if (!data) return null;
  const sharing = data.sharing;
  if (!data.enabled) {
    return (
      <Section icon={<NetworkIcon size={16} />} title="Your family apps" blurb="Trailmix family apps on one Mac can share keys, preferences and what they know.">
        <p className="py-3.5 text-hint text-ink-soft">
          Off for this copy of {app.name}: it isn't running as the Mac app. Set TRAILMIX_FAMILY_DIR to a folder to join one.
        </p>
      </Section>
    );
  }
  const others = data.apps.filter((a) => !a.self);
  return (
    <Section icon={<NetworkIcon size={16} />} title="Your family apps" blurb="Trailmix family apps on this Mac share keys and preferences, and ask each other for what they know.">
      <SwitchRow
        label="Share keys and preferences"
        hint={
          sharing
            ? "On: your AI keys and choices, your name and the appearance are the same in every family app here."
            : `Off: ${app.name} keeps its own keys and preferences. What it saved before stays as it was.`
        }
        checked={sharing}
        onChange={onSharing}
      />
      {others.length ? (
        <ul className="divide-y divide-line">
          {others.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5 py-3">
              <div className="min-w-0">
                <div className="text-label font-medium">{a.name}</div>
                <div className="text-hint text-ink-soft">Version {a.version}</div>
              </div>
              <StatusChip tone={a.running ? "forest" : "neutral"} label={a.running ? "Open" : "Closed"} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="py-3.5 text-hint text-ink-soft">No other family apps have opened on this Mac yet. When one does, it shows here.</p>
      )}
    </Section>
  );
}

/** Where the Mac app's updates stand: its window sends a report now and on every change after. */
function useUpdates() {
  const [report, setReport] = useState<UpdateReport | null>(null);
  useEffect(() => {
    const listen = (e: Event) => setReport((e as CustomEvent<UpdateReport>).detail);
    window.addEventListener("app-updates", listen);
    sendUpdates("get");
    return () => window.removeEventListener("app-updates", listen);
  }, []);
  return report;
}

/** Settings → Updates: the version on offer, beta updates, a skipped version and going back. The Mac app's menu
 *  has the same; this is them in the window, for the Mac app only. */
function Updates() {
  const { app } = useShell();
  const { get } = useSettings();
  const u = useUpdates();
  const blurb = "New versions install from here or from the menu bar, in about a minute. Your data stays.";
  if (!inApp || !u || !u.enabled) {
    return (
      <Section icon={<DownloadIcon size={16} />} title="Updates" blurb={blurb}>
        <p className="py-3.5 text-hint text-ink-soft">
          {!inApp ? `Open ${app.name} from Applications to check for updates.` : `This copy of ${app.name} doesn't update itself (a development build).`}
        </p>
      </Section>
    );
  }
  const busy = u.working || u.state === "checking";
  let status: string;
  switch (u.state) {
    case "available": status = `${app.name} ${u.version}${u.prerelease ? " (beta)" : ""} is ready to install.`; break;
    case "downloading": status = `Downloading ${u.version}…${u.progress != null ? ` ${Math.round(u.progress * 100)}%` : ""}`; break;
    case "installing": status = `Installing ${u.version}… ${app.name} restarts when it's done.`; break;
    case "going-back": status = `Going back to ${u.version}…`; break;
    case "failed": status = u.error ?? "The update didn't work."; break;
    case "checking": status = "Checking for updates…"; break;
    case "offline": status = "Couldn't reach GitHub to check. It tries again in a few hours."; break;
    case "up-to-date": status = `You have the newest version${u.beta ? ", betas included" : ""}.`; break;
    default: status = get<boolean>("core.lockdown")
      ? "Lockdown is on, so it doesn't check by itself. Check for updates still works when you press it."
      : `${app.name} checks for updates a few times a day.`;
  }
  return (
    <Section icon={<DownloadIcon size={16} />} title="Updates" blurb={blurb}>
      <ControlRow label={`Version ${u.current}`} hint={status}>
        <div className="flex flex-wrap gap-2">
          {u.state === "available" && (
            <>
              <button className="btn btn-sm btn-ghost" onClick={() => sendUpdates("skip")}>Skip this version</button>
              <button className="btn btn-sm btn-primary" onClick={() => sendUpdates("install")}>
                <DownloadIcon size={16} />
                Update to {u.version}
              </button>
            </>
          )}
          {u.state === "failed" && (
            <button className="btn btn-sm btn-soft" onClick={() => sendUpdates("try-again")}>
              <RefreshIcon size={16} />
              Try again
            </button>
          )}
          {u.state !== "available" && u.state !== "failed" && (
            <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => sendUpdates("check")}>
              {busy ? <Spinner /> : <RefreshIcon size={16} />}
              Check for updates
            </button>
          )}
        </div>
      </ControlRow>
      <SwitchRow
        label="Beta updates"
        hint="Get new versions a few days early, to try them out; they may have rough edges. A beta reaches everyone after 3 days unless someone reports that it blocks them."
        checked={u.beta}
        disabled={u.working}
        onChange={(on) => sendUpdates(on ? "beta-on" : "beta-off")}
      />
      {u.skipped && (
        <ControlRow label={`Skipping ${u.skipped}`} hint="It isn't offered; the next version will be.">
          <button className="btn btn-sm btn-ghost" disabled={u.working} onClick={() => sendUpdates("unskip")}>Offer it again</button>
        </ControlRow>
      )}
      {u.previous && (
        <ControlRow
          label={`Go back to ${u.previous}`}
          hint={`If this version lets you down: puts back ${u.previous}, the version it updated from, and skips ${u.current} until a newer one comes out. Your data stays.`}
        >
          <button className="btn btn-sm btn-ghost" disabled={u.working} onClick={() => sendUpdates("go-back")}>
            <BackIcon size={16} />
            Go back
          </button>
        </ControlRow>
      )}
    </Section>
  );
}

export default function Settings() {
  const { app, theme, toast, reopenSetup } = useShell();
  const { values, hints, save } = useSettings();
  const { data: providers } = useLive<ProviderInfo[]>(api.providers);
  const { data: family } = useLive<FamilyStatus>(api.family);
  const [setup, setSetup] = useState<ProviderId | null>(null);
  const modules = modulesFor(app.modules.map((m) => m.id)).filter((m) => m.settings);
  if (!values) return null;
  const options = (providers ?? []).map((p) => ({ value: p.id, label: p.label, hint: p.kind === "local" ? "Runs on this Mac" : "Cloud" }));
  const primary = values["ai.provider"] as ProviderId;
  const setupId = setup ?? primary;
  const setupOptions = (providers ?? []).map((p) => ({ value: p.id, label: p.label, hint: p.ready ? "Ready" : p.kind === "local" ? "Not running" : "Needs setup" }));

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

      {!values["ai.path"] && <ChooseWhereAiRuns />}

      <OnThisMac />

      <Section
        icon={<SparkleIcon size={16} />}
        title="AI"
        blurb={`One choice for every part of the app. Local models never leave this Mac.${family?.sharing ? " Shared with your other family apps." : ""}`}
        delay={60}
      >
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
        <ControlRow label="Set up" hint="Each provider keeps its own key and model, so the jobs below can use different ones.">
          <Select label="Provider to set up" size="sm" className="w-full sm:w-64" value={setupId} options={setupOptions} onChange={(x) => setSetup(x as ProviderId)} />
        </ControlRow>
        <ProviderFields key={setupId} id={setupId} values={values} hints={hints} save={save} />
      </Section>

      <Privacy on={!!values["core.lockdown"]} onChange={(on) => void save({ "core.lockdown": on })} />

      <FamilyApps data={family ?? null} onSharing={(on) => void save({ "core.share_with_family": on })} />

      {modules.map((m) => {
        const ModuleSettings = m.settings!;
        return <ModuleSettings key={m.id} />;
      })}

      <YourData />

      <Updates />

      <Section icon={<LeafIcon size={16} />} title={app.name} blurb={`Version ${app.version}`}>
        <ControlRow label="Setup" hint="The first-run questions again, one at a time. Nothing you have is changed unless you change it.">
          <button className="btn btn-sm btn-soft" onClick={() => void reopenSetup().catch((e: Error) => toast(e.message, "error"))}>
            <RefreshIcon size={16} />
            Run setup again
          </button>
        </ControlRow>
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
