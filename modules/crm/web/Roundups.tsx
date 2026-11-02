// Roundups: a packet about a set of people, for someone else to take to an event (the server half is roundups.py).
// Start from a group (an organization, a topic or a tag) or pick people one by one, say what the event is, prepare the
// packet, and save it as Word, PDF or Markdown. Every roundup stays here with the files made from it.
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { inApp, revealInFinder } from "@core/api";
import { JobStatus } from "@core/components/blocks";
import { AlertIcon, BackIcon, BackpackIcon, CloseIcon, DocIcon, DownloadIcon, ExternalIcon, FolderIcon, PlusIcon, RefreshIcon, SearchIcon, SparkleIcon, TrashIcon, UsersIcon } from "@core/components/icons";
import { PageHeader, Segmented, Select, Skeleton, Spinner, StatusChip } from "@core/components/ui";
import type { RouteProps } from "@core/registry";
import { useLive } from "@core/live";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { PacketPerson, PersonRow, Roundup, RoundupFormat, RoundupGroup, RoundupRow } from "./api";
import { Avatar, Empty } from "./bits";
import { Dialog } from "./forms";
import { formatDate, relativeTime } from "./format";

const FORMATS: { id: RoundupFormat; label: string; hint: string }[] = [
  { id: "docx", label: "Word", hint: "With pictures, to edit or send" },
  { id: "pdf", label: "PDF", hint: "With pictures, ready to read or print" },
  { id: "md", label: "Markdown", hint: "Text only, to paste somewhere else" },
];
const KIND_WORD: Record<RoundupGroup["kind"], string> = { organization: "Organization", topic: "Topic", tag: "Tag" };

const groupOptions = (groups: RoundupGroup[]) =>
  groups.map((g) => ({ value: g.id, label: g.name, hint: `${KIND_WORD[g.kind]} · ${g.size} ${g.size === 1 ? "person" : "people"}` }));

function state(r: { job: RoundupRow["job"]; prepared_at?: string | null; packet?: unknown }) {
  const busy = r.job && ["queued", "running", "waiting"].includes(r.job.status);
  if (busy) return <StatusChip tone="sky" label="Preparing" live />;
  if (r.job?.status === "error") return <StatusChip tone="trail" label="Didn't finish" />;
  if (r.prepared_at || r.packet) return <StatusChip tone="forest" label="Ready" />;
  return <StatusChip tone="neutral" label="Not prepared yet" />;
}

const Markdown = ({ children }: { children: string }) => (
  <div className="prose-family [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
  </div>
);

function Panel({ icon, title, action, children }: { icon: ReactNode; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel animate-enter p-5 sm:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2.5 text-heading font-semibold tracking-[-0.01em]">
          <span className="well well-forest h-7 w-7">{icon}</span>
          {title}
        </h2>
        {action}
      </header>
      {children}
    </section>
  );
}

// ── The list ──────────────────────────────────────────────────────────

