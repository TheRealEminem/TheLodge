// What the AI drafts for you (chunk 12): a project's status update, and a task's subtasks. Each says which AI wrote
// it, and nothing counts until you post or accept it. An update can also be offered, as a new comment, where a linked
// task lives too (named by the module that keeps it, task.synced.source); it then waits for your approval there.
import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { JobStatus } from "@core/components/blocks";
import { CheckIcon, PencilIcon, RefreshIcon, SparkleIcon, icon } from "@core/components/icons";
import { Segmented, Select, Spinner, useConfirm } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useShell } from "@core/shell";
import { Send } from "lucide-react";
import { tasksApi } from "./api";
import type { Draft, Health, Meta, Shared, StepProposal, Task, Update } from "./api";
import { formatMinutes, parseMinutes } from "./dates";

const SendIcon = icon(Send);

/** Who wrote an update: you, someone, an AI, or an AI's draft that you posted (and maybe edited). */
export function whoWrote(u: Pick<Update, "written_by" | "author_ref" | "author_name" | "edited">): string {
  const author = u.author_ref === "core:me" || !u.author_name ? "you" : u.author_name;
  if (u.written_by && (u.author_ref || u.author_name)) return `Drafted by ${u.written_by}, ${u.edited ? "edited and posted" : "posted"} by ${author}`;
  if (u.written_by) return `Written by ${u.written_by}`;
  return author === "you" ? "You" : author;
}

/** The linked tasks a project's update can go on (open ones first), and where they're kept. */
export function commentTargets(tasks: Task[] | null | undefined): { targets: Task[]; where: string | null } {
  const targets = (tasks ?? [])
    .filter((t) => t.synced && !t.synced.removed_at)
    .sort((a, b) => Number(a.done || a.status === "dropped") - Number(b.done || b.status === "dropped"));
  return { targets, where: targets[0]?.synced?.source ?? null };
}

function useAct() {
  const { toast } = useShell();
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (what: string, work: () => Promise<unknown>, done?: string) => {
    setBusy(what);
    try {
      await work();
      if (done) toast(done, "success");
      return true;
    } catch (e) {
      toast((e as Error).message, "error");
      return false;
    } finally {
      setBusy(null);
    }
  };
  return { act, busy };
}

// ── Offered elsewhere ─────────────────────────────────────────────────

function SharedLine({ shared }: { shared: Shared[] }) {
  return (
    <>
      {shared.map((s) => (
        <a key={s.href} href={s.href} className={`inline-flex items-center gap-1 hover:underline ${s.state === "posted" ? "text-forest-deep" : "text-sun-deep"}`}>
          <SendIcon size={12} />
          {s.state === "waiting" ? `${s.title} · Review` : s.title}
        </a>
      ))}
    </>
  );
}

/** Under an update: where it waits or was posted, or a way to offer it. A task's own comment (onTask): a button; a
 *  project's update: choose which of its linked tasks it goes on. */
export function OfferUpdate({
  update,
  targets,
  where,
  onTask = false,
  onChanged,
}: {
  update: Update;
  targets: Task[];
  where: string | null;
  onTask?: boolean;
  onChanged: () => void;
}) {
  const { act, busy } = useAct();
  if (update.shared?.length) return <SharedLine shared={update.shared} />;
  if (!where || !targets.length) return null;
  const offer = (itemId?: string) =>
    void act("offer", () => tasksApi.shareUpdate(update.id, itemId).then(onChanged), `Waiting for you to send it to ${where}`);
  if (onTask) {
    return (
      <button className="inline-flex items-center gap-1 text-ink-soft hover:text-forest" disabled={!!busy} onClick={() => offer()}>
        {busy ? <Spinner /> : <SendIcon size={12} />} Post in {where} too
      </button>
    );
  }
  return (
    <Select
      label={`Post it in ${where} too, as a comment on one of this project's tasks`}
      size="sm"
      className="w-full sm:w-72"
      disabled={!!busy}
      value=""
      options={[{ value: "", label: `Post in ${where} too, on…` }, ...targets.map((t) => ({ value: t.id, label: t.text }))]}
      onChange={(v) => v && offer(v)}
    />
  );
}

