// The first run: one question per screen, every one skippable, and all of it in Settings later.
//   Hello → where AI runs → privacy → how to keep your work (when the app has a connection to offer) → connecting the
//   tool picked there → one step from each other module that wants one → done.
import { useState } from "react";
import type { ReactNode } from "react";
import { api, words } from "../api";
import { TextSetting } from "../components/blocks";
import { ChooseAi } from "../components/ChooseAi";
import { CheckIcon, LaptopIcon, LockIcon, NetworkIcon } from "../components/icons";
import { Ambient, Scene } from "../components/illustrations";
import { SwitchRow } from "../components/ui";
import { modulesFor } from "../registry";
import type { ModuleWeb } from "../registry";
import { useSettings, useShell } from "../shell";
import { welcomeLead, welcomeTitle } from "@identity/copy";

type Step = { id: string; title: string; show: (next: () => void) => ReactNode };

function Hello({ next }: { next: () => void }) {
  const { values, save } = useSettings();
  const { app } = useShell();
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">{welcomeLead}</p>
      <div className="mt-6">
        <label className="text-label font-medium" htmlFor="your-name">What should {app.name} call you?</label>
        <div className="mt-2">
          <TextSetting label="Your name" className="w-full" placeholder="e.g. Sam" value={String(values?.["core.your_name"] ?? "")} onSave={(x) => void save({ "core.your_name": x })} />
        </div>
        <p className="mt-1.5 text-hint text-ink-faint">Used instead of “You” wherever people are named. You can leave it blank.</p>
      </div>
      <button className="btn btn-md btn-primary mt-6" onClick={next}>Let's go</button>
    </>
  );
}

function Where({ next }: { next: () => void }) {
  return <ChooseAi onChosen={next} skippable={next} />;
}

function Privacy({ next }: { next: () => void }) {
  const { values, save } = useSettings();
  const on = !!values?.["core.lockdown"];
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">Everything is kept on {words.here}. Lockdown makes sure nothing is sent out either.</p>
      <div className="mt-4">
        <SwitchRow
          icon={<LockIcon size={16} />}
          label="Lockdown"
          hint={`On: only AI that runs on ${words.here} is used, the app doesn't check for updates by itself, and anything that talks to another service is switched off. Off: you pick the services you want, one at a time.`}
          checked={on}
          onChange={(v) => void save({ "core.lockdown": v })}
        />
      </div>
      <button className="btn btn-md btn-primary mt-6" onClick={next}>Continue</button>
    </>
  );
}

function Choice({ icon, title, body, current, onPick }: { icon: ReactNode; title: string; body: string; current?: boolean; onPick: () => void }) {
  return (
    <button
      className={`panel flex w-full items-start gap-3.5 px-5 py-4 text-left transition-[transform,box-shadow] duration-150 hover:-translate-y-px hover:shadow-md ${current ? "ring-2 ring-forest/40" : ""}`}
      onClick={onPick}
    >
      <span className="well well-forest shrink-0">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-heading font-semibold tracking-[-0.01em]">{title}</span>
        <span className="mt-0.5 block text-ui leading-snug text-ink-soft">{body}</span>
      </span>
    </button>
  );
}

/** Local only, or one of the project tools this app can connect to (modules with `active`, D11). */
function Keep({ pick }: { pick: (tool: string | null) => void }) {
  const { app } = useShell();
  const { values } = useSettings();
  const locked = !!values?.["core.lockdown"];
  const tools = app.modules.filter((m) => m.optional);
  const connected = tools.filter((m) => m.active).map((m) => m.name);
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">{app.name} works on its own, or on top of the tool your team already uses. You can change this later in Settings.</p>
      <div className="mt-6 space-y-3">
        <Choice
          current={!connected.length}
          icon={<LaptopIcon size={16} />}
          title={`Just on ${words.here}`}
          body={`Your projects and tasks stay here, and nothing is sent to a project tool.${connected.length ? ` ${connected.join(" and ")} stays connected until you change it in Settings.` : ""}`}
          onPick={() => pick(null)}
        />
        {tools.map((m) => (
          <Choice
            key={m.id}
            current={m.active}
            icon={<NetworkIcon size={16} />}
            title={m.active ? `${m.name}, connected` : `Connect ${m.name}`}
            body={`Keep your team's ${m.name} as the shared place, with ${app.name} on top of it. It reads ${m.name}, and sends changes only when you approve them.${locked ? ` While Lockdown is on, it won't reach ${m.name}.` : ""}`}
            onPick={() => pick(m.id)}
          />
        ))}
      </div>
    </>
  );
}

