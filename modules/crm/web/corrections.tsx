// Putting right what an import got wrong: a meeting or document on the wrong person, and the links it only guessed at.
// The server half is corrections.py.
import { useEffect, useMemo, useState } from "react";
import { AlertIcon, CloseIcon } from "@core/components/icons";
import { PageHeader, Segmented, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { EntityKind, EntitySummary, LinkCheck, SourcePreview } from "./api";
import { EntityLink, Empty } from "./bits";
import { formatDate } from "./format";
import { Dialog, EntityPicker, Field } from "./forms";

type Who = { id: string; name: string; kind: EntityKind };
type Mode = "new" | "existing" | "remove";

/** "This isn't them": move what a meeting or document said to whoever it's really about, or just take it off. */
export function NotThisDialog({ who, evidence, onClose }: { who: Who; evidence: { id: string; name: string }; onClose: () => void }) {
  const { toast } = useShell();
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [mode, setMode] = useState<Mode>("new");
  const [name, setName] = useState("");
  const [target, setTarget] = useState<EntitySummary | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    crmApi.sourcePreview(who.id, evidence.id).then((p) => {
      setPreview(p);
      // What the source called them is the likeliest name for whoever it's really about.
      if (p.written && p.written.toLowerCase() !== who.name.toLowerCase()) setName(p.written);
    }, (e: Error) => toast(e.message, "error"));
  }, [who.id, who.name, evidence.id, toast]);

  const go = async () => {
    setBusy(true);
    try {
      const done = await crmApi.detachSource(who.id, evidence.id, mode === "new" ? { new_name: name.trim() } : mode === "existing" ? { to_id: target?.id } : {});
      toast(done.to ? `${evidence.name} is on ${done.to.name} now.` : `${evidence.name} is off ${who.name}.`);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  const ready = !busy && preview && (mode === "remove" || (mode === "new" ? name.trim() : target));
  const one = who.kind === "person" ? "person" : "organization";
  return (
    <Dialog title={`Not ${who.name}?`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-ui text-ink-soft">
          <span className="font-medium text-ink">{evidence.name}</span> is linked to {who.name}
          {preview?.written && preview.written.toLowerCase() !== who.name.toLowerCase() ? <>, because it says “{preview.written}”</> : null}.
        </p>
        {!preview && <Skeleton className="h-16 w-full rounded-lg" />}
        {preview && (preview.notes.length > 0 || preview.links.length > 0 || preview.fields.length > 0) && (
          <div className="inset-surface space-y-1.5 p-3.5 text-ui">
            <p className="text-meta font-medium text-ink-soft">This goes with it</p>
            <ul className="max-h-44 space-y-1 overflow-y-auto">
              {preview.fields.map((f) => <li key={f.label}><span className="text-ink-soft">{f.label}:</span> {f.value}</li>)}
              {preview.links.map((l) => <li key={l.id}>{l.label} {l.other}</li>)}
              {preview.notes.map((n) => <li key={n.id}>{n.body}</li>)}
            </ul>
          </div>
        )}
        <Segmented
          label="Who it's really about"
          value={mode}
          onChange={setMode}
          options={[{ id: "new" as const, label: `A new ${one}` }, { id: "existing" as const, label: "Someone on file" }, { id: "remove" as const, label: "Just take it off" }]}
        />
        {mode === "new" && (
          <Field label="Their name">
            <input className="field h-10 w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </Field>
        )}
        {mode === "existing" && (target ? (
          <div className="inset-surface flex items-center justify-between gap-3 px-3.5 py-2.5 text-ui">
            <span className="truncate font-medium">{target.name}{target.subtitle && <span className="font-normal text-ink-soft"> · {target.subtitle}</span>}</span>
            <button className="icon-btn h-7 w-7" aria-label="Choose someone else" onClick={() => setTarget(null)}><CloseIcon size={14} /></button>
          </div>
        ) : <EntityPicker kinds={[who.kind]} exclude={[who.id]} onSelect={setTarget} placeholder={`Find the ${one}`} autoFocus />)}
        <p className="text-hint text-ink-soft">The overview is written again from what's left. You can put this back.</p>
        <div className="flex justify-end gap-2">
          <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={!ready} onClick={() => void go()}>{mode === "remove" ? "Take it off" : "Move it"}</button>
        </div>
      </div>
    </Dialog>
  );
}

/** A research report filed on someone is really about someone else: its links, facts and text go to that person. */
export function ReportNotThemDialog({ who, report, onClose }: { who: { id: string; name: string }; report: { inbox_id: string; title: string }; onClose: () => void }) {
  const { toast } = useShell();
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [name, setName] = useState("");
  const [target, setTarget] = useState<EntitySummary | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      const done = await crmApi.moveReport(who.id, report.inbox_id, mode === "new" ? { new_name: name.trim() } : { to_id: target?.id });
      toast(`${report.title} is on ${done.to?.name} now.`);
      onClose();
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  return (
    <Dialog title={`Not ${who.name}?`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-ui text-ink-soft"><span className="font-medium text-ink">{report.title}</span> is filed on {who.name}. Its links, facts and full text go to whoever it's really about. You can put this back.</p>
        <Segmented label="Who it's really about" value={mode} onChange={setMode}
          options={[{ id: "new" as const, label: "A new person" }, { id: "existing" as const, label: "Someone on file" }]} />
        {mode === "new" ? (
          <Field label="Their name"><input className="field h-10 w-full" value={name} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        ) : target ? (
          <div className="inset-surface flex items-center justify-between gap-3 px-3.5 py-2.5 text-ui">
            <span className="truncate font-medium">{target.name}</span>
            <button className="icon-btn h-7 w-7" aria-label="Choose someone else" onClick={() => setTarget(null)}><CloseIcon size={14} /></button>
          </div>
        ) : <EntityPicker kinds={["person"]} exclude={[who.id]} onSelect={setTarget} placeholder="Find the person" autoFocus />}
        <div className="flex justify-end gap-2">
          <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-md btn-primary" disabled={busy || (mode === "new" ? !name.trim() : !target)} onClick={() => void go()}>Move it</button>
        </div>
      </div>
    </Dialog>
  );
}

/** A small button beside a meeting or document on someone's page. */
export function NotThisButton({ who, evidence, className = "" }: { who: Who; evidence: { id: string; name: string }; className?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        className={`icon-btn h-7 w-7 opacity-0 focus:opacity-100 group-hover:opacity-100 [@media(pointer:coarse)]:opacity-100 ${className}`}
        aria-label={`${evidence.name} isn't ${who.name}`}
        data-tip={`Not ${who.name}?`}
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true); }}
      >
        <CloseIcon size={14} />
      </button>
      {open && <NotThisDialog who={who} evidence={evidence} onClose={() => setOpen(false)} />}
    </>
  );
}

