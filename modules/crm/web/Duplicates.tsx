// Records that look like one person (or organization) twice. They're only flagged: you merge them, and any merge
// can be undone from the record that was kept.
import { useState } from "react";
import { CheckIcon, MergeIcon, RefreshIcon } from "@core/components/icons";
import { PageHeader, Skeleton, Spinner } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { DuplicatePair, DuplicateSide, Entity } from "./api";
import { Avatar, Empty } from "./bits";
import { Dialog } from "./forms";
import { formatDate } from "./format";

/** The record to keep unless you choose otherwise: you, then the one with more on it, then the older one. */
function keeper(p: DuplicatePair): DuplicateSide {
  const { a, b } = p;
  if (a.is_self !== b.is_self) return a.is_self ? a : b;
  if (a.degree !== b.degree) return a.degree > b.degree ? a : b;
  return (a.created_at ?? "") <= (b.created_at ?? "") ? a : b;
}

function sideLine(s: DuplicateSide): string {
  const bits = [s.subtitle, s.email, `${s.degree} link${s.degree === 1 ? "" : "s"}`];
  if (s.created_at) bits.push(`added ${formatDate(s.created_at)}`);
  return bits.filter(Boolean).join(" · ");
}

function MergePairDialog({ pair, onClose, onMerged }: { pair: DuplicatePair; onClose: () => void; onMerged: (keptId: string) => void }) {
  const { toast } = useShell();
  const [keep, setKeep] = useState(keeper(pair).id);
  const [busy, setBusy] = useState(false);
  const kept = keep === pair.a.id ? pair.a : pair.b;
  const gone = keep === pair.a.id ? pair.b : pair.a;
  const run = async () => {
    setBusy(true);
    try {
      await crmApi.mergePair(pair.id, keep);
      toast(`Merged ${gone.name} into ${kept.name}. You can undo it from ${kept.name}'s page.`);
      onMerged(keep);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title="Merge these two?" onClose={onClose} width={560}>
      <p className="text-ui text-ink-soft">Choose the record to keep. The other one&apos;s meetings, notes, relationships and details move onto it, and its name is kept as another way of writing it.</p>
      <div className="mt-4 space-y-2" role="radiogroup" aria-label="Record to keep">
        {[pair.a, pair.b].map((s) => (
          <label key={s.id} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 ${keep === s.id ? "border-forest bg-forest-soft/40" : "border-line"}`}>
            <input type="radio" name="keep" className="accent-forest" checked={keep === s.id} onChange={() => setKeep(s.id)} />
            <Avatar id={s.id} name={s.name} kind={s.kind} size={32} />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-label font-medium">{s.name}{s.is_self && " (you)"}</span>
              <span className="block truncate text-hint text-ink-soft">{sideLine(s)}</span>
            </span>
            {keep === s.id && <span className="chip bg-forest-soft text-forest-deep">keep</span>}
          </label>
        ))}
      </div>
      <p className="mt-3 text-hint text-ink-soft">Nothing is thrown away: {gone.name} is kept as it was, so the merge can be undone later.</p>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-md btn-primary" disabled={busy} onClick={() => void run()}>
          {busy ? <Spinner /> : <MergeIcon size={18} />} Merge into {kept.name}
        </button>
      </div>
    </Dialog>
  );
}

/** One flagged pair, with why it was flagged and what you can do about it. `here`: the record whose page this is. */
function PairRow({ pair, here }: { pair: DuplicatePair; here?: string }) {
  const { toast } = useShell();
  const [merging, setMerging] = useState(false);
  const notSame = async () => {
    try {
      await crmApi.notSame(pair.id);
      toast("Marked as different. They won't be flagged again.");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const sides = here ? [pair.a.id === here ? pair.b : pair.a] : [pair.a, pair.b];
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2.5 px-5 py-3.5">
      <div className="min-w-56 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {sides.map((s, i) => (
            <span key={s.id} className="inline-flex min-w-0 items-center gap-2">
              {i > 0 && <span className="text-ink-faint">and</span>}
              <Avatar id={s.id} name={s.name} kind={s.kind} size={24} />
              <a href={`#/crm/e/${s.id}`} className="truncate text-label font-medium hover:underline">{s.name}{s.is_self && " (you)"}</a>
            </span>
          ))}
        </div>
        {here && <p className="mt-0.5 truncate text-hint text-ink-soft">{sideLine(sides[0])}</p>}
        <div className="mt-1.5 flex flex-wrap gap-1">
          {pair.reasons.map((r) => <span key={r} className="chip bg-surface-subtle text-ink-soft">{r}</span>)}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <button className="btn btn-sm btn-soft" onClick={() => setMerging(true)}><MergeIcon size={16} /> Merge…</button>
        <button className="btn btn-sm btn-ghost" onClick={() => void notSame()}>Not the same</button>
      </div>
      {merging && (
        <MergePairDialog pair={pair} onClose={() => setMerging(false)}
          onMerged={(keptId) => { setMerging(false); if (here && keptId !== here) navigate(`crm/e/${keptId}`); }} />
      )}
    </li>
  );
}

export default function DuplicatesPage() {
  const { toast } = useShell();
  const { data, error } = useLive(() => crmApi.duplicates(), []);
  const [looking, setLooking] = useState(false);
  const look = async () => {
    setLooking(true);
    try {
      await crmApi.checkDuplicates();
      toast("Looking again. New pairs appear here in a moment.");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setLooking(false);
    }
  };
  return (
    <>
      <PageHeader
        title="Possible duplicates"
        subtitle="Records that look like the same person or organization twice. Nothing is merged until you say so, and a merge can be undone."
        actions={<button className="btn btn-sm btn-soft" disabled={looking} onClick={() => void look()}><RefreshIcon size={16} /> Look again</button>}
      />
      <div className="animate-enter" style={{ animationDelay: "60ms" }}>
        {error && <p className="text-ui text-trail-deep">{error}</p>}
        {!data && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && data.items.length === 0 && (
          <Empty icon={<CheckIcon size={20} />} title="No duplicates found">The book is checked again whenever something is added.</Empty>
        )}
        {data && data.items.length > 0 && (
          <ul className="panel divide-y divide-line overflow-hidden">
            {data.items.map((p) => <PairRow key={p.id} pair={p} />)}
          </ul>
        )}
      </div>
    </>
  );
}

/** On a record's page: the records it might be a duplicate of. Shows nothing when there are none. */
export function DuplicatesCard({ entity }: { entity: Entity }) {
  const { data } = useLive(() => crmApi.duplicates(entity.id), [entity.id]);
  if (!data?.items.length) return null;
  return (
    <section className="panel overflow-hidden">
      <header className="flex items-center gap-3 px-5 pt-4">
        <span className="well"><MergeIcon size={16} /></span>
        <h2 className="text-label font-medium">Might be the same {entity.kind === "person" ? "person" : "organization"} as</h2>
      </header>
      <ul className="divide-y divide-line">
        {data.items.map((p) => <PairRow key={p.id} pair={p} here={entity.id} />)}
      </ul>
    </section>
  );
}

/** On a record's page: records merged into it, each of which can be split off again. */
export function MergedCard({ entity }: { entity: Entity }) {
  const { toast, confirm } = useShell();
  const { data } = useLive(() => crmApi.merges(entity.id), [entity.id]);
  if (!data?.length) return null;
  const undo = async (id: string, name: string) => {
    if (!(await confirm({ title: `Split ${name} off again?`, body: `${name} comes back as its own record with its own meetings, notes and relationships. Anything added to ${entity.name} since stays with ${entity.name}.`, confirmLabel: "Undo merge" }))) return;
    try {
      const back = await crmApi.undoMerge(id);
      toast(`${back.name} is its own record again.`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  return (
    <div className="inset-surface px-5 py-3">
      <ul className="space-y-1.5">
        {data.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-3">
            <MergeIcon size={16} className="shrink-0 text-ink-faint" />
            <p className="min-w-0 flex-1 text-ui text-ink-soft">{m.name} was merged into this record on {formatDate(m.created_at)}.</p>
            <button className="btn btn-sm btn-ghost" onClick={() => void undo(m.id, m.name)}>Undo merge</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
