// A person's portrait, and rehearsals with them as the AI plays them (the server half is talk.py).
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@core/api";
import { AlertIcon, ArrowUpIcon, PlusIcon, RefreshIcon, SparkleIcon, TrashIcon } from "@core/components/icons";
import { Select, Skeleton, Spinner } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useLive } from "@core/live";
import { useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { sedimentApi } from "./api";
import type { Line } from "./api";
import { Waiting } from "./bits";

const Markdown = ({ children }: { children: string }) => (
  <div className="prose-family [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
    <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
  </div>
);

function NotSetUp({ reason, doing }: { reason: string; doing: string }) {
  return (
    <p className="text-ui text-ink-soft">
      {reason || "No AI is set up for this yet"}. Choose one under <a href="#/settings" className="font-medium text-forest-deep hover:underline">Settings → AI</a> to {doing}.
    </p>
  );
}

// ── The portrait ──────────────────────────────────────────────────────

export function PortraitPanel({ personRef, first }: { personRef: string; first: string }) {
  const { toast } = useShell();
  const { data, error } = useLive(() => sedimentApi.portrait(personRef), [personRef]);
  if (error) return <p className="text-ui text-ink-soft">{error}</p>;
  if (!data) return <Skeleton className="h-40 w-full rounded-xl" />;
  const { portrait, job, ready, reason, material, provider } = data;
  const working = !!job && (job.status === "queued" || job.status === "running");
  const redo = () => sedimentApi.redoPortrait(personRef).catch((e: Error) => toast(e.message, "error"));

  let body: ReactNode;
  // A "**How they talk**" line straight above its sentence would run into it as one paragraph: give it its own.
  if (portrait) body = <Markdown>{portrait.body.replace(/^(\*\*[^*\n]+\*\*)[ \t]*\n(?!\n)/gm, "$1\n\n")}</Markdown>;
  else if (!material) body = <p className="text-ui text-ink-soft">Not much on file about {first} yet. Add a note, a meeting or their role, and a portrait will follow.</p>;
  else if (!ready) body = <NotSetUp reason={reason} doing={`get a portrait of ${first}`} />;
  else if (job?.status === "waiting") body = <Waiting job={job} />;
  else if (job?.status === "error") {
    body = (
      <div className="rounded-lg border border-trail/20 bg-trail-soft/70 px-4 py-3">
        <p className="flex items-start gap-1.5 text-ui text-trail-deep"><AlertIcon size={16} className="mt-0.5 shrink-0" /><span className="break-words">The portrait didn't come through. {job.error}</span></p>
        <button className="btn btn-sm btn-soft mt-2.5" onClick={() => api.jobRetry(job.id).catch((e: Error) => toast(e.message, "error"))}><RefreshIcon size={16} /> Try again</button>
      </div>
    );
  } else {
    body = (
      <div className="space-y-2.5" aria-busy="true">
        <Skeleton className="h-3.5 w-full rounded-full" />
        <Skeleton className="h-3.5 w-11/12 rounded-full" />
        <Skeleton className="h-3.5 w-2/3 rounded-full" />
        <p className="flex items-center gap-2 pt-1 text-hint text-ink-soft"><Spinner className="text-sky" /> Writing a portrait of {first} with {provider}…</p>
      </div>
    );
  }

  return (
    <section className="panel animate-enter p-5 sm:px-6">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-heading font-semibold tracking-[-0.01em]">{first} as a whole</h2>
        {portrait && ready && (
          <button className="btn btn-sm btn-ghost" disabled={working} onClick={() => void redo()} data-tip="Write it again from what's on file now">
            <RefreshIcon size={16} /> Redo
          </button>
        )}
      </header>
      {body}
      {portrait && (
        <p className="mt-4 flex flex-wrap items-center gap-x-2 text-meta text-ink-soft">
          <span>Written by {portrait.written_by} · {relativeTime(portrait.created_at)}</span>
          {!portrait.current && working && <span className="inline-flex items-center gap-1.5"><Spinner className="text-sky" /> updating with what's new</span>}
        </p>
      )}
      {material && data.voice === 0 && (
        <p className="mt-3 text-hint text-ink-soft">No transcripts of {first}'s own words are on file, so how they talk is read from your notes.</p>
      )}
      <p className="mt-3 text-hint text-ink-soft">This is what a rehearsal plays {first} from. It's the AI's reading of your records, and nothing here is added to their profile.</p>
    </section>
  );
}

// ── Rehearsals ────────────────────────────────────────────────────────

/** Their reply, with each phrase the AI made up underlined. */
function Marked({ text, guesses }: { text: string; guesses: string[] }) {
  const spans: [number, number][] = [];
  for (const g of guesses) {
    const at = text.indexOf(g);
    if (at >= 0 && !spans.some(([a, b]) => at < b && at + g.length > a)) spans.push([at, at + g.length]);
  }
  spans.sort((x, y) => x[0] - y[0]);
  const out: ReactNode[] = [];
  let i = 0;
  for (const [a, b] of spans) {
    if (a > i) out.push(text.slice(i, a));
    out.push(<span key={a} className="underline decoration-sun decoration-dotted decoration-2 underline-offset-4" data-tip="A guess, not on file">{text.slice(a, b)}</span>);
    i = b;
  }
  if (i < text.length) out.push(text.slice(i));
  return <p className="whitespace-pre-wrap text-label">{out}</p>;
}

function TheirLine({ line, first }: { line: Line; first: string }) {
  const { toast } = useShell();
  const [why, setWhy] = useState(false);
  const retry = () => sedimentApi.retryLine(line.id).catch((e: Error) => toast(e.message, "error"));
  return (
    <div className="flex gap-3">
      <span className="chip mt-0.5 h-7 shrink-0 bg-berry-soft px-2.5 text-berry-deep" data-tip={line.written_by ? `Played by ${line.written_by}` : undefined}>{first}</span>
      <div className="min-w-0 flex-1 pt-1">
        {line.status === "done" ? (
          <>
            <Marked text={line.body} guesses={line.guesses} />
            {(line.grounds.length > 0 || line.guesses.length > 0) && (
              <button className="mt-1 text-meta font-medium text-forest-deep hover:underline" onClick={() => setWhy(!why)} aria-expanded={why}>
                {why ? "Hide why" : "Why?"}
              </button>
            )}
            {why && (
              <ul className="mt-1.5 space-y-1 border-l-2 border-line pl-3 text-meta text-ink-soft">
                {line.grounds.map((g) => <li key={g.phrase}>“{g.phrase}” rests on {g.source}</li>)}
                {line.guesses.map((g) => <li key={g}>“{g}” is a guess: nothing on file says it</li>)}
                {line.grounds.length === 0 && <li>Nothing in this reply was matched to a record.</li>}
              </ul>
            )}
          </>
        ) : line.status === "error" ? (
          <div className="flex flex-wrap items-start gap-x-3 gap-y-2 text-ui text-trail-deep">
            <span className="flex min-w-0 items-start gap-1.5"><AlertIcon size={16} className="mt-0.5 shrink-0" /><span className="break-words">{line.error || "The reply didn't come through."}</span></span>
            <button className="btn btn-sm btn-soft" onClick={() => void retry()}><RefreshIcon size={16} /> Try again</button>
          </div>
        ) : line.job?.status === "waiting" ? (
          <Waiting job={line.job} />
        ) : (
          <p className="flex items-center gap-2 text-ui text-ink-soft"><Spinner className="text-sky" /> Writing {first}'s reply…</p>
        )}
      </div>
    </div>
  );
}

export function RehearsePanel({ personRef, first }: { personRef: string; first: string }) {
  const { toast, confirm } = useShell();
  const [query, setQuery] = useQueryParams();
  const { data: list } = useLive(() => sedimentApi.conversations(personRef), [personRef]);
  const { data: ai } = useLive(sedimentApi.ai);
  const chosen = query.get("c") || list?.[0]?.id || null;
  const [fresh, setFresh] = useState(false);
  const starting = fresh || (list !== null && list.length === 0);
  const talk = ai?.talk;

  const remove = async () => {
    if (!chosen) return;
    if (!(await confirm({ title: "Delete this rehearsal?", body: "Its lines are deleted. Nothing in People changes.", confirmLabel: "Delete", tone: "danger" }))) return;
    try {
      await sedimentApi.removeConversation(chosen);
      setQuery({ c: null });
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <section className="panel animate-enter p-5 sm:px-6">
      <p className="mb-4 flex items-start gap-2.5 rounded-lg border border-line bg-surface-subtle px-4 py-3 text-ui">
        <SparkleIcon size={16} className="mt-0.5 shrink-0 text-ink-soft" />
        <span>
          <span className="font-medium">A simulation from your records, not {first}.</span>{" "}
          <span className="text-ink-soft">Anything it makes up is underlined, and “Why?” shows what a reply rests on.</span>
        </span>
      </p>

      {list === null ? (
        <Skeleton className="h-24 w-full rounded-xl" />
      ) : !talk?.ready && talk ? (
        <NotSetUp reason={talk.reason} doing={`rehearse with ${first}`} />
      ) : starting ? (
        <Start personRef={personRef} first={first} onStarted={(id) => { setFresh(false); setQuery({ c: id }); }} onCancel={list.length ? () => setFresh(false) : undefined} />
      ) : (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Select
              label="Rehearsal"
              size="sm"
              className="min-w-0 flex-1 sm:max-w-sm"
              value={chosen ?? ""}
              onChange={(id) => setQuery({ c: id })}
              options={list.map((c) => ({ value: c.id, label: c.scenario || "No scene set", hint: `${formatDate(c.created_at)} · ${c.messages} line${c.messages === 1 ? "" : "s"}` }))}
            />
            <button className="btn btn-sm btn-soft" onClick={() => setFresh(true)}><PlusIcon size={16} /> New rehearsal</button>
            <button className="btn btn-sm btn-danger-ghost" aria-label="Delete this rehearsal" data-tip="Delete this rehearsal" onClick={() => void remove()}><TrashIcon size={16} /></button>
          </div>
          {chosen && <Thread id={chosen} first={first} />}
        </>
      )}
      {talk && (
        <p className="mt-3 text-meta text-ink-soft">
          {first} is played by {talk.label}{talk.local ? " on this Mac" : ""}, from their portrait and what's on file. Nothing said here is added to their profile.
        </p>
      )}
    </section>
  );
}

function Start({ personRef, first, onStarted, onCancel }: { personRef: string; first: string; onStarted: (id: string) => void; onCancel?: () => void }) {
  const { toast } = useShell();
  const [scenario, setScenario] = useState("");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try {
      onStarted((await sedimentApi.start(personRef, scenario)).id);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={(e) => { e.preventDefault(); void go(); }}>
      <label className="block">
        <span className="mb-1 block text-ui font-medium">What's the scene?</span>
        <input className="field h-10 w-full" value={scenario} onChange={(e) => setScenario(e.target.value)} maxLength={600}
          placeholder={`Asking ${first} for an intro, pitching a renewal, a hard conversation…`} />
        <span className="mt-1 block text-hint text-ink-soft">Optional. It tells the simulation what you're practicing for.</span>
      </label>
      <div className="mt-3 flex gap-2">
        <button className="btn btn-md btn-primary" disabled={busy}>{busy && <Spinner />} Start a rehearsal</button>
        {onCancel && <button type="button" className="btn btn-md btn-ghost" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
}

function Thread({ id, first }: { id: string; first: string }) {
  const { toast } = useShell();
  const { data } = useLive(() => sedimentApi.conversation(id), [id]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const lines = data?.messages ?? [];
  const pending = lines.some((l) => l.status === "queued");
  const last = lines[lines.length - 1];

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [lines.length, last?.status]);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  const send = async () => {
    const t = text.trim();
    if (!t || sending || pending) return;
    setSending(true);
    try {
      await sedimentApi.say(id, t);
      setText("");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
      box.current?.focus();
    }
  };

  if (!data) return <Skeleton className="h-24 w-full rounded-xl" />;
  return (
    <>
      {lines.length > 0 ? (
        <div className="fade-edges-y -mx-1 mb-4 max-h-[520px] space-y-4 overflow-y-auto px-1 py-1">
          {lines.map((l) => l.role === "you" ? (
            <div key={l.id} className="flex animate-fade-in justify-end">
              <p className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-xs bg-sky-soft px-3.5 py-2 text-label text-sky-deep">{l.body}</p>
            </div>
          ) : (
            <div key={l.id} className="animate-fade-in"><TheirLine line={l} first={first} /></div>
          ))}
          <div ref={end} />
        </div>
      ) : (
        <p className="mb-3 text-ui text-ink-soft">Say the first line, the way you would to {first}.</p>
      )}
      <form className="relative" onSubmit={(e) => { e.preventDefault(); void send(); }}>
        <textarea
          ref={box}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={pending ? `Waiting for ${first}'s reply…` : `Say something to ${first}…`}
          aria-label={`Say something to ${first}`}
          className="field block max-h-40 min-h-[44px] w-full resize-none py-[11px] pl-3.5 pr-12"
        />
        <button className="btn btn-sm btn-primary absolute bottom-1.5 right-1.5 h-8 w-8 px-0" disabled={!text.trim() || sending || pending} aria-label="Send">
          {sending ? <Spinner /> : <ArrowUpIcon size={16} />}
        </button>
      </form>
    </>
  );
}