/** On a record's page: what's been taken off it, each of which can be put back. */
export function CorrectionsCard({ entity }: { entity: { id: string } }) {
  const { toast } = useShell();
  const { data } = useLive(() => crmApi.corrections(entity.id), [entity.id]);
  if (!data?.length) return null;
  const undo = (id: string) => crmApi.undoCorrection(id).catch((e: Error) => toast(e.message, "error"));
  return (
    <div className="inset-surface px-5 py-3">
      <ul className="space-y-1.5">
        {data.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-3">
            <p className="min-w-0 flex-1 text-ui text-ink-soft">
              {c.name} was taken off this record on {formatDate(c.created_at)}{c.to_id && c.to_name ? <> and given to <a className="underline" href={`#/crm/e/${c.to_id}`}>{c.to_name}</a></> : null}.
            </p>
            <button className="btn btn-sm btn-ghost" onClick={() => void undo(c.id)}>Put it back</button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CheckGroup({ who, checks }: { who: EntitySummary; checks: LinkCheck[] }) {
  const { toast } = useShell();
  const [fixing, setFixing] = useState<LinkCheck | null>(null);
  const right = (list: LinkCheck[]) => Promise.all(list.map((c) => crmApi.linkIsRight(c.entity.id, c.evidence.id))).catch((e: Error) => toast(e.message, "error"));
  return (
    <section className="panel">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-5 py-2.5">
        <span className="text-label font-medium"><EntityLink entity={who} /></span>
        {checks.length > 1 && <button className="btn btn-sm btn-ghost" onClick={() => void right(checks)}>All {checks.length} are right</button>}
      </header>
      <ul className="divide-y divide-line">
        {checks.map((c) => (
          <li key={c.evidence.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-5 py-2.5">
            <div className="min-w-0 flex-1">
              <div className="text-ui"><EntityLink entity={c.evidence} /></div>
              <p className="mt-0.5 text-hint text-ink-soft">{c.why}</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <button className="btn btn-sm btn-soft" onClick={() => setFixing(c)}>Not them…</button>
              <button className="btn btn-sm btn-ghost" onClick={() => void right([c])}>It's right</button>
            </div>
          </li>
        ))}
      </ul>
      {fixing && <NotThisDialog who={fixing.entity} evidence={fixing.evidence} onClose={() => setFixing(null)} />}
    </section>
  );
}

export default function LinkChecksPage() {
  const { data, error } = useLive(crmApi.linkChecks);
  const [kind, setKind] = useState<"person" | "organization">("person");
  const rows = (data?.items ?? []).filter((c) => c.entity.kind === kind);
  const groups = useMemo(() => {
    const by = new Map<string, LinkCheck[]>();
    for (const c of rows) by.set(c.entity.id, [...(by.get(c.entity.id) ?? []), c]);
    return [...by.values()];
  }, [data, kind]);
  const count = (k: string) => data?.items.filter((c) => c.entity.kind === k).length ?? 0;
  return (
    <>
      <PageHeader title="Links to check" subtitle="Imports linked these on a guess: a name that only looks alike, or a surname the source never gave. Names that plainly differ come first. Say which are right." />
      <div className="animate-enter space-y-3" style={{ animationDelay: "60ms" }}>
        <Segmented kind="tab" label="Kind" value={kind} onChange={setKind}
          options={[{ id: "person" as const, label: `People ${count("person")}` }, { id: "organization" as const, label: `Organizations ${count("organization")}` }]} />
        {error && <p className="text-ui text-trail-deep">{error}</p>}
        {!data && !error && <Skeleton className="h-64 w-full rounded-xl" />}
        {data && rows.length === 0 && <Empty icon={<AlertIcon size={20} />} title="Nothing to check">Every link here was made on something solid, or you've looked at it.</Empty>}
        {groups.map((list) => <CheckGroup key={list[0].entity.id} who={list[0].entity} checks={list} />)}
      </div>
    </>
  );
}
