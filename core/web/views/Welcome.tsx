// The first run: one question per screen, every one skippable, and all of it in Settings later.
//   Hello → where AI runs → privacy → one step from each module that wants one → done.
import { useState } from "react";
import type { ComponentType } from "react";
import { api } from "../api";
import { TextSetting } from "../components/blocks";
import { ChooseAi } from "../components/ChooseAi";
import { CheckIcon, LockIcon } from "../components/icons";
import { Ambient, Scene } from "../components/illustrations";
import { SwitchRow } from "../components/ui";
import { modulesFor } from "../registry";
import { useSettings, useShell } from "../shell";
import { welcomeLead, welcomeTitle } from "@identity/copy";

type Step = { id: string; title: string; view: ComponentType<{ next: () => void }> };

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
      <p className="mt-2 text-body leading-relaxed text-ink-soft">Everything is kept on this Mac. Lockdown makes sure nothing is sent out either.</p>
      <div className="mt-4">
        <SwitchRow
          icon={<LockIcon size={16} />}
          label="Lockdown"
          hint="On: only AI that runs on this Mac is used, the app doesn't check for updates by itself, and anything that talks to another service is switched off. Off: you pick the services you want, one at a time."
          checked={on}
          onChange={(v) => void save({ "core.lockdown": v })}
        />
      </div>
      <button className="btn btn-md btn-primary mt-6" onClick={next}>Continue</button>
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
  const modules = modulesFor(app.modules.map((m) => m.id));
  const steps: Step[] = [
    { id: "hello", title: welcomeTitle, view: Hello },
    { id: "ai", title: "Where should AI run?", view: Where },
    { id: "privacy", title: "Keep it private?", view: Privacy },
    ...modules.flatMap((m) => (m.setupStep ? [{ id: m.id, title: m.setupStep.title, view: m.setupStep.view }] : [])),
    { id: "done", title: "You're all set", view: Done },
  ];
  const [at, setAt] = useState(0);
  const [busy, setBusy] = useState(false);
  const step = steps[at];
  const View = step.view;
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
        <View next={() => void next()} />
        {at > 0 && at < steps.length - 1 && (
          <button className="btn btn-sm btn-ghost mt-4 -ml-2" onClick={() => setAt(at - 1)}>Back</button>
        )}
      </div>
    </div>
  );
}
