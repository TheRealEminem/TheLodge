// Settings for the shared Google Sheet: setting it up, how the last sync went, and the choice when a tab was held back.
import { useState } from "react";
import { Section, SecretSetting } from "@core/components/blocks";
import { AlertIcon, CheckIcon, ChevronDownIcon, ColumnsIcon, CopyIcon, ExternalIcon, RefreshIcon } from "@core/components/icons";
import { ControlRow, Spinner } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import type { SheetStatus } from "./api";
import { relativeTime } from "./format";

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

/** Closer than relativeTime's days, since this runs every couple of minutes. */
function syncedAt(iso: string) {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${plural(minutes, "minute")} ago`;
  const d = new Date(iso);
  if (d.toDateString() === new Date().toDateString()) return `at ${d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
  return relativeTime(iso);
}

/** Puts text on the clipboard, falling back to a hidden text box where the clipboard API isn't allowed. */
async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    return;
  } catch {
    const box = document.createElement("textarea");
    box.value = text;
    box.setAttribute("readonly", "");
    box.style.position = "fixed";
    box.style.opacity = "0";
    document.body.appendChild(box);
    box.select();
    const ok = document.execCommand("copy");
    box.remove();
    if (!ok) throw new Error("Couldn't copy. Show the script and copy it from there.");
  }
}

