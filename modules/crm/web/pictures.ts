// Pictures of people: who has one (asked once, and again when anything changes), and making a chosen file small.
import { useEffect, useSyncExternalStore } from "react";
import { useChanges } from "@core/live";
import { crmApi } from "./api";

let known: Record<string, string> = {};
let lastSeq = -1;
const listeners = new Set<() => void>();

async function refresh() {
  try {
    const next = await crmApi.pictures();
    if (JSON.stringify(next) !== JSON.stringify(known)) {
      known = next;
      listeners.forEach((l) => l());
    }
  } catch {
    /* the server is restarting: the next change asks again */
  }
}

/** {record id: version} for everyone with a picture. Many avatars can ask; the server is asked once per change. */
export function usePictures(): Record<string, string> {
  const seq = useChanges();
  useEffect(() => {
    if (seq !== lastSeq) {
      lastSeq = seq;
      void refresh();
    }
  }, [seq]);
  return useSyncExternalStore(
    (on) => {
      listeners.add(on);
      return () => listeners.delete(on);
    },
    () => known,
  );
}

export const pictureUrl = (id: string, version: string) => `/api/crm/pictures/${id}?v=${encodeURIComponent(version)}`;

/** Any picture the browser can read, as a centred square of `size` pixels (JPEG), so only a few KB are kept. */
export async function toSquare(file: Blob, size = 256): Promise<Blob> {
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode().catch(() => {
      throw new Error("That file isn't a picture the app can read.");
    });
    const side = Math.min(img.naturalWidth, img.naturalHeight);
    if (!side) throw new Error("That picture is empty.");
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("This window can't resize pictures.");
    ctx.fillStyle = "#fff";                                 // JPEG has no transparency
    ctx.fillRect(0, 0, size, size);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, size, size);
    const out = await new Promise<Blob | null>((ok) => canvas.toBlob(ok, "image/jpeg", 0.85));
    if (!out) throw new Error("Couldn't make that picture smaller.");
    return out;
  } finally {
    URL.revokeObjectURL(url);
  }
}
