// Settings: what the app keeps for you. Daily backups you can restore, and a plain JSON copy of everything.
import { useState } from "react";
import { api } from "../api";
import type { BackupItem } from "../api";
import { Section } from "../components/blocks";
import { AlertIcon, CheckIcon, DownloadIcon, FolderIcon, RefreshIcon, TrashIcon } from "../components/icons";
import { ControlRow, Spinner, useConfirm } from "../components/ui";
import { useLive } from "../live";
import { useShell } from "../shell";
import { exportHint, restoreBody } from "@identity/copy";

const KIND: Record<BackupItem["kind"], string> = {
  auto: "Daily",
  manual: "Made by you",
  "before-restore": "Kept before a restore",
  "before-update": "Kept before an update",
};

function size(bytes: number) {
  return bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export default function YourData() {
  const { toast } = useShell();
  const [confirm, dialog] = useConfirm();
  const { data, reload } = useLive(api.backups);
  const [busy, setBusy] = useState<string | null>(null);
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

  return (
    <>
      <Section icon={<FolderIcon size={16} />} title="Your data" blurb="A copy is made each day and kept for two weeks, and another before an update changes anything. They stay in this Mac's data folder, private to you, and aren't sent anywhere.">
        <ControlRow label="Back up now" hint={data ? `Saved in ${data.folder}. Use Show Data Folder in the menu bar to open it.` : undefined} wrap>
          <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void backUp()}>
            {busy === "backup" ? <Spinner /> : <RefreshIcon size={16} />} Back up
          </button>
        </ControlRow>
        {data?.items.length ? (
          <ul className="divide-y divide-line">
            {data.items.map((b) => (
              <li key={b.name} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                <div className="min-w-0">
                  <div className="text-label font-medium">{when(b.created_at)}</div>
                  <div className="text-hint text-ink-soft">{KIND[b.kind]} · {size(b.bytes)}</div>
                </div>
                <div className="flex gap-1.5">
                  <button className="btn btn-sm btn-soft" disabled={busy !== null} onClick={() => void restore(b)}>
                    {busy === b.name ? <Spinner /> : <RefreshIcon size={16} />} Restore
                  </button>
                  <button className="icon-btn" aria-label={`Delete the backup from ${when(b.created_at)}`} disabled={busy !== null} onClick={() => void remove(b)}>
                    <TrashIcon size={16} />
                  </button>
                </div>
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
      </Section>
      {dialog}
    </>
  );
}