function Steps({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const { toast } = useShell();
  const [script, setScript] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const load = async () => script ?? (await crmApi.sheetScript()).text;
  const copy = async () => {
    try {
      const text = await load();
      setScript(text);
      await copyText(text);
      toast("Script copied. Paste it into Apps Script.");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const show = async () => {
    if (!shown) setScript(await load());
    setShown(!shown);
  };
  return (
    <div className="py-3.5">
      <button className="flex w-full items-center justify-between gap-2 text-left text-ui font-medium" aria-expanded={open} onClick={onToggle}>
        How to set it up
        <ChevronDownIcon size={16} className={`shrink-0 text-ink-soft transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <div className="mt-3 animate-fade-in">
          <ol className="list-decimal space-y-2 pl-5 text-hint leading-snug text-ink-soft">
            <li>Make a Google Sheet, or open the one you want to share. The Lodge adds a People tab and an Organizations tab and leaves any others alone.</li>
            <li>Choose Extensions, then Apps Script. Replace everything there with the script below, and save.</li>
            <li>
              Choose Deploy, New deployment, and pick Web app. Set Execute as to “Me” and Who has access to “Anyone”, then Deploy. If Google says the app
              isn’t verified, that’s because it’s your own script: choose Advanced, then Go to it.
            </li>
            <li>Copy the Web app URL (it ends in /exec) and paste it below. Then share the spreadsheet with whoever you like, as you would any other.</li>
          </ol>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-sm btn-soft" onClick={() => void copy()}>
              <CopyIcon size={16} /> Copy the script
            </button>
            <button className="btn btn-sm btn-ghost" onClick={() => void show()}>
              {shown ? "Hide the script" : "Show the script"}
            </button>
          </div>
          {shown && script && (
            <textarea
              readOnly
              aria-label="The sheet’s script"
              wrap="off"
              className="field mt-3 h-48 w-full font-mono text-hint"
              value={script}
              onFocus={(e) => e.currentTarget.select()}
            />
          )}
        </div>
      )}
    </div>
  );
}

function StatusLine({ status }: { status: SheetStatus }) {
  if (!status.configured) return null;
  if (status.error) {
    return (
      <p className="flex items-start gap-1.5 py-3.5 text-hint leading-snug text-trail-deep">
        <AlertIcon size={16} className="mt-px shrink-0" />
        <span className="break-words">{status.error}</span>
      </p>
    );
  }
  const c = status.last_counts ?? {};
  const parts = [
    c.changes_in ? `${plural(c.changes_in, "change")} came in` : "",
    c.new ? `${c.new} new from the sheet` : "",
    c.notes ? plural(c.notes, "note") : "",
    c.conflicts ? `${plural(c.conflicts, "clash", "clashes")} noted` : "",
  ].filter(Boolean);
  return (
    <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 py-3.5">
      <p className="flex items-start gap-1.5 text-hint leading-snug text-ink-soft">
        <CheckIcon size={16} className="mt-px shrink-0 text-forest-deep" />
        <span>
          {status.last_ok_at
            ? `Synced${status.spreadsheet ? ` with “${status.spreadsheet.name}”` : ""} ${syncedAt(status.last_ok_at)}${parts.length ? ` · ${parts.join(" · ")}` : ""}.`
            : "Waiting for the first sync."}
        </span>
      </p>
      {status.spreadsheet && (
        <a className="btn btn-sm btn-ghost" href={status.spreadsheet.url} target="_blank" rel="noreferrer">
          <ExternalIcon size={16} /> Open the sheet
        </a>
      )}
    </div>
  );
}

function Held({ held, onDone }: { held: NonNullable<SheetStatus["held"]>; onDone: () => void }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState<"apply" | "restore" | null>(null);
  const decide = async (choice: "apply" | "restore") => {
    setBusy(choice);
    try {
      await crmApi.sheetDecide(choice);
      toast(choice === "restore" ? "Putting The Lodge’s values back on the sheet." : "Copying the sheet’s values in.");
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  return (
    <>
      {Object.entries(held).map(([tab, h]) => (
        <div key={tab} className="py-3.5">
          <p className="flex items-start gap-1.5 text-hint leading-snug text-trail-deep">
            <AlertIcon size={16} className="mt-px shrink-0" />
            <span>
              On the {tab} tab, {plural(h.cells, "value")} {h.columns.length ? `(mostly ${h.columns.join(", ")}) ` : ""}were emptied or replaced at once.
              That can be a sort or a paste gone wrong, so The Lodge hasn’t copied them in, and that tab waits until you choose. Undoing it on the
              sheet (File, Version history) clears this on its own.
            </span>
          </p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void decide("restore")}>
              {busy === "restore" ? <Spinner /> : <RefreshIcon size={16} />} Put The Lodge’s back
            </button>
            <button className="btn btn-sm btn-ghost" disabled={busy !== null} onClick={() => void decide("apply")}>
              {busy === "apply" ? <Spinner /> : <CheckIcon size={16} />} Copy them in
            </button>
          </div>
        </div>
      ))}
    </>
  );
}

function Actions({ ready }: { ready: boolean }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState<"test" | "sync" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (kind: "test" | "sync") => {
    setBusy(kind);
    setResult(null);
    try {
      if (kind === "sync") {
        await crmApi.sheetSync();
        toast("Syncing now.");
      } else {
        const r = await crmApi.sheetTest();
        setResult({ ok: true, text: `The script answered from “${r.spreadsheet?.name ?? "your spreadsheet"}”.` });
      }
    } catch (e) {
      setResult({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="py-3.5">
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-sm btn-soft" disabled={!ready || busy !== null} onClick={() => void run("test")}>
          {busy === "test" ? <Spinner /> : <CheckIcon size={16} />} Test it
        </button>
        <button className="btn btn-sm btn-soft" disabled={!ready || busy !== null} onClick={() => void run("sync")}>
          {busy === "sync" ? <Spinner /> : <RefreshIcon size={16} />} Sync now
        </button>
      </div>
      {result && (
        <p className={`mt-2.5 flex animate-fade-in items-start gap-1.5 text-hint leading-snug ${result.ok ? "text-forest-deep" : "text-trail-deep"}`}>
          {result.ok ? <CheckIcon size={16} className="shrink-0" /> : <AlertIcon size={16} className="shrink-0" />}
          <span className="break-words">{result.text}</span>
        </p>
      )}
    </div>
  );
}

export default function SheetSettings() {
  const { save, hints } = useSettings();
  const { data, reload } = useLive(crmApi.sheet);
  const [stepsOpen, setStepsOpen] = useState<boolean | null>(null);
  const configured = !!data?.configured;
  return (
    <Section
      icon={<ColumnsIcon size={16} />}
      title="People: shared sheet"
      blurb="Your people and organizations in a Google Sheet that anyone you share it with can read, correct and add to. The Lodge checks it every couple of minutes and sends its own changes within about half a minute."
    >
      <p className="py-3.5 text-hint leading-snug text-ink-soft">
        On the sheet: names, organizations, titles, contact details, tags and summaries. Staying here: how well you know people, notes, meetings,
        documents and overviews. Tag anyone “private” to keep them off it. New rows become people (or join someone already here), anything typed under
        “Add a note” is filed as a note, and a deleted row comes back.
      </p>
      <Steps open={stepsOpen ?? !configured} onToggle={() => setStepsOpen(!(stepsOpen ?? !configured))} />
      <ControlRow label="Sheet script link" hint="The Web app URL from Apps Script. Anyone with it can read and change the sheet, so it’s kept like a key." wrap>
        <SecretSetting label="Sheet script link" hint={hints["crm.sheet_secret"]} onSave={(x) => void save({ "crm.sheet_secret": x })} />
      </ControlRow>
      {data && <StatusLine status={data} />}
      {data?.held && <Held held={data.held} onDone={() => void reload()} />}
      <Actions ready={configured} />
    </Section>
  );
}
