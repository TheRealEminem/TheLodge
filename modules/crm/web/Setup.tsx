// The People module's step in the first run: who you are (connections are measured from you), and ways to bring people in.
import { useState } from "react";
import { PlusIcon } from "@core/components/icons";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";

export default function SetupStep({ next }: { next: () => void }) {
  const { toast } = useShell();
  const { values } = useSettings();
  const [name, setName] = useState(String(values?.["core.your_name"] ?? ""));
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      next();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <>
      <p className="mt-2 text-body leading-relaxed text-ink-soft">
        Connections are measured from you, so tell The Lodge who you are. Then bring people in whenever you like: type a note, drop a document, a spreadsheet or a LinkedIn export on the Inbox, or add someone by hand.
      </p>
      <form className="mt-5 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) void run(() => crmApi.setMe(name.trim())); }}>
        <input className="field h-10 flex-1" placeholder="Your name" aria-label="Your name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <button className="btn btn-md btn-primary" disabled={!name.trim() || busy}><PlusIcon size={18} /> Continue</button>
      </form>
      <p className="mt-5 text-hint text-ink-soft">
        Just looking around?{" "}
        <button className="font-medium text-forest-deep hover:underline" disabled={busy} onClick={() => void run(async () => { await crmApi.setMe(name.trim() || "You"); await crmApi.loadDemo(); })}>
          Load a fictional network
        </button>
        . <button className="font-medium text-forest-deep hover:underline" disabled={busy} onClick={next}>Skip this</button>
      </p>
    </>
  );
}
