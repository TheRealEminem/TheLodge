// Settings for the automatic ways in: Trailmix and Granola meetings, and calendar events.
import { useEffect, useState } from "react";
import { words } from "@core/api";
import { Section, SecretSetting } from "@core/components/blocks";
import { AlertIcon, CalendarIcon, CheckIcon, MicIcon, NoteIcon, RefreshIcon, TrashIcon } from "@core/components/icons";
import { ControlRow, Select, Spinner, SwitchRow, useConfirm } from "@core/components/ui";
import { useLive } from "@core/live";
import { useSettings, useShell } from "@core/shell";
import { crmApi } from "./api";
import type { CaptureSource, CaptureStatus, TrailmixFound } from "./api";
import { LockedNote } from "./bits";
import { relativeTime } from "./format";

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function StatusLine({ status, what }: { status: CaptureStatus | undefined; what: "meetings" | "events" }) {
  if (!status?.configured) return null;
  if (status.error) {
    return (
      <p className="flex items-start gap-1.5 py-3.5 text-hint leading-snug text-trail-deep">
        <AlertIcon size={16} className="mt-px shrink-0" />
        <span className="break-words">{status.error}</span>
      </p>
    );
  }
  const counts = status.last_counts;
  const detail = counts
    ? what === "meetings"
      ? `${plural(counts.imported ?? 0, "new meeting")} found${counts.later ? `, ${counts.later} more over the next checks` : ""}${counts.total ? ` · ${counts.total} brought in so far` : ""}`
      : `${plural(counts.meetings ?? 0, "meeting")} from ${plural(counts.events ?? 0, "event")}`
    : "";
  return (
    <p className="flex items-start gap-1.5 py-3.5 text-hint leading-snug text-ink-soft">
      <CheckIcon size={16} className="mt-px shrink-0 text-forest-deep" />
      <span>
        {status.last_ok_at ? `Last checked ${relativeTime(status.last_ok_at)}${detail ? ` · ${detail}` : ""}.` : "Waiting for the first check."}
        {status.calendars?.length ? ` Reading ${status.calendars.join(", ")}.` : ""}
      </span>
    </p>
  );
}