/** The tool picked in Keep: its own first-run step if it has one, otherwise its Settings section. */
function Connect({ tool, next }: { tool: ModuleWeb; next: () => void }) {
  const { app } = useShell();
  const on = !!app.modules.find((m) => m.id === tool.id)?.active;
  const Own = tool.setupStep?.view;
  if (Own) return <Own next={next} />;
  const Fields = tool.settings!;
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">Set it up here, or skip it and come back to Settings → Connect a tool.</p>
      <div className="mt-6 text-left">
        <Fields />
      </div>
      <button className="btn btn-md btn-primary mt-2" onClick={next}>{on ? "Continue" : "Skip for now"}</button>
    </>
  );
}

function Done({ next }: { next: () => void }) {
  const { app } = useShell();
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">That's it. Everything you chose is in Settings if you change your mind, and {app.name} is ready.</p>
      <button className="btn btn-md btn-primary mt-6" onClick={next}><CheckIcon size={16} /> Open {app.name}</button>
    </>
  );
}

export default function Welcome({ dusk, onDone }: { dusk: boolean; onDone: () => void }) {
  const { app } = useShell();
  const modules = modulesFor(app.modules.filter((m) => !m.optional).map((m) => m.id));
  const tools = modulesFor(app.modules.filter((m) => m.optional).map((m) => m.id));
  const [tool, setTool] = useState<string | null>(null);
  const picked = tools.find((m) => m.id === tool && (m.setupStep || m.settings));
  const steps: Step[] = [
    { id: "hello", title: welcomeTitle, show: (next) => <Hello next={next} /> },
    { id: "ai", title: "Where should AI run?", show: (next) => <Where next={next} /> },
    { id: "privacy", title: "Keep it private?", show: (next) => <Privacy next={next} /> },
    ...(tools.length
      ? [{ id: "keep", title: "How do you want to keep your work?", show: (next: () => void) => <Keep pick={(id) => { setTool(id); next(); }} /> }]
      : []),
    ...(picked ? [{ id: `connect-${picked.id}`, title: picked.setupStep?.title ?? `Connect ${picked.name}`, show: (next: () => void) => <Connect tool={picked} next={next} /> }] : []),
    ...modules.flatMap(({ id, setupStep: own }) => (own ? [{ id, title: own.title, show: (next: () => void) => <own.view next={next} /> }] : [])),
    { id: "done", title: "You're all set", show: (next) => <Done next={next} /> },
  ];
  const [at, setAt] = useState(0);
  const [busy, setBusy] = useState(false);
  const step = steps[at];
  const next = async () => {
    if (at < steps.length - 1) return setAt(at + 1);
    setBusy(true);
    try {
      await api.setupDone();
    } finally {
      setBusy(false);
    }
    onDone();
  };
  return (
    <div className="relative flex h-full flex-col items-center overflow-y-auto p-5">
      <Ambient />
      <div className="relative my-auto w-full max-w-[560px] animate-enter py-8" key={step.id} aria-busy={busy}>
        {at === 0 && <div className="art-frame mb-6 h-44"><Scene dusk={dusk} className="h-full w-full" /></div>}
        <p className="text-hint text-ink-faint">Step {at + 1} of {steps.length}</p>
        <h1 className="page-title mt-1">{step.title}</h1>
        {step.show(() => void next())}
        {at > 0 && at < steps.length - 1 && (
          <button className="btn btn-sm btn-ghost mt-4 -ml-2" onClick={() => setAt(at - 1)}>Back</button>
        )}
      </div>
    </div>
  );
}
