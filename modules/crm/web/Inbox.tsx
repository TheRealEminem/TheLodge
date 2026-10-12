// The inbox: add notes and documents, watch them being read, and find what needs you.
import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { CheckIcon, DocIcon, FolderIcon, InboxIcon, SparkleIcon } from "@core/components/icons";
import { PageHeader, Skeleton, Spinner, StatusChip, useConfirm } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { InboxRow, InboxStatus } from "./api";
import { Card, Empty } from "./bits";
import { fromDrop, fromInput } from "./drop";
import type { Picked } from "./drop";
import { relativeTime } from "./format";
import { CATEGORY_LABEL, SOURCE_LABEL, StatusPill, extractorLabel } from "./inboxBits";

/** Who will read what you add: the extraction job's provider, with a way to change it. */
function ReadBy() {
  const { data } = useLive(crmApi.aiRoles);
  const job = data?.find((r) => r.role === "extraction");
  if (!job) return null;
  return (
    <a href="#/settings" className="inline-flex items-center gap-1.5 text-meta text-ink-soft hover:text-ink" data-tip="Change who reads what you add">
      <SparkleIcon size={14} />
      {job.provider === "rules" ? "Rules only, no AI" : job.ready ? `Read by ${extractorLabel(`${job.provider}:${job.model}`)}` : job.reason}
    </a>
  );
}

function AddFiles() {
  const { toast } = useShell();
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [picked, setPicked] = useState<Picked[]>([]);
  const [auto, setAuto] = useState(true);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);

  const add = (more: Picked[]) => setPicked((prev) => [...prev, ...more.filter((n) => !prev.some((p) => p.path === n.path))]);
  const onDrop = async (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    add(await fromDrop(e.dataTransfer));
  };
  const size = picked.reduce((n, p) => n + p.file.size, 0);
  const upload = async () => {
    setBusy(true);
    try {
      const rows = await crmApi.addFiles(picked, auto);
      const skipped = rows.filter((r) => r.status === "skipped").length;
      setPicked([]);
      toast(`${rows.length - skipped} queued${skipped ? `, ${skipped} skipped (duplicates, empty or unsupported)` : ""}`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Add files" action={<ReadBy />}>
      <div
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => void onDrop(e)}
        className={`flex flex-col items-center gap-2.5 rounded-lg border-2 border-dashed px-4 py-7 text-center transition-colors ${over ? "border-forest bg-forest-soft/60" : "border-line-strong"}`}
      >
        <p className="max-w-md text-ui text-ink-soft">
          Drop files or a whole folder here: meeting notes and transcripts, research on a person or organization, briefs
          (.docx .pdf .pptx .txt .md), and contact spreadsheets (.xlsx .csv). Folder and file names help the AI work out
          dates and who is who.
        </p>
        <div className="flex flex-wrap justify-center gap-2">
          <button className="btn btn-sm btn-soft" onClick={() => files.current?.click()}><DocIcon size={16} /> Choose files</button>
          <button className="btn btn-sm btn-soft" onClick={() => folder.current?.click()}><FolderIcon size={16} /> Choose a folder</button>
        </div>
        <input ref={files} type="file" multiple className="hidden" aria-label="Choose files" onChange={(e) => { add(fromInput(e.target.files)); e.target.value = ""; }} />
        <input
          ref={folder}
          type="file"
          className="hidden"
          aria-label="Choose a folder"
          {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          onChange={(e) => { add(fromInput(e.target.files)); e.target.value = ""; }}
        />
      </div>

      {picked.length > 0 && (
        <div className="mt-3 inset-surface p-3">
          <div className="mb-1.5 flex items-center justify-between text-ui">
            <span className="font-medium">{picked.length} file{picked.length > 1 ? "s" : ""} · {(size / 1_048_576).toFixed(1)} MB</span>
            <button className="text-hint text-ink-soft hover:text-ink" onClick={() => setPicked([])}>Clear</button>
          </div>
          <ul className="max-h-28 overflow-y-auto text-hint text-ink-soft">
            {picked.map((p) => <li key={p.path} className="truncate">{p.path}</li>)}
          </ul>
        </div>
      )}

      <label className="mt-3 flex items-start gap-2.5 text-ui text-ink-soft">
        <input type="checkbox" className="mt-1 accent-forest" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
        <span>
          <span className="font-medium text-ink">Add to your people automatically.</span> Only what needs a decision waits for you: a
          name that could be several people, or a reading by plain rules. Unticked, everything waits for review.
        </span>
      </label>
      <button className="btn btn-md btn-primary mt-4" disabled={!picked.length || busy} onClick={() => void upload()}>
        {busy ? <Spinner /> : null} Import {picked.length || ""} file{picked.length === 1 ? "" : "s"}
      </button>
    </Card>
  );
}

function AddNotes() {
  const { toast } = useShell();
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    try {
      const row = await crmApi.addNotes({ text, title: title.trim() || undefined, occurred_at: when ? new Date(when).toISOString() : undefined });
      setText("");
      setTitle("");
      setWhen("");
      location.hash = `/crm/inbox/${row.id}`;
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Write or paste notes">
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (text.trim()) void submit(); }}>
        <div className="grid gap-3 sm:grid-cols-2">
          <input className="field w-full min-w-0" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title (worked out if blank)" aria-label="Title" />
          <input type="datetime-local" className="field w-full min-w-0" value={when} onChange={(e) => setWhen(e.target.value)} aria-label="When it happened" />
        </div>
        <textarea
          className="field min-h-40 w-full resize-y"
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label="Notes"
          placeholder={"Coffee with Nora Linden\nShe chairs an angel network in Portland and offered to introduce us to two members…"}
        />
        <p className="text-hint text-ink-soft">
          Meeting notes, a transcript, a quick note about someone, a bio. A line like “Attendees: Ana Diaz (Acme), Ben Ode &lt;ben@x.com&gt;” helps.
          You review the result before anything is saved.
        </p>
        <button className="btn btn-md btn-primary" disabled={!text.trim() || busy}>
          {busy ? <Spinner /> : <SparkleIcon size={18} />} Sort and review
        </button>
      </form>
    </Card>
  );
}

