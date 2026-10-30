// The pieces Sediment's pages share: how a stance looks, the gauge, the layers, one reading, and a dialog.
import { useEffect } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { api } from "@core/api";
import type { Job } from "@core/api";
import { AlertIcon, CloseIcon, RefreshIcon, TrashIcon } from "@core/components/icons";
import { Skeleton, Spinner } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useShell } from "@core/shell";
import { sedimentApi } from "./api";
import type { Lean, Reading, Stance } from "./api";

export const firstName = (name: string) => name.trim().split(/\s+/)[0];

/** Warm sits on lake blue and cool on lantern, mixed and unknown in between: the blue–yellow axis colorblind eyes keep
 * (identity/DESIGN.md), never ember, and every stance is always shown with its word. */
export const STANCE: Record<Stance, { word: string; band: string; chip: string }> = {
  very_warm: { word: "Very warm", band: "bg-forest", chip: "bg-forest-soft text-forest-deep" },
  warm: { word: "Warm", band: "bg-forest/55", chip: "bg-forest-soft text-forest-deep" },
  mixed: { word: "Mixed", band: "bg-ink-faint/45", chip: "bg-surface-subtle text-ink-soft" },
  cool: { word: "Cool", band: "bg-sun/60", chip: "bg-sun-soft text-sun-deep" },
  very_cool: { word: "Very cool", band: "bg-sun", chip: "bg-sun-soft text-sun-deep" },
  unknown: { word: "Not enough on file", band: "bg-surface-subtle border border-dashed border-line-strong", chip: "bg-surface-subtle text-ink-soft" },
};
const SCALE: Stance[] = ["very_cool", "cool", "mixed", "warm", "very_warm"];
const LEAN: Record<Lean, { mark: string; word: string }> = {
  warm: { mark: "bg-forest", word: "Leans warm" },
  cool: { mark: "bg-sun", word: "Leans cool" },
  neutral: { mark: "bg-ink-faint/60", word: "Neutral" },
};
const CONFIDENCE = { low: "Low confidence", medium: "Medium confidence", high: "High confidence" };

export function StanceChip({ stance }: { stance: Stance | null }) {
  const s = STANCE[stance ?? "unknown"];
  return <span className={`chip ${s.chip}`}>{s.word}</span>;
}