// ── A project's status draft ──────────────────────────────────────────

export function DraftStatusButton({ projectId, draft, onChanged }: { projectId: string; draft: Draft | null | undefined; onChanged: () => void }) {
  const { act, busy } = useAct();
  const [confirm, dialog] = useConfirm();
  const drafting = draft?.status === "drafting" && draft.job?.status !== "error";
  const start = async () => {
    if (draft?.edited) {
      const ok = await confirm({ title: "Draft it again?", body: "Your changes to this draft are replaced by a new one.", confirmLabel: "Draft again" });
      if (!ok) return;
    }
    void act("draft", () => tasksApi.draftStatus(projectId).then(onChanged));
  };
  return (
    <>
      <button className="btn btn-sm btn-ghost -my-1" disabled={drafting || !!busy} onClick={() => void start()} data-tip="The AI reads the project and drafts an update for you to edit">
        {drafting || busy ? <Spinner /> : <SparkleIcon size={16} />}
        {draft ? "Draft again" : "Draft a status"}
      </button>
      {dialog}
    </>
  );
}

export function StatusDraftPanel({
  draft,
  meta,
  targets,
  where,
  onChanged,
}: {
  draft: Draft | null | undefined;
  meta: Meta | null;
  targets: Task[];
  where: string | null;
  onChanged: () => void;
}) {
  const { act, busy } = useAct();
  const [confirm, dialog] = useConfirm();
  const [body, setBody] = useState<string | null>(null);
  const [shareOn, setShareOn] = useState("");
  useEffect(() => setBody(null), [draft?.id, draft?.written_by]);
  if (!draft) return null;
  if (draft.status === "drafting") {
    return (
      <div className="inset-surface mb-3 px-4 py-3.5" aria-label="Drafting a status update">
        {draft.job ? (
          <JobStatus job={draft.job} />
        ) : (
          <span className="flex items-center gap-2 text-ui text-ink-soft">
            <Spinner className="text-sky" /> Drafting…
          </span>
        )}
      </div>
    );
  }

  const text = body ?? draft.body;
  const flush = () => (body !== null && body !== draft.body ? tasksApi.editDraft(draft.id, { body }) : Promise.resolve(null));
  const save = (changes: { body?: string; health?: Health | null }) => void act("edit", () => tasksApi.editDraft(draft.id, changes).then(onChanged));
  const post = () =>
    void act(
      "post",
      () =>
        flush()
          .then(() => tasksApi.postDraft(draft.id, shareOn || null))
          .then(onChanged),
      shareOn && where ? `Posted. It waits for you to send it to ${where}.` : "Posted.",
    );
  const discard = async () => {
    if (draft.edited || (body !== null && body !== draft.body)) {
      const ok = await confirm({ title: "Discard this draft?", body: "Your changes to it are lost. Nothing was posted.", confirmLabel: "Discard" });
      if (!ok) return;
    }
    void act("discard", () => tasksApi.discardDraft(draft.id).then(onChanged));
  };

  return (
    <section className="panel mb-3 animate-enter overflow-hidden" aria-label="Status draft">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-5 pt-4">
        <SparkleIcon size={16} className="text-ink-faint" />
        <span className="text-label font-semibold">Draft status update</span>
        <span className="text-meta text-ink-soft" data-tip={formatDate(draft.updated_at)}>
          Drafted by {draft.written_by ?? "AI"}
          {draft.edited ? ", edited by you" : ""} · {relativeTime(draft.updated_at)}
        </span>
      </div>
      <div className="px-5 pt-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span className="text-hint text-ink-soft">Health it suggests</span>
          <Segmented<Health | "">
            label="Health"
            size="sm"
            value={draft.health ?? ""}
            onChange={(h) => save({ health: h || null })}
            options={[{ id: "", label: "None" }, ...(meta?.health ?? []).map((h) => ({ id: h.value as Health, label: h.label }))]}
          />
        </div>
        {draft.why && <p className="mt-1.5 text-hint text-ink-soft">{draft.why}</p>}
        <textarea
          aria-label="Draft update"
          className="field mt-3 min-h-[10rem] w-full resize-y py-2.5 leading-relaxed"
          value={text}
          onChange={(e) => setBody(e.target.value)}
          onBlur={() => {
            if (body !== null && body !== draft.body) void act("edit", () => tasksApi.editDraft(draft.id, { body }).then(onChanged));
          }}
        />
        <p className="mt-1 text-meta text-ink-faint">Markdown works. Posting it makes it the project's status update, and its health the project's.</p>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line px-5 py-3">
        {where && targets.length > 0 && (
          <Select
            label={`Also offer it to ${where}`}
            size="sm"
            className="w-full sm:mr-auto sm:w-72"
            value={shareOn}
            onChange={setShareOn}
            options={[{ value: "", label: "Only here" }, ...targets.map((t) => ({ value: t.id, label: `In ${where} too, on ${t.text}` }))]}
          />
        )}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button className="btn btn-sm btn-ghost" disabled={!!busy} onClick={() => void discard()}>
            Discard
          </button>
          <button className="btn btn-sm btn-primary" disabled={!!busy || !text.trim()} onClick={post}>
            {busy === "post" ? <Spinner /> : shareOn ? <SendIcon size={16} /> : <CheckIcon size={16} />}
            {shareOn && where ? `Post, and offer to ${where}` : "Post update"}
          </button>
        </div>
      </div>
      {dialog}
    </section>
  );
}

