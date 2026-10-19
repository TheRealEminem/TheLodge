// Larger pieces built from the design kit, shared by the host and every module.
import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { api } from "../api";
import type { Job, Linked } from "../api";
import { useLive } from "../live";
import { useShell } from "../shell";
import { initials } from "../format";
import { Badge } from "./illustrations";
import { AlertIcon, RefreshIcon } from "./icons";
import { Spinner, StatusChip } from "./ui";

/** A settings-style section: a forest well, a heading with a one-line blurb, then a panel of rows. */
export function Section({
  icon,
  title,
  blurb,
  delay = 0,
  children,
}: {
  icon: ReactNode;
  title: string;
  blurb?: string;
  delay?: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-10 animate-enter" style={{ animationDelay: `${delay}ms` } as CSSProperties}>
      <div className="mb-3 flex items-start gap-3 px-1">
        <span className="well well-forest">{icon}</span>
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.01em]">{title}</h2>
          {blurb && <p className="mt-0.5 text-ui leading-snug text-ink-soft">{blurb}</p>}
        </div>
      </div>
      <div className="panel divide-y divide-line px-5 sm:px-6">{children}</div>
    </section>
  );
}

/** A thing's background job as a chip, for list rows. Nothing when there's nothing to say. */
export function JobChip({ job }: { job: Job | null | undefined }) {
  if (!job || job.status === "done") return null;
  if (job.status === "running") return <StatusChip tone="sky" label={job.stage || "Working"} live />;
  if (job.status === "queued") return <StatusChip tone="neutral" label="Queued" />;
  if (job.status === "waiting") return <StatusChip tone="sun" label={job.wait_reason || "Needs you"} />;
  return <StatusChip tone="trail" label="Failed" />;
}

/** A thing's background job with what you can do about it: start it, go ahead anyway, or retry. */
export function JobStatus({ job, startLabel = "Start" }: { job: Job | null | undefined; startLabel?: string }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  if (!job || job.status === "done") return null;
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  if (job.status === "error") {
    return (
      <div className="flex animate-enter items-start gap-3 rounded-lg border border-trail/20 bg-trail-soft/70 p-4 text-label text-trail-deep">
        <AlertIcon size={18} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">That didn't go through</div>
          <div className="mt-0.5 break-words opacity-90">{job.error}</div>
        </div>
        <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => act(() => api.jobRetry(job.id))}>
          <RefreshIcon size={16} />
          Try again
        </button>
      </div>
    );
  }
  if (job.status === "waiting") {
    const needsYou = !job.wait_reason || job.wait_reason === "Needs you";
    return (
      <div className="flex animate-enter flex-wrap items-center gap-3">
        <StatusChip tone="sun" label={job.wait_reason || "Needs you"} />
        <button
          className={`btn btn-sm ${needsYou ? "btn-sun" : "btn-soft"}`}
          disabled={busy}
          onClick={() => act(() => api.jobGo(job.id, !needsYou))}
        >
          {needsYou ? startLabel : "Go ahead anyway"}
        </button>
      </div>
    );
  }
  return (
    <div className="flex animate-fade-in items-center gap-2 text-ui text-ink-soft">
      <Spinner className="text-sky" />
      {job.status === "queued" ? "Queued" : job.stage || "Working…"}
    </div>
  );
}

/** Everything linked to `of` (a ref, "notes:<id>"), from any module, each described by its own module. */
export function LinkedList({ of, title = "Linked" }: { of: string; title?: string }) {
  const { app } = useShell();
  const { data } = useLive(() => api.links(of), [of]);
  if (!data?.length) return null;
  const moduleName = (id: string) => app.modules.find((m) => m.id === id)?.name ?? id;
  return (
    <section className="mt-10 animate-enter">
      <h2 className="eyebrow mb-2 px-1">{title}</h2>
      <div className="panel divide-y divide-line px-2">
        {data.map((l: Linked) => (
          <a key={l.ref + l.kind} href={l.href} className="flex items-center justify-between gap-3 rounded-md px-3 py-3 transition-colors hover:bg-forest/[.04]">
            <span className="min-w-0 truncate text-label">{l.title}</span>
            <span className="shrink-0 text-meta text-ink-soft">{moduleName(l.module)}</span>
          </a>
        ))}
      </div>
    </section>
  );
}

/** A text setting that saves when you leave the field or press Return. */
export function TextSetting({
  value,
  onSave,
  placeholder,
  mono,
  className = "w-full sm:w-64",
  label,
}: {
  value: string;
  onSave: (v: string) => void;
  placeholder?: string;
  mono?: boolean;
  className?: string;
  label: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => draft !== value && onSave(draft.trim());
  return (
    <input
      aria-label={label}
      className={`field ${mono ? "font-mono text-hint" : ""} ${className}`}
      value={draft}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
    />
  );
}

/** An API key: never shown again once saved, only a hint of its end. */
export function SecretSetting({ hint, onSave, label }: { hint: string | null | undefined; onSave: (v: string) => void; label: string }) {
  const [draft, setDraft] = useState("");
  return (
    <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
      <input
        type="password"
        aria-label={label}
        autoComplete="off"
        className="field min-w-0 flex-1 font-mono text-hint sm:w-60 sm:flex-none"
        placeholder={hint ? `Saved (${hint})` : "Paste a key"}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && draft.trim()) {
            onSave(draft.trim());
            setDraft("");
          }
        }}
      />
      <button
        className="btn btn-sm btn-soft"
        disabled={!draft.trim()}
        onClick={() => {
          onSave(draft.trim());
          setDraft("");
        }}
      >
        Save
      </button>
      {hint && !draft && (
        <button className="btn btn-sm btn-danger-ghost" onClick={() => onSave("")}>
          Remove
        </button>
      )}
    </div>
  );
}

/** Initials in a soft tile: round for people, rounded-square for everything else (an organization, a project). */
export function Avatar({ name, round = true, size = 36 }: { name: string; round?: boolean; size?: number }) {
  return (
    <span
      aria-hidden="true"
      className={`grid shrink-0 place-items-center bg-surface-subtle font-semibold text-ink-soft ${round ? "rounded-full" : "rounded-sm"}`}
      style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }}
    >
      {initials(name)}
    </span>
  );
}

/** Up to `max` tags as quiet chips. */
export function Tags({ tags, max = 2 }: { tags: string[]; max?: number }) {
  return (
    <>
      {tags.slice(0, max).map((t) => (
        <span key={t} className="chip bg-surface-subtle text-ink-soft">
          #{t}
        </span>
      ))}
    </>
  );
}

/** An empty list or page: the identity's badge around an icon, a title, and a line on what will appear here. */
export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="inset-surface px-4 py-12 text-center">
      <Badge>{icon}</Badge>
      <p className="mt-3 font-medium">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-sm text-ui text-ink-soft">{children}</p>}
    </div>
  );
}
