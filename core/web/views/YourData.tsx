// Settings: what the app keeps for you. Back up now and a few points to go back to; under Advanced, every copy on disk,
// the folder, and a plain JSON copy of everything (ARCHITECTURE.md §7, DESIGN.md §7).
import { useState } from "react";
import { api, inApp, revealInFinder } from "../api";
import type { BackupItem, BackupSlot } from "../api";
import { Section } from "../components/blocks";
import { AlertIcon, CheckIcon, ChevronDownIcon, DownloadIcon, FolderIcon, RefreshIcon, TrashIcon } from "../components/icons";
import { Collapse, ControlRow, Spinner, useConfirm } from "../components/ui";
import { useLive } from "../live";
import { useShell } from "../shell";
import { exportHint, restoreBody } from "@identity/copy";

const KIND: Record<BackupItem["kind"], string> = {
  auto: "Automatic",
  manual: "Made by you",
  "before-restore": "Kept before a restore",
  "before-update": "Kept before an update",
};

const DAY = 864e5;
const SLOTS: BackupSlot[] = ["latest", "hour", "day", "week"];

function size(bytes: number) {
  return bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function startOfDay(t: number) {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

/** "An hour ago", "Yesterday", "Last week": how long ago a copy was made, in calendar days once it's not today. */
function ago(iso: string, now: number) {
  const t = new Date(iso).getTime();
  const minutes = Math.round((now - t) / 6e4);
  const days = Math.round((startOfDay(now) - startOfDay(t)) / DAY);
  if (minutes < 1) return "Just now";
  if (minutes < 2) return "A minute ago";
  if (minutes < 50) return `${minutes} minutes ago`;
  if (minutes < 90) return "An hour ago";
  if (days < 1) return `${Math.round(minutes / 60)} hours ago`;
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 14) return "Last week";
  if (days < 60) return `${Math.floor(days / 7)} weeks ago`;
  return `${Math.floor(days / 30)} months ago`;
}

/** "129 people, 40 tasks". */
function holds(counts: Record<string, number>) {
  return Object.entries(counts).map(([what, n]) => `${n} ${what}`).join(", ");
}

/** The restore choices the server picked (the newest, and the newest at least an hour, a day and a week old), once
 *  each: one copy can fill several. */
function choices(items: BackupItem[], slots: Record<BackupSlot, string | null> | undefined) {
  const names = [...new Set(SLOTS.map((s) => slots?.[s]).filter((n): n is string => !!n))];
  return names.map((n) => items.find((b) => b.name === n)).filter((b): b is BackupItem => !!b);
}

export default function YourData() {
  const { toast } = useShell();
  const [confirm, dialog] = useConfirm();
  const { data, reload } = useLive(api.backups);
  const [busy, setBusy] = useState<string | null>(null);
  const [advanced, setAdvanced] = useState(false);
  const [exported, setExported] = useState<{ name: string; folder: string; text: string } | null>(null);

  const run = async (what: string, fn: () => Promise<void>) => {
    setBusy(what);
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  };
  const backUp = () => run("backup", async () => {
    await api.backUpNow();
    await reload();
    toast("Backed up.");
  });
  const restore = (b: BackupItem) => run(b.name, async () => {
    const ok = await confirm({
      title: `Go back to ${when(b.created_at)}?`,
      body: restoreBody,
      confirmLabel: "Restore",
      tone: "danger",
    });
    if (!ok) return;
    const r = await api.restoreBackup(b.name);
    await reload();
    const held = holds(r.counts ?? {});
    toast(`Restored${held ? `: ${held}` : ""}. The earlier state is kept as a backup.`);
  });
  const remove = (b: BackupItem) => run(b.name, async () => {
    await api.deleteBackup(b.name);
    await reload();
  });
  const exportAll = () => run("export", async () => {
    const r = await api.exportAll();
    const counts = Object.values(r.counts).flatMap((c) => Object.entries(c).map(([k, n]) => `${n} ${k}`));
    setExported({ name: r.name, folder: r.folder, text: `${counts.join(", ")} · ${size(r.bytes)}` });
  });

  const items = data?.items ?? [];
  const now = Date.now();
  const restoreButton = (b: BackupItem) => (
    <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void restore(b)}>
      {busy === b.name ? <Spinner /> : <RefreshIcon size={16} />} Restore
    </button>
  );

  return (
    <>
      <Section icon={<FolderIcon size={16} />} title="Your data" blurb="A copy is made each hour while something changes, and before an update or a restore. Only a few are kept: the newest, and one from about an hour, a day and a week ago. They stay in this Mac's data folder, private to you, and aren't sent anywhere.">
        <ControlRow label="Back up now" hint="Makes a copy of everything as it is right now, kept for at least a day." wrap>
          <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void backUp()}>
            {busy === "backup" ? <Spinner /> : <RefreshIcon size={16} />} Back up
          </button>
        </ControlRow>
        {items.length ? (
          <ul className="divide-y divide-line">
            {choices(items, data?.slots).map((b) => (
              <li key={b.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                <div className="min-w-0">
                  <div className="text-label font-medium">{ago(b.created_at, now)}</div>
                  <div className="text-hint text-ink-soft">{[when(b.created_at), holds(b.counts)].filter(Boolean).join(" · ")}</div>
                </div>
                {restoreButton(b)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-start gap-1.5 py-3.5 text-hint text-ink-soft"><AlertIcon size={16} className="mt-px shrink-0" /> No backups yet. The first is made shortly after the app starts.</p>
        )}
        <div>
          <button type="button" className="flex w-full items-center justify-between gap-5 py-3.5 text-left" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
            <span className="min-w-0">
              <span className="block text-label font-medium leading-5 text-ink">Advanced</span>
              <span className="mt-0.5 block text-hint leading-[1.45] text-ink-soft">Every copy on disk, where they're kept, and an export.</span>
            </span>
            <ChevronDownIcon size={16} className={`shrink-0 text-ink-faint transition-transform duration-200 ${advanced ? "rotate-180" : ""}`} />
          </button>
          <Collapse open={advanced}>
            <div className="border-t border-line">
              <p className="py-3.5 text-hint leading-[1.45] text-ink-soft">
                What stays: the newest copy in each of the last 3 hours, 9 days and 4 weeks; also what you made in the
                last day, the two from before the last updates, and the one from before a restore for a week. The same
                data is never copied twice.
              </p>
              {data && (
                <ControlRow label="Folder" hint={<>{items.length} {items.length === 1 ? "copy" : "copies"}, {size(items.reduce((n, b) => n + b.bytes, 0))} in all, in <span className="break-all">{data.folder}</span></>} wrap>
                  {inApp && (
                    <button className="btn btn-sm btn-soft" onClick={() => revealInFinder(data.folder)}>
                      <FolderIcon size={16} /> Show in Finder
                    </button>
                  )}
                </ControlRow>
              )}
              {items.length > 0 && (
                <ul className="divide-y divide-line border-t border-line">
                  {items.map((b) => (
                    <li key={b.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                      <div className="min-w-0">
                        <div className="text-label font-medium">{when(b.created_at)}</div>
                        <div className="text-hint text-ink-soft">
                          {[b.kinds.map((k) => KIND[k]).join(", ") + (b.update ? ` (${b.update})` : ""), size(b.bytes), holds(b.counts)].filter(Boolean).join(" · ")}
                        </div>
                      </div>
                      <div className="flex gap-1.5">
                        {restoreButton(b)}
                        <button className="icon-btn" aria-label={`Delete the backup from ${when(b.created_at)}`} disabled={busy !== null} onClick={() => void remove(b)}>
                          <TrashIcon size={16} />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
              <div className="border-t border-line">
                <ControlRow label="Export everything" hint={exportHint} wrap>
                  <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void exportAll()}>
                    {busy === "export" ? <Spinner /> : <DownloadIcon size={16} />} Export
                  </button>
                </ControlRow>
                {exported && (
                  <p className="flex animate-fade-in items-start gap-1.5 py-3.5 text-hint leading-snug text-forest-deep">
                    <CheckIcon size={16} className="mt-px shrink-0" />
                    <span className="break-words">Saved {exported.name} in {exported.folder} ({exported.text}).</span>
                  </p>
                )}
              </div>
            </div>
          </Collapse>
        </div>
      </Section>
      {dialog}
    </>
  );
}