/** Five steps from very cool to very warm, the reading's step filled. */
export function Gauge({ stance }: { stance: Stance }) {
  const at = SCALE.indexOf(stance);
  return (
    <div role="img" aria-label={`Stance: ${STANCE[stance].word}`}>
      <div className="flex gap-1">
        {SCALE.map((s, i) => (
          <span key={s} className={`h-2.5 flex-1 rounded-full ${i === at ? STANCE[s].band : "bg-ink-faint/20"}`} />
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-meta text-ink-soft">
        <span>Very cool</span>
        <span>Mixed</span>
        <span>Very warm</span>
      </div>
    </div>
  );
}

/** Every reading of one subject, newest on top, like the layers in a core of lake sediment. */
export function Layers({ readings, active, onPick }: { readings: Reading[]; active: string | null; onPick: (id: string) => void }) {
  const done = readings.filter((r) => r.status === "done");
  if (done.length < 2) return null;
  return (
    <div className="mt-5 border-t border-line pt-4">
      <p className="mb-2 text-ui font-medium">Layers</p>
      <p className="mb-3 text-hint text-ink-soft">Each reading of this, newest on top.</p>
      <ol className="space-y-1">
        {done.map((r) => (
          <li key={r.id}>
            <button
              className={`flex w-full items-center gap-3 rounded-md px-2 py-1 text-left transition-colors hover:bg-forest/[.05] ${r.id === active ? "bg-forest/[.07]" : ""}`}
              onClick={() => onPick(r.id)}
              aria-pressed={r.id === active}
            >
              <span className={`h-3 w-28 shrink-0 rounded-sm sm:w-40 ${STANCE[r.stance ?? "unknown"].band}`} aria-hidden />
              <span className="min-w-0 flex-1 truncate text-label">{STANCE[r.stance ?? "unknown"].word}</span>
              <span className="shrink-0 text-meta text-ink-soft">{formatDate(r.read_at)}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}

function List({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <p className="text-ui font-medium">{title}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-label text-ink-soft">
        {items.map((x) => <li key={x}>{x}</li>)}
      </ul>
    </div>
  );
}

/** Work parked until the AI can take it (memory, a rate limit), with Go ahead anyway. The reason can be long ("Waiting
 * for memory: … free up some disk space…"), so it wraps here instead of sitting in the host's one-line chip. */
export function Waiting({ job, cancel }: { job: Job; cancel?: { label: string; run: () => void } }) {
  const { toast } = useShell();
  return (
    <div className="space-y-3">
      <p className="flex items-start gap-2 text-ui">
        <span className="mt-[7px] h-2 w-2 shrink-0 rounded-full bg-sun" aria-hidden />
        <span className="min-w-0 break-words">Waiting to start. {job.wait_reason}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        <button className="btn btn-sm btn-soft" onClick={() => api.jobGo(job.id, true).catch((e: Error) => toast(e.message, "error"))}>Go ahead anyway</button>
        {cancel && <button className="btn btn-sm btn-ghost" onClick={cancel.run}>{cancel.label}</button>}
      </div>
      <p className="text-hint text-ink-soft">It starts by itself once the AI can take it.</p>
    </div>
  );
}

/** One reading: the stance, how sure, why, and the evidence it rests on. */
export function ReadingView({ reading, first, provider }: { reading: Reading; first: string; provider: string }) {
  const { toast, confirm } = useShell();
  const retry = () => sedimentApi.retry(reading.id).catch((e: Error) => toast(e.message, "error"));
  const remove = async () => {
    if (!(await confirm({ title: "Delete this reading?", body: "Only this reading goes. Nothing in People changes.", confirmLabel: "Delete", tone: "danger" }))) return;
    sedimentApi.remove(reading.id).catch((e: Error) => toast(e.message, "error"));
  };

  if (reading.status === "queued" && reading.job?.status === "waiting") {
    return <Waiting job={reading.job} cancel={{ label: "Cancel this reading", run: () => void remove() }} />;
  }
  if (reading.status === "queued") {
    return (
      <div className="space-y-2.5" aria-busy="true">
        <Skeleton className="h-2.5 w-full rounded-full" />
        <Skeleton className="h-3.5 w-11/12 rounded-full" />
        <Skeleton className="h-3.5 w-2/3 rounded-full" />
        <p className="flex items-center gap-2 pt-1 text-hint text-ink-soft"><Spinner className="text-sky" /> Reading what's on file about {first} with {provider}…</p>
      </div>
    );
  }
  if (reading.status === "error") {
    return (
      <div className="rounded-lg border border-trail/20 bg-trail-soft/70 px-4 py-3">
        <p className="flex items-start gap-1.5 text-ui text-trail-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" /><span className="break-words">The reading didn't come through. {reading.error}</span></p>
        <div className="mt-2.5 flex gap-2">
          <button className="btn btn-sm btn-soft" onClick={() => void retry()}><RefreshIcon size={16} /> Try again</button>
          <button className="btn btn-sm btn-ghost" onClick={() => void remove()}>Delete</button>
        </div>
      </div>
    );
  }

  const b = reading.body;
  const stance = reading.stance ?? "unknown";
  return (
    <div className="animate-fade-in">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <StanceChip stance={stance} />
        {reading.confidence && <span className="chip bg-surface-subtle text-ink-soft">{CONFIDENCE[reading.confidence]}</span>}
      </div>
      {stance !== "unknown" && <Gauge stance={stance} />}
      {b.summary && <p className="mt-4 text-body leading-relaxed">{b.summary}</p>}

      {!!b.evidence?.length && (
        <div className="mt-5">
          <p className="text-ui font-medium">Evidence</p>
          <ul className="mt-2 space-y-2.5">
            {b.evidence.map((e, i) => (
              <li key={i} className="flex gap-3">
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${LEAN[e.leans].mark}`} data-tip={LEAN[e.leans].word} aria-label={LEAN[e.leans].word} />
                <div className="min-w-0">
                  <p className="text-label">{e.quoted ? `“${e.text.replace(/^[“"]|[”"]$/g, "")}”` : e.text}</p>
                  <p className="mt-0.5 text-meta text-ink-soft">
                    {[e.quoted ? "Quoted from your records" : "Paraphrased", e.date ? formatDate(e.date) : "Undated", e.source].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <List title="What seems to drive it" items={b.drivers} />
        {b.change && (
          <div>
            <p className="text-ui font-medium">How it's changed</p>
            <p className="mt-1 text-label text-ink-soft">{b.change}</p>
          </div>
        )}
        <List title="What might help" items={b.helps} />
        <List title="Not on file" items={b.unknowns} />
      </div>

      <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
        <p className="text-meta text-ink-soft">
          Read by {reading.written_by} · {relativeTime(reading.read_at)}
          {b.estimate ? ` · about $${b.estimate < 0.01 ? "0.01" : b.estimate.toFixed(2)}` : ""}
        </p>
        <button className="btn btn-sm btn-danger-ghost" aria-label="Delete this reading" data-tip="Delete this reading" onClick={() => void remove()}>
          <TrashIcon size={16} />
        </button>
      </div>
    </div>
  );
}

/** A dialog with room for a form. Esc or a click outside closes it. */
export function Dialog({ title, onClose, children, width = 500 }: { title: string; onClose: () => void; children: ReactNode; width?: number }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex animate-fade-in items-center justify-center bg-[var(--scrim)] p-5 backdrop-blur-[3px]"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[90vh] w-full animate-dialog-in flex-col rounded-xl border border-line bg-surface shadow-lg" style={{ maxWidth: width }}>
        <header className="flex items-center justify-between border-b border-line px-6 py-4">
          <h2 className="text-lead font-semibold tracking-[-0.01em]">{title}</h2>
          <button className="icon-btn" aria-label="Close" onClick={onClose}><CloseIcon size={18} /></button>
        </header>
        <div className="overflow-y-auto p-6">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-ui font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-hint text-ink-soft">{hint}</span>}
    </label>
  );
}