export default function Roundups() {
  const { data, error } = useLive(crmApi.roundups);
  const [making, setMaking] = useState(false);
  return (
    <>
      <PageHeader
        title="Roundups"
        subtitle="A packet about a set of people, for someone to take to an event: a word on each of them, their picture and LinkedIn, who they work with, and what matters for the occasion. Every one you make stays here."
        actions={<button className="btn btn-md btn-primary" onClick={() => setMaking(true)}><PlusIcon size={18} /> New roundup</button>}
      />
      <div className="animate-enter" style={{ animationDelay: "60ms" }}>
        {error && <p className="text-ui text-trail-deep">{error}</p>}
        {!data && !error && <Skeleton className="h-40 w-full rounded-xl" />}
        {data && data.length === 0 && (
          <Empty icon={<BackpackIcon size={20} />} title="No roundups yet">
            Start one from an organization, a topic or a tag, or pick people one by one.
          </Empty>
        )}
        {data && data.length > 0 && (
          <ul className="panel divide-y divide-line">
            {data.map((r) => (
              <li key={r.id}>
                <a href={`#/crm/roundups/${r.id}`} className="flex items-center gap-3 px-5 py-3.5 hover:bg-surface-subtle">
                  <span className="well well-forest"><BackpackIcon size={16} /></span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-label font-medium">{r.title}</div>
                    <div className="truncate text-meta text-ink-soft">
                      {[r.audience && `For ${r.audience}`, `${r.people} ${r.people === 1 ? "person" : "people"}`, r.origin && `from ${r.origin}`,
                        r.prepared_at ? `prepared ${relativeTime(r.prepared_at)}` : `changed ${relativeTime(r.updated_at)}`,
                        r.files > 0 && `${r.files} saved file${r.files === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}
                    </div>
                  </div>
                  {state(r)}
                </a>
              </li>
            ))}
          </ul>
        )}
      </div>
      {making && <NewRoundup onClose={() => setMaking(false)} />}
    </>
  );
}

function NewRoundup({ onClose, group: startGroup }: { onClose: () => void; group?: string }) {
  const { toast } = useShell();
  const { data: groups } = useLive(crmApi.roundupGroups);
  const [mode, setMode] = useState<"group" | "pick">("group");
  const [group, setGroup] = useState(startGroup ?? "");
  const [title, setTitle] = useState("");
  const [audience, setAudience] = useState("");
  const [event, setEvent] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const r = await crmApi.createRoundup({ title: title.trim() || undefined, audience, event, group: mode === "group" ? group || undefined : undefined });
      onClose();
      navigate(`crm/roundups/${r.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setBusy(false);
    }
  };

  return (
    <Dialog title="New roundup" onClose={onClose} width={560}>
      <div className="space-y-4">
        <Segmented label="Start from" value={mode} onChange={setMode}
          options={[{ id: "group", label: "A group" }, { id: "pick", label: "People I pick" }]} />
        {mode === "group" ? (
          groups ? (
            groups.length ? (
              <label className="block">
                <span className="mb-1.5 block text-label font-medium">Organization, topic or tag</span>
                <Select label="Group" value={group} onChange={setGroup} options={[{ value: "", label: "Choose a group" }, ...groupOptions(groups)]} className="w-full" />
                <span className="mt-1.5 block text-hint text-ink-soft">Everyone in it comes in, closest to you first. You can add or take people off after.</span>
              </label>
            ) : <p className="text-ui text-ink-soft">There are no groups yet. Pick people instead.</p>
          ) : <Skeleton className="h-10 w-full rounded-lg" />
        ) : (
          <p className="text-ui text-ink-soft">You'll add people one by one on the next page.</p>
        )}
        <label className="block">
          <span className="mb-1.5 block text-label font-medium">Title</span>
          <input className="field h-10 w-full" value={title} onChange={(e) => setTitle(e.target.value)}
            placeholder={mode === "group" && group ? `${groups?.find((g) => g.id === group)?.name ?? ""} roundup` : "Roundup"} />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-label font-medium">Who it's for</span>
          <input className="field h-10 w-full" value={audience} onChange={(e) => setAudience(e.target.value)} placeholder="Your teammate's name" />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-label font-medium">The event, and what they should know</span>
          <textarea className="field h-24 w-full resize-none p-3 text-ui" value={event} onChange={(e) => setEvent(e.target.value)}
            placeholder="The Cold Chain Summit next Thursday. Look for anyone expanding pilots or hiring." />
        </label>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button className="btn btn-md btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn btn-md btn-primary" disabled={busy || (mode === "group" && !group)} onClick={() => void create()}>
          {busy ? <Spinner /> : <PlusIcon size={18} />} Create
        </button>
      </div>
    </Dialog>
  );
}

/** "Roundup" on a group's row: makes one from it and opens it. */
export function RoundupFromGroup({ group }: { group: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-sm btn-ghost" onClick={() => setOpen(true)}><BackpackIcon size={16} /> Roundup</button>
      {open && <NewRoundup group={group} onClose={() => setOpen(false)} />}
    </>
  );
}

// ── One roundup ───────────────────────────────────────────────────────

export function RoundupPage({ params }: RouteProps) {
  const { data, error } = useLive(() => crmApi.roundup(params.id), [params.id]);
  if (error) return <p className="text-ui text-trail-deep">{error}</p>;
  if (!data) return <Skeleton className="h-64 w-full rounded-xl" />;
  return <RoundupView r={data} />;
}

/** A text field that saves when you leave it, and follows the server while you aren't typing in it. */
function Saved({ value, save, multiline, label, placeholder }: { value: string; save: (v: string) => Promise<unknown>; multiline?: boolean; label: string; placeholder?: string }) {
  const [draft, setDraft] = useState(value);
  const [editing, setEditing] = useState(false);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);
  const props = {
    value: draft, placeholder, "aria-label": label,
    onFocus: () => setEditing(true),
    onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
    onBlur: () => { setEditing(false); if (draft.trim() !== value.trim()) void save(draft); },
  };
  return (
    <label className="block">
      <span className="mb-1.5 block text-label font-medium">{label}</span>
      {multiline ? <textarea className="field h-24 w-full resize-y p-3 text-ui" {...props} /> : <input className="field h-10 w-full" {...props} />}
    </label>
  );
}

function RoundupView({ r }: { r: Roundup }) {
  const { toast, confirm } = useShell();
  const busy = !!r.job && ["queued", "running", "waiting"].includes(r.job.status);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };
  const save = (b: Parameters<typeof crmApi.updateRoundup>[1]) => act(() => crmApi.updateRoundup(r.id, b));
  const remove = async () => {
    if (!(await confirm({ title: `Delete ${r.title}?`, body: "The roundup goes from this list. Files you already saved stay in its folder.", confirmLabel: "Delete", tone: "danger" }))) return;
    await act(async () => { await crmApi.deleteRoundup(r.id); navigate("crm/roundups"); });
  };

  return (
    <div className="space-y-5">
      <header className="animate-enter">
        <a href="#/crm/roundups" className="btn btn-sm btn-ghost -ml-2 mb-3"><BackIcon size={16} /> Roundups</a>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="page-title">{r.title}</h1>
            <p className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-body text-ink-soft">
              {state(r)}
              <span>{[r.audience && `For ${r.audience}`, `${r.people.length} ${r.people.length === 1 ? "person" : "people"}`, r.origin_name && `from ${r.origin_name}`].filter(Boolean).join(" · ")}</span>
            </p>
          </div>
          <button className="btn btn-sm btn-ghost" onClick={() => void remove()}><TrashIcon size={16} /> Delete</button>
        </div>
      </header>

      <Panel icon={<DocIcon size={16} />} title="The brief">
        <div className="grid gap-4 sm:grid-cols-2">
          <Saved label="Title" value={r.title} save={(title) => save({ title })} />
          <Saved label="Who it's for" value={r.audience} placeholder="Your teammate's name" save={(audience) => save({ audience })} />
        </div>
        <div className="mt-4">
          <Saved multiline label="The event, and what they should know" value={r.event}
            placeholder="The Cold Chain Summit next Thursday. Look for anyone expanding pilots or hiring." save={(event) => save({ event })} />
          <p className="mt-1.5 text-hint text-ink-soft">The AI writes the opening and each person's few lines for this. The rest comes from what's already on file.</p>
        </div>
      </Panel>

      <People r={r} act={act} />

      <Panel icon={<SparkleIcon size={16} />} title="The packet"
        action={r.people.length > 0 && !busy && (
          <button className={`btn btn-sm ${r.packet && !r.stale ? "btn-soft" : "btn-primary"}`} disabled={!r.ready} onClick={() => void act(() => crmApi.prepareRoundup(r.id))}>
            {r.packet ? <RefreshIcon size={16} /> : <SparkleIcon size={16} />} {r.packet ? "Prepare again" : "Prepare the packet"}
          </button>
        )}>
        {!r.ready && <p className="mb-3 flex items-start gap-2 text-ui text-sun-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" />{r.reason || "No AI is set up for this yet (Settings → AI)."}</p>}
        <JobStatus job={r.job} />
        {r.job?.status === "error" && !busy && <p className="mt-2 text-ui text-trail-deep">It stopped: {r.job.error}. Prepare it again to carry on from where it got to.</p>}
        {r.packet && r.stale && !busy && (
          <p className="mb-3 inset-surface px-4 py-3 text-ui text-ink-soft">The brief or the people changed after this was prepared. Prepare it again to bring it up to date.</p>
        )}
        {!r.packet && !busy && r.ready && (
          <p className="text-ui text-ink-soft">
            {r.people.length ? `Writes a few lines on each person for this event, then the opening, with ${r.provider}${r.local ? " on this Mac" : ""}. It takes about as long as ${r.people.length + 1} short answers.` : "Add some people first."}
          </p>
        )}
        {r.packet && <Exports r={r} act={act} />}
        {r.packet && <Preview r={r} />}
      </Panel>
    </div>
  );
}

function People({ r, act }: { r: Roundup; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { data: groups } = useLive(crmApi.roundupGroups);
  const [group, setGroup] = useState("");
  const without = (id: string) => r.people.filter((p) => p.id !== id).map((p) => p.id);
  const missing = r.people.filter((p) => !p.overview).length;
  return (
    <Panel icon={<UsersIcon size={16} />} title={`People ${r.people.length}`}>
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <AddPerson onAdd={(id) => act(() => crmApi.addToRoundup(r.id, { people: [id] }))} taken={new Set(r.people.map((p) => p.id))} />
        <div className="flex gap-2">
          <Select label="Add a group" value={group} onChange={setGroup} className="min-w-0 flex-1"
            options={[{ value: "", label: "Add everyone in a group" }, ...groupOptions(groups ?? [])]} />
          <button className="btn btn-md btn-soft" disabled={!group} onClick={() => void act(async () => { await crmApi.addToRoundup(r.id, { group }); setGroup(""); })}>
            <PlusIcon size={18} /> Add
          </button>
        </div>
      </div>
      {r.people.length === 0 ? (
        <p className="inset-surface px-4 py-6 text-center text-ui text-ink-soft">No one yet. Find people above, or add a whole group.</p>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {r.people.map((p) => (
            <li key={p.id} className="flex items-center gap-3 px-4 py-2.5">
              <Avatar name={p.name} id={p.id} size={32} />
              <a href={`#/crm/e/${p.id}`} className="min-w-0 flex-1">
                <div className="truncate text-label font-medium hover:underline">{p.name}</div>
                {p.subtitle && <div className="truncate text-meta text-ink-soft">{p.subtitle}</div>}
              </a>
              {!p.overview && <span className="chip bg-sun-soft text-sun-deep" data-tip="The packet uses their profile summary, or says little is on file">No overview yet</span>}
              <button className="icon-btn" aria-label={`Take ${p.name} off`} data-tip="Take off this roundup"
                onClick={() => void act(() => crmApi.updateRoundup(r.id, { people: without(p.id) }))}>
                <CloseIcon size={16} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {missing > 0 && (
        <p className="mt-3 text-hint text-ink-soft">
          {missing} {missing === 1 ? "person has" : "people have"} no overview yet. Opening their profile writes one; the packet uses whatever is there when it's prepared.
        </p>
      )}
    </Panel>
  );
}

/** Find someone by name, role, organization or tag and add them. */
function AddPerson({ onAdd, taken }: { onAdd: (id: string) => Promise<unknown>; taken: Set<string> }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PersonRow[] | null>(null);
  useEffect(() => {
    const term = q.trim();
    if (!term) return setRows(null);
    let alive = true;
    const t = setTimeout(() => void crmApi.people({ q: term, limit: 6, sort: "match" }).then((p) => alive && setRows(p.items), () => alive && setRows([])), 120);
    return () => { alive = false; clearTimeout(t); };
  }, [q]);
  const [open, setOpen] = useState(false);
  const shown = (rows ?? []).filter((r) => !r.person.is_self);
  return (
    <div className="relative" onFocus={() => setOpen(true)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false); }}
      onKeyDown={(e) => { if (e.key === "Escape") setQ(""); }}>
      <SearchIcon size={16} className="pointer-events-none absolute left-3 top-[1.25rem] -translate-y-1/2 text-ink-faint" />
      <input className="field h-10 w-full pl-9" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Add a person" aria-label="Add a person" />
      {rows && open && (
        <ul className="absolute inset-x-0 top-11 z-20 max-h-72 overflow-y-auto rounded-lg border border-line bg-surface shadow-lg">
          {shown.length === 0 && <li className="px-4 py-3 text-ui text-ink-soft">No one matches.</li>}
          {shown.map((row) => {
            const on = taken.has(row.person.id);
            return (
              <li key={row.person.id}>
                <button className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-surface-subtle disabled:opacity-60" disabled={on}
                  onClick={() => void onAdd(row.person.id).then(() => setQ(""))}>
                  <Avatar name={row.person.name} id={row.person.id} size={28} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-label">{row.person.name}</span>
                    {row.person.subtitle && <span className="block truncate text-meta text-ink-soft">{row.person.subtitle}</span>}
                  </span>
                  <span className="text-meta text-ink-soft">{on ? "On it" : <PlusIcon size={16} />}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function Exports({ r, act }: { r: Roundup; act: (fn: () => Promise<unknown>) => Promise<void> }) {
  const { toast } = useShell();
  const [making, setMaking] = useState<RoundupFormat | null>(null);
  const download = (name: string) => {
    const a = document.createElement("a");
    a.href = crmApi.roundupFileUrl(r.id, name);
    a.download = name;
    a.click();
  };
  const make = (format: RoundupFormat) => act(async () => {
    setMaking(format);
    try {
      const saved = await crmApi.exportRoundup(r.id, format);
      toast(`Saved ${saved.name}`);
      if (inApp) revealInFinder(saved.path);
      else download(saved.name);
    } finally {
      setMaking(null);
    }
  });
  return (
    <div className="mb-5 space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-label font-medium">Save as</span>
        {FORMATS.map((f) => (
          <button key={f.id} className="btn btn-sm btn-soft" data-tip={f.hint} disabled={making !== null} onClick={() => void make(f.id)}>
            {making === f.id ? <Spinner /> : <DownloadIcon size={16} />} {f.label}
          </button>
        ))}
      </div>
      {r.files.length > 0 && (
        <div className="inset-surface px-4 py-3">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="text-label font-medium">Saved files</span>
            {inApp && <button className="btn btn-sm btn-ghost" onClick={() => revealInFinder(r.folder)}><FolderIcon size={16} /> Show in Finder</button>}
          </div>
          <ul className="space-y-1">
            {r.files.map((f) => (
              <li key={f.name} className="flex items-center gap-2 text-ui">
                <DocIcon size={16} className="shrink-0 text-ink-faint" />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="shrink-0 text-meta text-ink-soft">{relativeTime(f.saved_at)}</span>
                {inApp
                  ? <button className="icon-btn" aria-label={`Show ${f.name} in Finder`} onClick={() => revealInFinder(`${r.folder}/${f.name}`)}><FolderIcon size={16} /></button>
                  : <button className="icon-btn" aria-label={`Download ${f.name}`} onClick={() => download(f.name)}><DownloadIcon size={16} /></button>}
              </li>
            ))}
          </ul>
          {!inApp && <p className="mt-2 break-words text-hint text-ink-soft">Kept in {r.folder}</p>}
        </div>
      )}
    </div>
  );
}

function Preview({ r }: { r: Roundup }) {
  const p = r.packet!;
  return (
    <div className="space-y-5 border-t border-line pt-5">
      <div>
        <p className="text-meta text-ink-soft">
          Prepared {formatDate(p.prepared_at)}{p.audience && ` for ${p.audience}`} · written by {p.written_by}
        </p>
        {p.event && <p className="mt-2 text-ui"><span className="font-semibold">The event:</span> {p.event}</p>}
        <div className="mt-3"><Markdown>{p.intro}</Markdown></div>
      </div>
      <div className="space-y-4">
        {p.people.map((s) => <PersonCard key={s.id} s={s} />)}
      </div>
    </div>
  );
}

function PersonCard({ s }: { s: PacketPerson }) {
  return (
    <article className="rounded-xl border border-line p-4 sm:p-5">
      <div className="flex items-start gap-3.5">
        <Avatar name={s.name} id={s.id} size={56} />
        <div className="min-w-0 flex-1">
          <h3 className="text-lead font-semibold tracking-[-0.01em]">{s.name}</h3>
          {(s.headline || s.location) && <p className="text-meta text-ink-soft">{[s.headline, s.location].filter(Boolean).join(" · ")}</p>}
          <p className="mt-1 flex flex-wrap gap-x-3 text-meta">
            {s.linkedin && <a className="inline-flex items-center gap-1 text-forest-deep hover:underline" href={s.linkedin.startsWith("http") ? s.linkedin : `https://${s.linkedin}`} target="_blank" rel="noreferrer">LinkedIn <ExternalIcon size={12} /></a>}
            {s.email && <a className="text-forest-deep hover:underline" href={`mailto:${s.email}`}>{s.email}</a>}
          </p>
        </div>
      </div>
      {s.blurb && <p className="mt-3 text-ui"><span className="font-semibold">For this event:</span> {s.blurb}</p>}
      {s.with_owner && <p className="mt-1.5 text-meta italic text-ink-soft">{s.with_owner}</p>}
      <details className="group mt-3">
        <summary className="cursor-pointer text-label font-medium text-forest-deep">Summary, organizations and connections</summary>
        <div className="mt-3 space-y-3 text-ui">
          {s.summary ? <Markdown>{s.summary}</Markdown> : <p className="text-ink-soft">Little is on file about them yet.</p>}
          {s.organizations.length > 0 && (
            <div>
              <div className="mb-1 text-label font-medium">Organizations</div>
              <ul className="list-disc space-y-0.5 pl-5">
                {s.organizations.map((o) => <li key={o.name}>{o.name}{o.role && `, ${o.role}`}{!o.current && <span className="text-ink-soft"> (earlier)</span>}</li>)}
              </ul>
            </div>
          )}
          {s.connections.length > 0 && (
            <div>
              <div className="mb-1 text-label font-medium">Closest connections</div>
              <ul className="list-disc space-y-0.5 pl-5">
                {s.connections.map((c) => (
                  <li key={c.name}>
                    <span className="font-medium">{c.name}</span>{c.headline && <span className="text-ink-soft"> ({c.headline})</span>}: {c.relation}
                    {c.in_packet && <span className="chip ml-1.5 bg-forest-soft text-forest-deep">in this packet</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </details>
    </article>
  );
}