/** LinkedIn's own export, and how recorded meetings and note-taking apps send things in. */
function OtherWays() {
  const { toast } = useShell();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const origin = location.origin;
  const upload = async (file: File) => {
    setBusy(true);
    try {
      const row = await crmApi.addLinkedIn(file);
      const r = (row.result ?? {}) as Record<string, number>;
      toast(`Imported ${r.rows} connections: ${r.people_created} new people, ${r.relationships} new relationships`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card title="Other ways in">
      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <h3 className="text-label font-semibold">LinkedIn connections</h3>
          <p className="mt-1 text-ui text-ink-soft">
            Use LinkedIn's own export, no scraping: Settings, Data privacy, Get a copy of your data, Connections. Then add{" "}
            <code className="rounded-sm bg-surface-subtle px-1 font-mono text-hint">Connections.csv</code>. Adding it again changes nothing.
          </p>
          <input ref={input} type="file" accept=".csv,text/csv" className="hidden" aria-label="Choose Connections.csv"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = ""; }} />
          <button className="btn btn-sm btn-soft mt-3" disabled={busy} onClick={() => input.current?.click()}>
            {busy ? <Spinner /> : <DocIcon size={16} />} Choose Connections.csv
          </button>
        </div>
        <div>
          <h3 className="text-label font-semibold">Recorded meetings and note-taking apps</h3>
          <p className="mt-1 text-ui text-ink-soft">
            A tool that records meetings can send them here. Send JSON to{" "}
            <code className="break-all rounded-sm bg-surface-subtle px-1 font-mono text-hint">POST {origin}/api/crm/ingest/meeting</code>{" "}
            (title, start, invitees with emails, notes and transcript). Sending one twice adds it once. For Zapier, n8n or Make,{" "}
            <code className="break-all rounded-sm bg-surface-subtle px-1 font-mono text-hint">POST {origin}/api/crm/ingest/webhook</code>.
            From another machine this only works when The Lodge runs as a server, with its access token.
          </p>
        </div>
      </div>
    </Card>
  );
}

const FILTERS: { key: string; label: string; statuses?: InboxStatus[] }[] = [
  { key: "all", label: "All" },
  { key: "review", label: "Needs review", statuses: ["review"] },
  { key: "active", label: "In progress", statuses: ["pending", "processing"] },
  { key: "applied", label: "Added", statuses: ["applied"] },
  { key: "other", label: "Skipped or failed", statuses: ["skipped", "failed", "discarded"] },
];

