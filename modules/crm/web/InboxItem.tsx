// One inbox item: what was found, for you to look over and correct before it's added to your people.
import { useState } from "react";
import { AlertIcon, BackIcon, CheckIcon, RefreshIcon } from "@core/components/icons";
import { JobStatus } from "@core/components/blocks";
import { PageHeader, Segmented, Select, Skeleton, Spinner, useConfirm } from "@core/components/ui";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { InboxItem as Item, Proposal, ProposalEntity, SheetMappingInfo, SheetProposal } from "./api";
import { Avatar, Card, Empty, KIND_LABEL } from "./bits";
import { EntityPicker } from "./forms";
import { formatDate } from "./format";
import { DOC_TYPE_LABEL, StatusPill, extractorLabel } from "./inboxBits";

const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
const toLocal = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export default function InboxItem({ params }: RouteProps) {
  const { data: item, error } = useLive(() => crmApi.inboxItem(params.id), [params.id]);
  if (error) return <Empty icon={<AlertIcon size={20} />} title="That item isn't here">It may have been removed. <a className="underline" href="#/crm/inbox">Back to the inbox</a></Empty>;
  if (!item) return <Skeleton className="h-64 w-full rounded-xl" />;
  const sheets = item.proposal && "kind" in item.proposal && item.proposal.kind === "spreadsheet" ? (item.proposal as SheetProposal) : null;
  const proposal = item.proposal && "entities" in item.proposal ? (item.proposal as Proposal) : null;
  const triage = item.payload?.triage;
  return (
    <>
      <PageHeader
        title={
          <span className="flex items-center gap-2">
            <a href="#/crm/inbox" className="icon-btn" aria-label="Back to the inbox"><BackIcon size={20} /></a>
            {proposal?.record.title || item.title || item.payload?.filename || "Notes"}
          </span>
        }
        subtitle={
          <>
            {item.payload?.filename && <>{item.payload.folder ? `${item.payload.folder}/` : ""}{item.payload.filename} · </>}
            added {formatDate(item.created_at, { hour: "numeric", minute: "2-digit" })}
            {item.extractor && <> · read by {extractorLabel(item.extractor)}</>}
          </>
        }
        actions={
          <div className="flex items-center gap-2">
            {proposal && <span className="chip bg-surface-subtle text-ink-soft">{DOC_TYPE_LABEL[proposal.doc_type] ?? proposal.doc_type}</span>}
            <StatusPill row={item} />
          </div>
        }
      />
      <div className="space-y-4">
        {triage && triage.process !== "full" && <p className="text-ui text-ink-soft">Sorted as {triage.category.replace(/_/g, " ")}: {triage.reason}</p>}
        {(item.status === "pending" || item.status === "processing") && <Reading item={item} />}
        {(item.status === "failed" || item.status === "skipped") && <NotProcessed item={item} />}
        {item.status === "review" && proposal && <ReviewForm key={item.updated_at} item={item} initial={proposal} />}
        {item.status === "applied" && <Applied item={item} />}
        {sheets && <SheetMappings sheets={sheets.sheets} />}
        {item.status === "discarded" && <div className="panel p-5 text-ui text-ink-soft">Discarded. Nothing was added to your people, and the same file won't be imported again.</div>}
        {item.raw_text && (
          <details className="panel px-5 py-3">
            <summary className="cursor-pointer text-label font-semibold text-ink-soft">
              Original text{item.payload?.words ? ` (${item.payload.words.toLocaleString()} words)` : ""}
            </summary>
            <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap font-mono text-hint text-ink-soft">{item.raw_text}</pre>
          </details>
        )}
      </div>
    </>
  );
}

function Reading({ item }: { item: Item }) {
  return (
    <div className="panel p-5">
      <p className="mb-3 text-ui text-ink-soft">Reading it, writing the notes, and matching the people to the ones you already know.</p>
      {item.work ? <JobStatus job={item.work} /> : <Spinner className="text-sky" />}
    </div>
  );
}

function NotProcessed({ item }: { item: Item }) {
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  const retry = async () => {
    setBusy(true);
    try {
      await crmApi.retryItem(item.id);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="panel space-y-3 p-5">
      {item.status === "failed" ? (
        <div className="flex items-start gap-2 text-ui text-trail-deep"><AlertIcon size={18} className="mt-0.5 shrink-0" /> <span className="break-words">{item.error ?? "It couldn't be read."}</span></div>
      ) : (
        <p className="text-ui text-ink-soft">Skipped: {item.error}</p>
      )}
      {(item.raw_text || item.source === "spreadsheet") && (
        <button className="btn btn-sm btn-soft" disabled={busy} onClick={() => void retry()}>
          <RefreshIcon size={16} /> {item.status === "failed" ? "Try again" : "Read it anyway"}
        </button>
      )}
    </div>
  );
}

function Applied({ item }: { item: Item }) {
  const r = (item.result ?? {}) as Record<string, number | string | null>;
  if (item.source === "linkedin_csv" || item.source === "spreadsheet") {
    return (
      <div className="panel flex items-start gap-3 p-5">
        <CheckIcon size={20} className="mt-0.5 text-forest" />
        <p className="min-w-0 flex-1 text-ui text-ink-soft">
          Imported {r.rows} rows: {r.people_created} new people, {r.people_updated} updated, {r.orgs_created} new organizations,
          {" "}{r.relationships} new relationships{r.notes !== undefined && <>, {r.notes} notes</>}
          {Boolean(r.skipped_rows) && <>. {r.skipped_rows} rows had no name and were skipped</>}.
        </p>
      </div>
    );
  }
  const target = (r.record_id ?? r.subject_id) as string | undefined;
  return (
    <div className="panel flex flex-wrap items-center gap-3 p-5">
      <CheckIcon size={20} className="text-forest" />
      <p className="min-w-0 flex-1 text-ui text-ink-soft">
        Added: {r.created} new records, {r.linked} linked to ones you had, {r.relationships} relationships, {r.notes} notes.
      </p>
      {target && <a className="btn btn-md btn-primary" href={`#/crm/e/${target}`}>Open the {r.record_kind ?? "profile"}</a>}
    </div>
  );
}

/** How a spreadsheet's columns were read: kept after the import so you can see what went where. */
function SheetMappings({ sheets }: { sheets: Record<string, SheetMappingInfo> }) {
  return (
    <div className="space-y-4">
      {Object.entries(sheets).map(([name, m]) => (
        <Card key={name} title={`Sheet “${name}”: ${m.row_kind === "skip" ? "skipped" : `each row is ${m.row_kind === "person" ? "a person" : "an organization"}`}`}
          action={<span className="text-hint text-ink-soft">columns read by {extractorLabel(m.mapped_by)}</span>}>
          {m.reason && <p className="mb-2 text-ui text-ink-soft">{m.reason}</p>}
          {(m.event_name || m.sheet_tags.length > 0) && (
            <p className="mb-2 flex flex-wrap items-center gap-1.5 text-ui text-ink-soft">
              {m.event_name && <span>Event: <b className="text-ink">{m.event_name}</b>{m.event_date && ` (${m.event_date})`}</span>}
              {m.sheet_tags.map((t) => <span key={t} className="chip bg-surface-subtle">#{t}</span>)}
            </p>
          )}
          {m.columns.length > 0 && (
            <table className="w-full text-ui">
              <caption className="sr-only">Where each column went</caption>
              <tbody>
                {m.columns.map((c) => (
                  <tr key={c.column} className="border-t border-line">
                    <td className="py-1.5 pr-3 font-medium">{c.column}</td>
                    <td className={`py-1.5 ${c.target === "ignore" ? "text-ink-faint" : "text-ink-soft"}`}>
                      {c.target === "ignore" ? "left out" : `→ ${c.target.replace(/_/g, " ")}${c.attribute_key ? ` (${c.attribute_key})` : ""}`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      ))}
    </div>
  );
}

const ACTIONS: { id: ProposalEntity["action"]; label: string }[] = [
  { id: "link", label: "Same as" },
  { id: "create", label: "New" },
  { id: "skip", label: "Skip" },
];

function ReviewForm({ item, initial }: { item: Item; initial: Proposal }) {
  const { toast } = useShell();
  const [confirm, confirmDialog] = useConfirm();
  const { data: meta } = useLive(crmApi.meta);
  const [p, setP] = useState<Proposal>(initial);
  const [points, setPoints] = useState((initial.record.key_points ?? []).join("\n"));
  const [actions, setActions] = useState((initial.record.action_items ?? []).join("\n"));
  const [tags, setTags] = useState((initial.record.tags ?? []).join(", "));
  const [busy, setBusy] = useState(false);
  const rec = p.record;
  const setRecord = (patch: Partial<Proposal["record"]>) => setP((prev) => ({ ...prev, record: { ...prev.record, ...patch } }));
  const setEntity = (ref: string, patch: Partial<ProposalEntity>) => setP((prev) => ({ ...prev, entities: prev.entities.map((e) => (e.ref === ref ? { ...e, ...patch } : e)) }));

  const byRef = new Map(p.entities.map((e) => [e.ref, e]));
  const subject = p.subject_ref ? byRef.get(p.subject_ref) : undefined;
  const nameOf = (ref: string) => (ref === "record" ? rec.title || `this ${rec.kind}` : byRef.get(ref)?.name ?? ref);
  const live = (ref: string) => (ref === "record" ? rec.include : byRef.get(ref)?.action !== "skip");
  const unresolved = p.entities.filter((e) => e.action === "link" && !e.match_id).length;

  const apply = async () => {
    setBusy(true);
    try {
      const done = await crmApi.applyItem(item.id, {
        ...p,
        record: { ...rec, key_points: lines(points), action_items: lines(actions), tags: tags.split(",").map((t) => t.trim()).filter(Boolean) },
      });
      const target = (done.result?.record_id ?? done.result?.subject_id) as string | undefined;
      navigate(target ? `crm/e/${target}` : "crm/inbox");
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };
  const discard = async () => {
    if (!(await confirm({ title: "Discard this?", body: "Nothing is added to your people. The same file won't be imported again.", confirmLabel: "Discard", tone: "danger" }))) return;
    setBusy(true);
    try {
      await crmApi.discardItem(item.id);
      navigate("crm/inbox");
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {p.warnings.length > 0 && (
        <div className="flex gap-2.5 rounded-lg bg-sun-soft px-4 py-3 text-ui text-sun-deep">
          <AlertIcon size={18} className="mt-0.5 shrink-0" />
          <div className="min-w-0 space-y-1">{p.warnings.map((w, i) => <p key={i} className="break-words">{w}</p>)}</div>
        </div>
      )}

      <Card
        title={rec.kind === "meeting" ? "The meeting" : "The document"}
        action={
          <label className="flex items-center gap-1.5 text-hint text-ink-soft">
            <input type="checkbox" className="accent-forest" checked={rec.include} onChange={(e) => setRecord({ include: e.target.checked })} />
            Keep a {rec.kind} record
          </label>
        }
      >
        {!rec.include && subject && (
          <p className="mb-3 inset-surface px-3 py-2 text-ui text-ink-soft">
            This is about <b className="text-ink">{subject.name}</b>: the summary and facts go on their record, and the full text is kept as a note there.
          </p>
        )}
        <fieldset disabled={!rec.include} className="grid gap-3 disabled:opacity-50 sm:grid-cols-[1fr_auto]">
          <label className="block">
            <span className="mb-1 block text-hint text-ink-soft">Title</span>
            <input className="field w-full" value={rec.title} onChange={(e) => setRecord({ title: e.target.value })} />
          </label>
          <label className="block">
            <span className="mb-1 block text-hint text-ink-soft">When</span>
            <input type="datetime-local" className="field" value={toLocal(rec.occurred_at)} onChange={(e) => e.target.value && setRecord({ occurred_at: new Date(e.target.value).toISOString() })} />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-hint text-ink-soft">Summary</span>
            <textarea className="field min-h-24 w-full resize-y" value={rec.summary} onChange={(e) => setRecord({ summary: e.target.value })} />
          </label>
          <label className="block sm:col-span-2">
            <span className="mb-1 block text-hint text-ink-soft">Key points (one per line)</span>
            <textarea className="field min-h-24 w-full resize-y" value={points} onChange={(e) => setPoints(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-hint text-ink-soft">Action items (one per line; they become tasks)</span>
            <textarea className="field min-h-16 w-full resize-y" value={actions} onChange={(e) => setActions(e.target.value)} />
          </label>
          <label className="block">
            <span className="mb-1 block text-hint text-ink-soft">Tags (separated by commas)</span>
            <input className="field w-full" value={tags} onChange={(e) => setTags(e.target.value)} />
          </label>
        </fieldset>
      </Card>

      <Card title={`People, organizations and topics (${p.entities.length})`} flush>
        {p.entities.length === 0 && <p className="px-5 pb-4 text-ui text-ink-soft">Nobody was found.</p>}
        <ul className="divide-y divide-line">
          {p.entities.map((e) => <EntityRow key={e.ref} entity={e} onChange={(patch) => setEntity(e.ref, patch)} />)}
        </ul>
      </Card>

      <Card title={`Relationships (${p.relationships.filter((r) => r.include && live(r.source) && live(r.target)).length} of ${p.relationships.length})`}>
        <ul className="space-y-0.5">
          {p.relationships.map((r) => {
            const enabled = live(r.source) && live(r.target);
            const label = meta?.relationship_kinds[r.kind]?.label ?? r.kind.replace(/_/g, " ");
            const when = [r.started && `from ${r.started}`, r.ended && `until ${r.ended}`].filter(Boolean).join(" ");
            return (
              <li key={r.id}>
                <label className={`flex items-start gap-2.5 rounded-md px-1.5 py-1.5 text-ui ${enabled ? "hover:bg-forest/[.04]" : "opacity-40"}`}>
                  <input
                    type="checkbox"
                    className="mt-1 accent-forest"
                    disabled={!enabled}
                    checked={r.include && enabled}
                    onChange={(ev) => setP((prev) => ({ ...prev, relationships: prev.relationships.map((x) => (x.id === r.id ? { ...x, include: ev.target.checked } : x)) }))}
                  />
                  <span>
                    <span className="font-medium">{nameOf(r.source)}</span> <span className="text-ink-soft">{label}</span> <span className="font-medium">{nameOf(r.target)}</span>
                    {when && <span className="text-ink-soft"> · {when}</span>}
                    {r.context && <span className="block text-hint text-ink-soft">“{r.context}”</span>}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      </Card>

      <div className="panel sticky bottom-3 z-10 flex flex-wrap items-center justify-end gap-2 px-4 py-3 shadow-lg">
        {unresolved > 0 && <span className="mr-auto text-ui text-sun-deep">{unresolved} {unresolved > 1 ? "need" : "needs"} a match, or “New”.</span>}
        <button className="btn btn-md btn-ghost" disabled={busy} onClick={() => void discard()}>Discard</button>
        <button className="btn btn-md btn-primary" disabled={busy || unresolved > 0} onClick={() => void apply()}>
          {busy ? <Spinner /> : <CheckIcon size={18} />} Add to your people
        </button>
      </div>
      {confirmDialog}
    </div>
  );
}

function EntityRow({ entity: e, onChange }: { entity: ProposalEntity; onChange: (patch: Partial<ProposalEntity>) => void }) {
  const [searching, setSearching] = useState(false);
  const details = [e.title, e.email, e.location].filter(Boolean).join(" · ");
  const options = e.candidates.map((c) => ({ value: c.id, label: c.name, hint: `${c.subtitle ? `${c.subtitle} · ` : ""}${c.reason === "chosen" ? "chosen" : `${Math.round(c.score * 100)}% match`}` }));
  return (
    <li className={`px-5 py-3.5 ${e.action === "skip" ? "opacity-50" : ""}`}>
      <div className="flex flex-wrap items-start gap-3">
        <Avatar name={e.name} kind={e.kind} size={32} />
        <div className="min-w-[11rem] flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {e.action === "create" ? (
              <input className="field h-8 max-w-64 font-medium" value={e.name} onChange={(ev) => onChange({ name: ev.target.value })} aria-label="Name" />
            ) : (
              <span className="text-label font-medium">{e.name}</span>
            )}
            <span className="chip bg-surface-subtle text-ink-soft">{KIND_LABEL[e.kind].one.toLowerCase()}</span>
            <span className="chip bg-surface-subtle text-ink-soft">{e.role}</span>
            {e.is_self && <span className="chip bg-forest-soft text-forest-deep">you</span>}
            {e.ambiguous && e.action !== "link" && <span className="chip bg-sun-soft text-sun-deep">could be several people</span>}
            {(e.tags ?? []).map((t) => <span key={t} className="text-hint text-ink-soft">#{t}</span>)}
          </div>
          {details && <div className="mt-0.5 text-hint text-ink-soft">{details}</div>}
          {e.summary && <p className="mt-1 text-ui text-ink-soft">{e.summary}</p>}
          {e.facts.length > 0 && <ul className="mt-1 space-y-0.5 text-ui text-ink-soft">{e.facts.map((f, i) => <li key={i}>• {f}</li>)}</ul>}
        </div>
        <Segmented<ProposalEntity["action"]>
          size="sm"
          label={`What to do with ${e.name}`}
          value={e.action}
          options={ACTIONS}
          onChange={(action) => onChange({ action, ...(action === "link" && !e.match_id && e.candidates[0] ? { match_id: e.candidates[0].id } : {}) })}
        />
      </div>
      {e.action === "link" && (
        <div className="mt-2.5 pl-11">
          {searching ? (
            <div className="max-w-sm">
              <EntityPicker
                kinds={[e.kind]}
                autoFocus
                placeholder="Search your records…"
                onSelect={(s) => {
                  onChange({
                    match_id: s.id,
                    candidates: e.candidates.some((c) => c.id === s.id) ? e.candidates : [...e.candidates, { id: s.id, name: s.name, kind: s.kind, subtitle: s.subtitle, score: 1, reason: "chosen" }],
                  });
                  setSearching(false);
                }}
              />
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2 text-ui">
              {e.candidates.length > 0 ? (
                <Select label={`Which record is ${e.name}`} size="sm" className="w-full sm:w-80" value={e.match_id ?? ""} options={[...(e.match_id ? [] : [{ value: "", label: "Choose…" }]), ...options]} onChange={(v) => onChange({ match_id: v || null })} />
              ) : (
                <span className="text-ink-soft">No close matches.</span>
              )}
              <button className="text-hint text-ink-soft underline hover:text-ink" onClick={() => setSearching(true)}>Search…</button>
              {e.match_id && <a className="text-hint text-ink-soft hover:text-ink hover:underline" href={`#/crm/e/${e.match_id}`} target="_blank" rel="noreferrer">Open that record</a>}
            </div>
          )}
        </div>
      )}
    </li>
  );
}
