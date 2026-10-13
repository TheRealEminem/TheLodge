// A person's AI overview, and the questions you ask about them (the server half is profiles.py).
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { JobStatus } from "@core/components/blocks";
import { AlertIcon, ArrowUpIcon, ChatIcon, RefreshIcon, SparkleIcon, TrashIcon } from "@core/components/icons";
import { Skeleton, Spinner } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { crmApi } from "./api";
import type { Entity, OverviewState, Question } from "./api";
import { relativeTime } from "./format";

const firstName = (name: string) => name.trim().split(/\s+/)[0];

function Panel({ icon, title, action, children }: { icon: ReactNode; title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="panel animate-enter p-5 sm:px-6">
      <header className="mb-3 flex items-center justify-between gap-3">
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

/** Everyone but you: their overview, then a place to ask about them. */
export function Briefing({ person }: { person: Entity }) {
  const { data } = useLive(() => crmApi.overview(person.id), [person.id]);
  if (!data) return <Skeleton className="h-36 w-full rounded-xl" />;
  return (
    <>
      <OverviewCard person={person} state={data} />
      <AskCard person={person} state={data} />
    </>
  );
}

function OverviewCard({ person, state }: { person: Entity; state: OverviewState }) {
  const { toast } = useShell();
  const { overview, job, ready, reason, material, provider } = state;
  const working = !!job && (job.status === "queued" || job.status === "running");
  const redo = () => crmApi.redoOverview(person.id).catch((e: Error) => toast(e.message, "error"));

  let body: ReactNode;
  if (overview) body = <Markdown>{overview.body}</Markdown>;
  else if (!material) body = <p className="text-ui text-ink-soft">Not much on file about {firstName(person.name)} yet. Add a note, a meeting or their role, and an overview will follow.</p>;
  else if (!ready) body = <NotSetUp reason={reason} doing="get an overview of everyone" />;
  else if (job?.status === "error" || job?.status === "waiting") body = null;
  else {
    body = (
      <div className="space-y-2.5" aria-busy="true">
        <Skeleton className="h-3.5 w-full rounded-full" />
        <Skeleton className="h-3.5 w-11/12 rounded-full" />
        <Skeleton className="h-3.5 w-2/3 rounded-full" />
        <p className="flex items-center gap-2 pt-1 text-hint text-ink-soft"><Spinner className="text-sky" /> Writing an overview with {provider}…</p>
      </div>
    );
  }

  return (
    <Panel
      icon={<SparkleIcon size={16} />}
      title="Overview"
      action={overview && ready && (
        <button className="btn btn-sm btn-ghost" disabled={working} onClick={() => void redo()} data-tip="Write it again from what's on file now">
          <RefreshIcon size={16} /> Redo
        </button>
      )}
    >
      {body}
      {(job?.status === "error" || job?.status === "waiting") && <div className={body ? "mt-4" : ""}><JobStatus job={job} startLabel="Write it" /></div>}
      {overview && (
        <p className="mt-3 flex flex-wrap items-center gap-x-2 text-meta text-ink-soft">
          <span>Written by {overview.written_by} · {relativeTime(overview.created_at)}</span>
          {!overview.current && working && <span className="inline-flex items-center gap-1.5"><Spinner className="text-sky" /> updating with what's new</span>}
        </p>
      )}
    </Panel>
  );
}

const SUGGESTIONS = ["What did we last talk about?", "What should I follow up on?", "Who do we both know?", "How do I know them?"];

function AskCard({ person, state }: { person: Entity; state: OverviewState }) {
  const { toast, confirm } = useShell();
  const { data: thread } = useLive(() => crmApi.questions(person.id), [person.id]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const first = firstName(person.name);
  const count = thread?.length ?? 0;
  const lastStatus = thread?.[count - 1]?.status;

  useEffect(() => {
    end.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [count, lastStatus]);

  // The box grows with what's typed (up to its max height) and shrinks back once it's sent.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text]);

  const send = async (question: string) => {
    const q = question.trim();
    if (!q || sending) return;
    setSending(true);
    try {
      await crmApi.ask(person.id, q);
      setText("");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
      box.current?.focus();
    }
  };
  const clear = async () => {
    if (!(await confirm({ title: `Clear the questions about ${first}?`, body: "The questions and answers are deleted. The overview stays.", confirmLabel: "Clear", tone: "danger" }))) return;
    crmApi.clearQuestions(person.id).catch((e: Error) => toast(e.message, "error"));
  };

  return (
    <Panel
      icon={<ChatIcon size={16} />}
      title={`Ask about ${first}`}
      action={count > 0 && (
        <button className="btn btn-sm btn-danger-ghost" onClick={() => void clear()} aria-label="Clear the questions" data-tip="Clear the questions">
          <TrashIcon size={16} />
        </button>
      )}
    >
      {count > 0 && (
        <div className="fade-edges-y -mx-1 mb-4 max-h-[460px] space-y-4 overflow-y-auto px-1 py-1">
          {thread!.map((q) => <Exchange key={q.id} q={q} />)}
          <div ref={end} />
        </div>
      )}
      {!state.ready ? (
        <NotSetUp reason={state.reason} doing={`ask about ${first}`} />
      ) : (
        <>
          {count === 0 && (
            <div className="mb-3 flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="chip h-7 bg-surface-subtle px-3 text-ink-soft transition-colors duration-150 hover:bg-forest/10 hover:text-ink" disabled={sending} onClick={() => void send(s)}>
                  {s}
                </button>
              ))}
            </div>
          )}
          <form
            className="relative"
            onSubmit={(e) => {
              e.preventDefault();
              void send(text);
            }}
          >
            <textarea
              ref={box}
              rows={1}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  void send(text);
                }
              }}
              placeholder={`Ask anything about ${first}…`}
              aria-label={`Ask about ${first}`}
              className="field block max-h-40 min-h-[44px] w-full resize-none py-[11px] pl-3.5 pr-12"
            />
            <button className="btn btn-sm btn-primary absolute bottom-1.5 right-1.5 h-8 w-8 px-0" disabled={!text.trim() || sending} aria-label="Ask">
              {sending ? <Spinner /> : <ArrowUpIcon size={16} />}
            </button>
          </form>
          <p className="mt-2 text-meta text-ink-soft">Answers come from what's on file about {first}, using {state.provider}{state.local ? " on this Mac" : ""}.</p>
        </>
      )}
    </Panel>
  );
}