function Queue() {
  const { toast } = useShell();
  const [filter, setFilter] = useState<string | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const [busy, setBusy] = useState(false);
  const { data: summary } = useLive(crmApi.inboxSummary);
  const counts = summary?.counts ?? {};
  const total = Object.values(counts).reduce((a, b) => a + (b ?? 0), 0);
  const current = filter ?? ((counts.review ?? 0) > 0 ? "review" : "all");
  const statuses = FILTERS.find((f) => f.key === current)?.statuses;
  const { data: rows } = useLive(() => crmApi.inbox(statuses?.join(",")), [current]);
  const count = (f: (typeof FILTERS)[number]) => (f.statuses ? f.statuses.reduce((a, s) => a + (counts[s] ?? 0), 0) : total);

  const approveReady = async () => {
    if (!(await confirm({ title: "Add everything that's ready?", body: "Each item whose names are clear is added to your people now. Anything that needs a decision stays here.", confirmLabel: "Add them", tone: "primary" }))) return;
    setBusy(true);
    try {
      const r = await crmApi.applyReady();
      toast(`Added ${r.applied}${r.held ? `; ${r.held} still need a decision` : ""}`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  const resume = async () => {
    try {
      const r = await crmApi.resume();
      toast(`Carrying on with ${r.resumed} item${r.resumed === 1 ? "" : "s"}`, "success");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <section className="panel overflow-hidden">
      <header className="flex flex-wrap items-center gap-3 px-5 pt-4 pb-2">
        <h2 className="text-heading font-semibold tracking-[-0.01em]">Everything you've added</h2>
        {(summary?.active ?? 0) > 0 && !summary?.parked.count && (
          <span className="inline-flex items-center gap-2 text-ui text-ink-soft"><Spinner className="text-sky" /> Reading… {summary?.active} left</span>
        )}
        {(counts.review ?? 0) > 0 && (
          <button className="btn btn-sm btn-soft ml-auto" disabled={busy} onClick={() => void approveReady()}>
            <CheckIcon size={16} /> Add everything that's ready
          </button>
        )}
      </header>

      {summary && summary.parked.count > 0 && (
        <div className="mx-5 mb-2 flex animate-enter flex-wrap items-center gap-3 rounded-lg bg-sun-soft px-4 py-3 text-ui text-sun-deep">
          <StatusChip tone="sun" label="Paused" />
          <span className="min-w-0 flex-1 break-words">{summary.parked.count} waiting. {summary.parked.reason}</span>
          <button className="btn btn-sm btn-sun" onClick={() => void resume()}>Resume</button>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5 px-4 pb-2" role="group" aria-label="Show">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            aria-pressed={current === f.key}
            onClick={() => setFilter(f.key)}
            className={`chip h-7 gap-1.5 px-2.5 ${current === f.key ? "bg-forest-soft text-forest-deep" : "bg-surface-subtle text-ink-soft hover:text-ink"}`}
          >
            {f.label} <span className="tabular-nums">{count(f)}</span>
          </button>
        ))}
      </div>

      {!rows ? (
        <Skeleton className="m-5 h-24 rounded-lg" />
      ) : rows.length === 0 ? (
        <div className="p-5"><Empty icon={<InboxIcon size={20} />} title="Nothing here">Notes you paste and files you import appear here, with what the AI found.</Empty></div>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map((r) => <Row key={r.id} row={r} />)}
        </ul>
      )}
      {confirmDialog}
    </section>
  );
}

function Row({ row: r }: { row: InboxRow }) {
  const detail = [
    SOURCE_LABEL[r.source],
    r.category && CATEGORY_LABEL[r.category],
    relativeTime(r.created_at),
    (r.status === "skipped" || r.status === "failed") && r.error,
    r.work?.status === "waiting" && r.work.wait_reason,
  ].filter(Boolean);
  return (
    <li>
      <a href={`#/crm/inbox/${r.id}`} className="flex items-center gap-3 px-5 py-3 transition-colors hover:bg-forest/[.04]">
        <div className="min-w-0 flex-1">
          <div className="truncate text-label font-medium">{r.filename || r.title || "Untitled notes"}</div>
          <div className="truncate text-hint text-ink-soft">{detail.join(" · ")}</div>
        </div>
        <StatusPill row={r} />
      </a>
    </li>
  );
}

export default function Inbox() {
  return (
    <>
      <PageHeader title="Inbox" subtitle="Everything that enters your people passes through here, and waits for you only when it has to." />
      <div className="space-y-5">
        <div className="grid animate-enter gap-5 xl:grid-cols-2" style={{ animationDelay: "60ms" }}>
          <AddFiles />
          <AddNotes />
        </div>
        <div className="animate-enter" style={{ animationDelay: "120ms" }}><Queue /></div>
        <div className="animate-enter" style={{ animationDelay: "180ms" }}><OtherWays /></div>
      </div>
    </>
  );
}