// ── A task broken down ────────────────────────────────────────────────

export function BreakDownButton({ taskId, draft, onChanged }: { taskId: string; draft: Draft | null | undefined; onChanged: () => void }) {
  const { act, busy } = useAct();
  const drafting = draft?.status === "drafting" && draft.job?.status !== "error";
  return (
    <button
      className="btn btn-sm btn-ghost -my-1"
      disabled={drafting || !!busy}
      onClick={() => void act("draft", () => tasksApi.breakDown(taskId).then(onChanged))}
      data-tip="The AI proposes subtasks with estimates, for you to accept, edit or drop"
    >
      {drafting || busy ? <Spinner /> : <SparkleIcon size={16} />}
      Break it down
    </button>
  );
}

function StepRow({ p, draftId, onChanged }: { p: StepProposal; draftId: string; onChanged: () => void }) {
  const { act, busy } = useAct();
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(p.text);
  const [estimate, setEstimate] = useState(formatMinutes(p.estimate_min));
  const change = (c: { text?: string; estimate_min?: number | null; state?: "proposed" | "dropped" }) =>
    act("edit", () => tasksApi.editProposal(draftId, p.id, c).then(onChanged));
  if (editing) {
    const save = async () => {
      const min = parseMinutes(estimate);
      if (min === undefined) return void act("edit", () => Promise.reject(new Error("Write an estimate like 45, 2h or 1h30")));
      if (await change({ text: text.trim(), estimate_min: min })) setEditing(false);
    };
    const keys = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEditing(false);
      if (e.key === "Enter" && text.trim()) void save();
    };
    return (
      <li className="animate-fade-in py-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <input autoFocus aria-label="Subtask" className="field h-9 flex-1" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={keys} />
          <input aria-label="Estimate" className="field h-9 w-full sm:w-28" placeholder="Estimate" value={estimate} onChange={(e) => setEstimate(e.target.value)} onKeyDown={keys} />
        </div>
        <div className="mt-2 flex justify-end gap-2">
          <button className="btn btn-sm btn-ghost" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button className="btn btn-sm btn-soft" disabled={!text.trim() || !!busy} onClick={() => void save()}>
            Save
          </button>
        </div>
      </li>
    );
  }
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-3">
      <div className="flex min-w-0 flex-1 items-baseline gap-2">
        <span className="min-w-0 text-label leading-snug">{p.text}</span>
        {p.estimate_min != null && <span className="chip shrink-0 bg-surface-subtle tabular-nums text-ink-soft">{formatMinutes(p.estimate_min)}</span>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button className="btn btn-sm btn-soft" disabled={!!busy} onClick={() => void act("accept", () => tasksApi.acceptProposals(draftId, [p.id]).then(onChanged))}>
          <CheckIcon size={16} /> Accept
        </button>
        <button className="icon-btn" aria-label={`Edit "${p.text}"`} data-tip="Edit" onClick={() => setEditing(true)}>
          <PencilIcon size={16} />
        </button>
        <button className="btn btn-sm btn-danger-ghost" disabled={!!busy} onClick={() => void change({ state: "dropped" })}>
          Drop
        </button>
      </div>
    </li>
  );
}

