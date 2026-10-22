// Small pieces the project screens share: progress, health, and a project's tile.
import { StatusChip } from "@core/components/ui";
import type { Health, Meta, Rollup } from "./api";

/** A 6px bar with the words beside it, never a bare percentage (the Lodge blueprint §8). */
export function Progress({ rollup, className = "" }: { rollup: Rollup; className?: string }) {
  const pct = rollup.progress == null ? 0 : Math.round(rollup.progress * 100);
  const words = rollup.counted ? `${rollup.done} of ${rollup.counted} done` : "No tasks yet";
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <div
        role="progressbar"
        aria-label="Progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-valuetext={words}
        className="h-1.5 min-w-[3rem] flex-1 overflow-hidden rounded-full bg-line-strong"
      >
        <div className="h-full rounded-full bg-forest transition-[width] duration-500 ease-out" style={{ width: `${pct}%` }} />
      </div>
      <span className="shrink-0 whitespace-nowrap text-meta tabular-nums text-ink-soft">{words}</span>
    </div>
  );
}

export function HealthChip({ health, meta }: { health: Health | null; meta: Meta | null }) {
  const h = health ? meta?.health.find((x) => x.value === health) : null;
  return h ? <StatusChip tone={h.tone} label={h.label} /> : null;
}

/** A project's tile: its initial on a rounded square. Projects get no colors; color is for meaning. */
export function ProjectTile({ name, size = 36 }: { name: string; size?: number }) {
  const letter = (name.trim()[0] ?? "?").toUpperCase();
  return (
    <span
      aria-hidden="true"
      className="grid shrink-0 place-items-center rounded-sm bg-surface-subtle font-semibold text-ink-soft"
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
    >
      {letter}
    </span>
  );
}
