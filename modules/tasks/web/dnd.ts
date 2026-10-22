// Dragging tasks between and within lists (the project list view, the board), with the browser's own drag and drop.
// A list is a drop zone: while a task is over it, it knows where the task would land (a line is drawn there), and
// on drop it reports the task and the one it should go right after (null for first). Keyboard moves (Alt + arrows)
// are handled by each view, and end in the same call.
import { useCallback, useState, useSyncExternalStore } from "react";
import type { CSSProperties, DragEvent } from "react";

export const TASK_TYPE = "application/x-trailmix-task";

// Which task is being dragged right now, so empty lists can show where to drop it.
let dragging: string | null = null;
const listeners = new Set<() => void>();
const setDragging = (id: string | null) => {
  dragging = id;
  listeners.forEach((l) => l());
};
export function useDragging(): string | null {
  return useSyncExternalStore(
    (on) => {
      listeners.add(on);
      return () => listeners.delete(on);
    },
    () => dragging,
  );
}

/** What a draggable task needs: drag it, and look faded while it's being dragged. */
export function dragProps(id: string, current: string | null) {
  return {
    draggable: true,
    "data-drag-id": id,
    onDragStart: (e: DragEvent<HTMLElement>) => {
      e.dataTransfer.setData(TASK_TYPE, id);
      e.dataTransfer.effectAllowed = "move";
      // Let the browser take its drag image first, then fade the original.
      window.setTimeout(() => setDragging(id), 0);
    },
    onDragEnd: () => setDragging(null),
    style: (current === id ? { opacity: 0.4 } : undefined) as CSSProperties | undefined,
  };
}

/**
 * Makes a list a drop zone. `ids` are its tasks in the order shown. While a task is over it, `at` is the index it
 * would take (0 = first, ids.length = last); `lineFor(i)` styles the row that gets the line above (or, for the
 * last place, below) it.
 */
export function useDropZone(ids: string[], onDrop: (id: string, afterId: string | null) => void, between: "rows" | "cards" = "rows") {
  const [at, setAt] = useState<number | null>(null);

  const place = (e: DragEvent<HTMLElement>) => {
    const rows = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[data-drag-id]"));
    const i = rows.findIndex((r) => {
      const box = r.getBoundingClientRect();
      return e.clientY < box.top + box.height / 2;
    });
    return i === -1 ? rows.length : i;
  };

  const zone = {
    onDragOver: (e: DragEvent<HTMLElement>) => {
      if (!e.dataTransfer.types.includes(TASK_TYPE)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setAt(place(e));
    },
    onDragLeave: (e: DragEvent<HTMLElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setAt(null);
    },
    onDrop: (e: DragEvent<HTMLElement>) => {
      const id = e.dataTransfer.getData(TASK_TYPE);
      const i = place(e);
      setAt(null);
      setDragging(null);
      if (!id) return;
      e.preventDefault();
      if (ids.includes(id) && (ids[i] === id || ids[i - 1] === id)) return; // dropped where it already is
      const before = ids.slice(0, i).filter((x) => x !== id);
      onDrop(id, before.length ? before[before.length - 1] : null);
    },
  };

  const lineFor = useCallback(
    (i: number): CSSProperties | undefined => {
      if (at === null) return undefined;
      // Rows touch, so the line sits inside the row's edge; cards have a gap, so it sits in the gap.
      const above = between === "rows" ? "inset 0 2px 0 0 var(--forest)" : "0 -6px 0 -4px var(--forest)";
      const below = between === "rows" ? "inset 0 -2px 0 0 var(--forest)" : "0 6px 0 -4px var(--forest)";
      if (i === at) return { boxShadow: above };
      if (at === ids.length && i === ids.length - 1) return { boxShadow: below };
      return undefined;
    },
    [at, ids.length, between],
  );

  return { zone, at, lineFor };
}

/** Where a task goes when it moves one place up or down with the keyboard: the id to put it after (null = first). */
export function afterForStep(ids: string[], id: string, step: -1 | 1): string | null | undefined {
  const i = ids.indexOf(id);
  const j = i + step;
  if (i === -1 || j < 0 || j >= ids.length) return undefined; // already at the end
  const without = ids.filter((x) => x !== id);
  const target = step === 1 ? without.indexOf(ids[j]) : without.indexOf(ids[j]) - 1;
  return target >= 0 ? without[target] : null;
}
