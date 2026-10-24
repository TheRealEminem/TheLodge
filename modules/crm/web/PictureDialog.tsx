// Adding, replacing or removing a picture: choose a file, drop one, paste one, or (when allowed) ask Gravatar.
import { useEffect, useRef, useState } from "react";
import { CloseIcon, SearchIcon, TrashIcon } from "@core/components/icons";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity } from "./api";
import { Avatar } from "./bits";
import { Dialog } from "./forms";
import { toSquare, usePictures } from "./pictures";

/** The first picture on the clipboard or in a drop, if any. */
function firstImage(items: DataTransferItemList | undefined, files: FileList | undefined): Blob | null {
  for (const f of Array.from(files ?? [])) if (f.type.startsWith("image/")) return f;
  for (const item of Array.from(items ?? [])) if (item.type.startsWith("image/")) return item.getAsFile();
  return null;
}

export function PictureDialog({ entity, onClose }: { entity: Entity; onClose: () => void }) {
  const { toast } = useShell();
  const has = !!usePictures()[entity.id];
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const canLookUp = entity.kind === "person" && !!entity.attributes?.email;

  const run = async (work: () => Promise<string | void>) => {
    setBusy(true);
    try {
      const said = await work();
      if (said) toast(said);
      else onClose();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const save = (blob: Blob) => run(async () => void (await crmApi.putPicture(entity.id, await toSquare(blob))));

  // ⌘V anywhere in the dialog.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const blob = firstImage(e.clipboardData?.items, e.clipboardData?.files);
      if (blob) {
        e.preventDefault();
        void save(blob);
      }
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  });

  const pasteButton = () =>
    run(async () => {
      const clip = await navigator.clipboard.read().catch(() => {
        throw new Error("The window wouldn't let me read the clipboard. Press ⌘V instead.");
      });
      for (const item of clip) {
        const type = item.types.find((t) => t.startsWith("image/"));
        if (type) {
          await crmApi.putPicture(entity.id, await toSquare(await item.getType(type)));
          return;
        }
      }
      return "There's no picture on the clipboard. Copy one first, then paste.";
    });

  return (
    <Dialog title={`Picture of ${entity.name}`} onClose={onClose} width={440}>
      <div className="flex flex-col items-center gap-4">
        <Avatar id={entity.id} name={entity.name} kind={entity.kind} size={112} />
        <div
          className={`w-full rounded-lg border border-dashed px-4 py-6 text-center text-label text-ink-soft transition-colors ${over ? "border-forest bg-forest-soft/40" : "border-line"}`}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const blob = firstImage(e.dataTransfer.items, e.dataTransfer.files);
            if (blob) void save(blob);
            else toast("That wasn't a picture.", "error");
          }}
        >
          Drop a picture here
          <div className="mt-3 flex flex-wrap justify-center gap-2">
            <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => input.current?.click()}>Choose a file</button>
            <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => void pasteButton()}>Paste</button>
          </div>
          <input ref={input} type="file" accept="image/*" hidden onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) void save(f); }} />
        </div>
        <p className="text-hint text-ink-faint">
          LinkedIn doesn't let apps fetch photos. Right-click one in your browser, copy it, and paste it here.
        </p>
        <div className="flex w-full flex-wrap justify-between gap-2">
          {canLookUp ? (
            <button
              className="btn btn-sm btn-ghost"
              disabled={busy}
              data-tip="Sends a scrambled form of their email address to Gravatar. Needs Looking up pictures turned on in Settings."
              onClick={() => void run(async () => ((await crmApi.lookUpPicture(entity.id)).found ? undefined : "Gravatar has no picture for them."))}
            >
              <SearchIcon size={16} /> Look up on Gravatar
            </button>
          ) : <span />}
          <div className="flex gap-2">
            {has && (
              <button className="btn btn-sm btn-danger-ghost" disabled={busy} onClick={() => void run(async () => void (await crmApi.deletePicture(entity.id)))}>
                <TrashIcon size={16} /> Remove
              </button>
            )}
            <button className="btn btn-sm btn-ghost" onClick={onClose}><CloseIcon size={16} /> Close</button>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
