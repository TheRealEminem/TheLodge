// Settings: what the app keeps for you. A few points to go back to, every copy on disk under Advanced, and a plain
// JSON copy of everything.
import { useState } from "react";
import { api } from "../api";
import type { BackupItem } from "../api";
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

/** The few copies worth offering: the newest, the newest from before today, the newest at least a week old, and the
 *  one kept before the last update. The server's rotation keeps one for each of these. Newest first, no repeats. */
function choices(items: BackupItem[], now: number) {
  const at = (b: BackupItem) => new Date(b.created_at).getTime();
  const picks: { b: BackupItem; label: string }[] = [];
  const add = (b: BackupItem | undefined, label?: string) => {
    if (!b) return;
    const had = picks.find((p) => p.b.name === b.name);
    if (had) had.label = label ?? had.label;
    else picks.push({ b, label: label ?? ago(b.created_at, now) });
  };
  add(items[0]);
  add(items.find((b) => at(b) < startOfDay(now)));
  add(items.find((b) => at(b) <= now - 7 * DAY));
  add(items.find((b) => b.kind === "before-update"), "Before the last update");
  return picks.sort((x, y) => at(y.b) - at(x.b));
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
    const held = Object.entries(r.counts ?? {}).map(([what, n]) => `${n} ${what}`).join(", ");
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
  const restoreButton = (b: BackupItem) => (
    <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void restore(b)}>
      {busy === b.name ? <Spinner /> : <RefreshIcon size={16} />} Restore
    </button>
  );

  return (
    <>
      <Section icon={<FolderIcon size={16} />} title="Your data" blurb="A copy is made every hour, and another before an update changes anything. Older ones thin out on their own, to one a day for a week and one a week for a month. They stay in this Mac's data folder, private to you, and aren't sent anywhere.">
        <ControlRow label="Back up now" hint="Makes a copy of everything as it is right now." wrap>
          <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void backUp()}>
            {busy === "backup" ? <Spinner /> : <RefreshIcon size={16} />} Back up
          </button>
        </ControlRow>
        {items.length ? (
          <ul className="divide-y divide-line">
            {choices(items, Date.now()).map(({ b, label }) => (
              <li key={b.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                <div className="min-w-0">
                  <div className="text-label font-medium">{label}</div>
                  <div className="text-hint text-ink-soft">{when(b.created_at)}</div>
                </div>
                {restoreButton(b)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="flex items-start gap-1.5 py-3.5 text-hint text-ink-soft"><AlertIcon size={16} className="mt-px shrink-0" /> No backups yet. The first is made shortly after the app starts.</p>
        )}
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
        <div>
          <button type="button" className="flex w-full items-center justify-between gap-5 py-3.5 text-left" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
            <span className="min-w-0">
              <span className="block text-label font-medium leading-5 text-ink">Advanced</span>
              <span className="mt-0.5 block text-hint leading-[1.45] text-ink-soft">Every copy on disk, and where they're kept.</span>
            </span>
            <ChevronDownIcon size={16} className={`shrink-0 text-ink-faint transition-transform duration-200 ${advanced ? "rotate-180" : ""}`} />
          </button>
          <Collapse open={advanced}>
            <div className="border-t border-line">
              {data && (
                <p className="py-3.5 text-hint leading-[1.45] text-ink-soft">
                  {items.length} {items.length === 1 ? "copy" : "copies"}, {size(items.reduce((n, b) => n + b.bytes, 0))} in all, saved in{" "}
                  <span className="break-all">{data.folder}</span>. Use Show Data Folder in the menu bar to open it.
                </p>
              )}
              {items.length > 0 && (
                <ul className="divide-y divide-line border-t border-line">
                  {items.map((b) => (
                    <li key={b.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                      <div className="min-w-0">
                        <div className="text-label font-medium">{when(b.created_at)}</div>
                        <div className="text-hint text-ink-soft">{KIND[b.kind]} · {size(b.bytes)}</div>
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
            </div>
          </Collapse>
        </div>
      </Section>
      {dialog}
    </>
  );
}