function RemoveRow({ source, confirm, onDone }: { source: CaptureSource | undefined; confirm: ReturnType<typeof useConfirm>[0]; onDone: () => void }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  if (!source || (source.meetings === 0 && source.people === 0 && source.lines === 0)) return null;
  const parts = [plural(source.meetings, "meeting"), source.people ? plural(source.people, "person", "people") : "", source.lines ? plural(source.lines, "other line") : ""].filter(Boolean);
  const run = async () => {
    const ok = await confirm({
      title: `Remove everything that came from ${source.label}?`,
      body: `${parts.join(", ")} will be deleted, with their notes. People and organizations that were already in your book, or that you've added to since, stay.${
        source.kept ? ` ${plural(source.kept, "calendar meeting")} that now hold notes from a recording stay too.` : ""
      } This can't be undone.`,
      confirmLabel: "Remove",
      tone: "danger",
    });
    if (!ok) return;
    setBusy(true);
    try {
      const r = await crmApi.captureRemove(source.origin);
      toast(`Removed ${plural(r.meetings, "meeting")} from ${source.label}.`);
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <ControlRow label={`Remove what came from ${source.label}`} hint={`${parts.join(", ")}. Everything it adds is marked with where it came from, so this takes back just that.`} wrap>
      <button className="btn btn-sm btn-danger-ghost" disabled={busy} onClick={() => void run()}>
        {busy ? <Spinner /> : <TrashIcon size={16} />} Remove
      </button>
    </ControlRow>
  );
}

function Actions({ which, ready }: { which: "trailmix" | "granola" | "calendar"; ready: boolean }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState<"test" | "sync" | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (kind: "test" | "sync") => {
    setBusy(kind);
    setResult(null);
    try {
      if (kind === "sync") {
        await crmApi.captureSync();
        toast("Checking now. New meetings appear in the Inbox or your people.");
      } else {
        const r = await crmApi.captureTest(which);
        if (which === "trailmix") {
          setResult({ ok: true, text: `Trailmix is answering, with ${plural(r.done as number, "finished meeting")}.` });
        } else if (which === "granola") {
          setResult({
            ok: true,
            text: `Granola accepted the key${r.has_notes ? "" : " (no notes yet)"}.${r.needs_my_email ? " Add your email to your own profile so The Lodge can tell which attendee is you." : ""}`,
          });
        } else {
          const found = (r.calendars as { name: string; events: number }[]).map((c) => `${c.name} (${plural(c.events, "event")} in the next two weeks and last week)`);
          setResult({ ok: true, text: `Read ${found.join(", ")}.` });
        }
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
          {busy === "sync" ? <Spinner /> : <RefreshIcon size={16} />} Check now
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

const BACK = [{ value: "30", label: "30 days" }, { value: "90", label: "90 days" }, { value: "365", label: "A year" }, { value: "0", label: "Everything" }];

/** Trailmix on this Mac: whether it's there, how many meetings it has, and which of its workspaces come in. */
function TrailmixChoices() {
  const { get, save } = useSettings();
  const [found, setFound] = useState<TrailmixFound | null>(null);
  const [missing, setMissing] = useState<string | null>(null);
  useEffect(() => {
    crmApi.trailmixFind().then(setFound, (e: Error) => setMissing(e.message));
  }, []);
  const skip = get<string[]>("crm.trailmix_skip_workspaces") ?? [];
  if (missing) return <p className="flex items-start gap-1.5 py-3.5 text-hint leading-snug text-ink-soft"><AlertIcon size={16} className="mt-px shrink-0" />{missing}</p>;
  if (!found) return null;
  return (
    <>
      <p className="py-3.5 text-hint text-ink-soft">Trailmix is on {words.here}, with {plural(found.done, "finished meeting")}.</p>
      {found.workspaces.length > 0 && (
        <ControlRow label="Workspaces to bring in" hint="Leave out any that aren't about people you want in your book, such as personal ones. Meetings in no workspace always come in." wrap>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {found.workspaces.map((w) => (
              <label key={w.id} className="flex items-center gap-2 text-ui">
                <input type="checkbox" className="accent-forest" checked={!skip.includes(String(w.id))}
                  onChange={(e) => void save({ "crm.trailmix_skip_workspaces": e.target.checked ? skip.filter((x) => x !== String(w.id)) : [...skip, String(w.id)] })} />
                {w.name} <span className="text-ink-soft tabular-nums">{w.meetings}</span>
              </label>
            ))}
          </div>
        </ControlRow>
      )}
    </>
  );
}

export default function CaptureSettings() {
  const { get, save, hints } = useSettings();
  const [confirm, confirmDialog] = useConfirm();   // outside the sections: their entrance animation would trap a fixed dialog
  const { data, reload } = useLive(crmApi.capture);
  const source = (o: CaptureSource["origin"]) => data?.sources.find((s) => s.origin === o);
  const refresh = () => void reload();
  return (
    <>
      <Section
        icon={<MicIcon size={16} />}
        title="People: Trailmix"
        blurb={`Meetings you record with Trailmix on ${words.here} are read and added on their own: who was there, what was said, and what was agreed. Nothing leaves ${words.here} to fetch them.`}
      >
        <SwitchRow
          label="Bring in Trailmix meetings"
          hint="Checks every 15 minutes. Each meeting is read by the AI that reads your notes, so it counts toward that AI's usage."
          checked={!!get<boolean>("crm.trailmix_sync")}
          onChange={(v) => void save({ "crm.trailmix_sync": v })}
        />
        <TrailmixChoices />
        <ControlRow label="How far back" hint="Meetings older than this aren't brought in. A big backlog comes in 40 at a time, a few minutes apart.">
          <Select label="How far back" size="sm" className="w-full sm:w-40" value={String(get<number>("crm.trailmix_days") ?? 90)}
            options={BACK} onChange={(v) => void save({ "crm.trailmix_days": Number(v) })} />
        </ControlRow>
        <SwitchRow
          label="Add meetings to your people automatically"
          hint="Off: each one waits in the Inbox for you to look over. On: it's added unless a name is unclear."
          checked={get<boolean>("crm.trailmix_auto_apply") !== false}
          onChange={(v) => void save({ "crm.trailmix_auto_apply": v })}
        />
        <StatusLine status={data?.trailmix} what="meetings" />
        <Actions which="trailmix" ready={!!data?.trailmix.configured} />
        <RemoveRow source={source("trailmix")} confirm={confirm} onDone={refresh} />
      </Section>
      <Section
        icon={<NoteIcon size={16} />}
        title="People: Granola"
        blurb="New Granola meetings are read and added on their own, with who was there and what was said. Needs a Granola Business or Enterprise plan."
      >
        <ControlRow label="Granola API key" hint="In the Granola app: Settings, Connectors, API keys. Saved on this machine and never shown again." wrap>
          <SecretSetting label="Granola API key" hint={hints["crm.granola_api_key"]} onSave={(x) => void save({ "crm.granola_api_key": x })} />
        </ControlRow>
        <SwitchRow
          label="Add meetings to your people automatically"
          hint="Off: each one waits in the Inbox for you to look over. On: it's added unless a name is unclear."
          checked={get<boolean>("crm.granola_auto_apply") !== false}
          onChange={(v) => void save({ "crm.granola_auto_apply": v })}
        />
        <LockedNote why={data?.granola.locked} />
        <StatusLine status={data?.granola} what="meetings" />
        <Actions which="granola" ready={!!data?.granola.configured && !data.granola.locked} />
        <RemoveRow source={source("granola")} confirm={confirm} onDone={refresh} />
      </Section>
      <Section
        icon={<CalendarIcon size={16} />}
        title="People: calendar"
        blurb="Meetings with people you know are on your book before they happen, so notes taken later join the same meeting. Strangers on an invite aren't added as people."
      >
        <ControlRow label="Calendar address" hint="Google Calendar: Settings for the calendar, Integrate calendar, Secret address in iCal format. Anyone with it can read that calendar, so it's kept like a key. Separate several with spaces." wrap>
          <SecretSetting label="Calendar address" hint={hints["crm.calendar_secret"]} onSave={(x) => void save({ "crm.calendar_secret": x })} />
        </ControlRow>
        <LockedNote why={data?.calendar.locked} />
        <StatusLine status={data?.calendar} what="events" />
        <Actions which="calendar" ready={!!data?.calendar.configured && !data.calendar.locked} />
        <RemoveRow source={source("calendar")} confirm={confirm} onDone={refresh} />
      </Section>
      {confirmDialog}
    </>
  );
}