export function BreakdownPanel({ draft, onChanged }: { draft: Draft | null | undefined; onChanged: () => void }) {
  const { act, busy } = useAct();
  if (!draft) return null;
  if (draft.status === "drafting") {
    return (
      <div className="inset-surface mb-2 px-4 py-3.5" aria-label="Breaking it down">
        {draft.job ? (
          <JobStatus job={draft.job} />
        ) : (
          <span className="flex items-center gap-2 text-ui text-ink-soft">
            <Spinner className="text-sky" /> Breaking it down…
          </span>
        )}
      </div>
    );
  }
  const proposed = draft.proposals.filter((p) => p.state === "proposed");
  const dropped = draft.proposals.filter((p) => p.state === "dropped");
  if (draft.proposals.length > 0 && !proposed.length && !dropped.length) return null; // all accepted: they're subtasks now
  const total = proposed.reduce((n, p) => n + (p.estimate_min ?? 0), 0);
  return (
    <section className="panel mb-2 animate-enter px-5" aria-label="Proposed subtasks">
      <div className="flex flex-wrap items-center justify-between gap-2 pb-1 pt-3.5">
        <p className="flex items-center gap-1.5 text-hint text-ink-soft">
          <SparkleIcon size={14} className="text-ink-faint" />
          {proposed.length ? `${proposed.length} proposed` : "Nothing new proposed"} by {draft.written_by ?? "AI"}
          {total > 0 && <span className="tabular-nums">· {formatMinutes(total)} in all</span>}
        </p>
        <div className="flex items-center gap-1.5">
          {proposed.length > 1 && (
            <button className="btn btn-sm btn-soft" disabled={!!busy} onClick={() => void act("all", () => tasksApi.acceptProposals(draft.id).then(onChanged), `${proposed.length} subtasks added.`)}>
              <CheckIcon size={16} /> Accept all
            </button>
          )}
          <button className="btn btn-sm btn-ghost" disabled={!!busy} onClick={() => void act("discard", () => tasksApi.discardDraft(draft.id).then(onChanged))}>
            {proposed.length ? "Discard" : "Done"}
          </button>
        </div>
      </div>
      {proposed.length > 0 && (
        <ul className="divide-y divide-line">
          {proposed.map((p) => (
            <StepRow key={p.id} p={p} draftId={draft.id} onChanged={onChanged} />
          ))}
        </ul>
      )}
      {dropped.length > 0 && (
        <ul className="border-t border-line py-2">
          {dropped.map((p) => (
            <li key={p.id} className="flex items-center gap-3 py-1">
              <span className="min-w-0 flex-1 truncate text-hint text-ink-soft line-through decoration-ink-faint">{p.text}</span>
              <button className="btn btn-sm btn-ghost shrink-0" disabled={!!busy} onClick={() => void act("back", () => tasksApi.editProposal(draft.id, p.id, { state: "proposed" }).then(onChanged))}>
                <RefreshIcon size={14} /> Bring back
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