function Exchange({ q }: { q: Question }) {
  const { toast } = useShell();
  const retry = () => crmApi.retryQuestion(q.id).catch((e: Error) => toast(e.message, "error"));
  return (
    <div className="animate-fade-in space-y-2.5">
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-br-xs bg-sky-soft px-3.5 py-2 text-label text-sky-deep">{q.question}</p>
      </div>
      <div className="flex gap-3">
        <span className="well well-forest mt-0.5 h-7 w-7 shrink-0" data-tip={q.written_by ? `Answered by ${q.written_by}` : undefined}>
          <SparkleIcon size={14} />
        </span>
        <div className="min-w-0 flex-1 pt-0.5">
          {q.status === "done" && q.answer ? (
            <Markdown>{q.answer}</Markdown>
          ) : q.status === "error" ? (
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2 text-ui text-trail-deep">
              <span className="flex min-w-0 items-start gap-1.5"><AlertIcon size={16} className="mt-0.5 shrink-0" /><span className="break-words">{q.error || "That didn't come through."}</span></span>
              <button className="btn btn-sm btn-soft" onClick={() => void retry()}><RefreshIcon size={16} /> Try again</button>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-ui text-ink-soft"><Spinner className="text-sky" /> Thinking…</p>
          )}
        </div>
      </div>
    </div>
  );
}
