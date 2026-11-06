// On a linked task's page: what it's kept in step with elsewhere (a Plane work item), and anything waiting for you.
// Fields you haven't changed follow the other side by themselves; a field changed on both sides shows both values
// until you take theirs or keep yours. What you've changed goes there only when you send it, and then only after you
// approve it where it's going (task.sharing says where it waits). A task that isn't linked, in a project that is, can
// be sent to be made there. Nothing here knows what "elsewhere" is: the server names it (synced.source).
import { useState } from "react";
import { AlertIcon, ExternalIcon, NetworkIcon, icon } from "@core/components/icons";
import { Spinner, useConfirm } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useShell } from "@core/shell";
import { Send } from "lucide-react";
import { tasksApi } from "./api";
import type { Meta, ProjectDetail, SyncedField, Task, TaskDetail } from "./api";

const SendIcon = icon(Send);

const FIELD_LABEL: Record<SyncedField, string> = {
  text: "Title",
  notes: "Notes",
  status: "Status",
  priority: "Priority",
  start_on: "Start",
  due_on: "Due",
  assignee: "Assignee",
};

/** One field's value, the way the task page shows it. */
function shown(field: SyncedField, v: Partial<Task>, meta: Meta | null): string {
  switch (field) {
    case "status":
      return meta?.statuses.find((s) => s.value === v.status)?.label ?? String(v.status ?? "");
    case "priority":
      return meta?.priorities.find((p) => p.value === v.priority)?.label ?? String(v.priority ?? "");
    case "start_on":
    case "due_on": {
      const day = v[field];
      return day
        ? formatDate(`${day}T12:00:00`, {
            weekday: "short",
            month: "short",
            day: "numeric",
          })
        : "None";
    }
    case "assignee":
      return v.assignee_ref === "core:me" ? "You" : v.assignee_name || (v.assignee_ref ? "Someone" : "No one");
    case "notes": {
      const text = (v.notes ?? "").trim();
      return text ? (text.length > 140 ? `${text.slice(0, 140)}…` : text) : "Empty";
    }
    default:
      return String(v.text ?? "");
  }
}

/** "Send to Plane": asks for the task to be sent; it then waits for your approval where it's going. */
function useSend(task: TaskDetail, onChanged: () => void) {
  const { toast } = useShell();
  const [busy, setBusy] = useState(false);
  const send = async () => {
    setBusy(true);
    try {
      const sent = await tasksApi.share(task.id);
      toast(sent.sharing[0]?.title ?? "Waiting for you to send it", "success");
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return { send, busy };
}

/** Where the task's changes wait for you, with a way there; or the button that sends them. */
function SendRow({ task, label, onChanged }: { task: TaskDetail; label: string; onChanged: () => void }) {
  const { send, busy } = useSend(task, onChanged);
  const waiting = task.sharing[0];
  if (waiting) {
    return (
      <a href={waiting.href} className="btn btn-sm btn-sun -my-1">
        <SendIcon size={16} /> Review and send
      </a>
    );
  }
  return (
    <button className="btn btn-sm btn-soft -my-1" disabled={busy} onClick={() => void send()}>
      {busy ? <Spinner /> : <SendIcon size={16} />} {label}
    </button>
  );
}

export function SyncedPanel({
  task,
  meta,
  project,
  onChanged,
}: {
  task: TaskDetail;
  meta: Meta | null;
  project?: ProjectDetail | null;
  onChanged: () => void;
}) {
  const { toast } = useShell();
  const [confirm, dialog] = useConfirm();
  const synced = task.synced;
  if (!synced) return <NotSentYet task={task} project={project ?? null} onChanged={onChanged} />;
  const where = synced.source;
  const toSend = synced.removed_at ? 0 : synced.edited.length;

  const choose = (field: SyncedField, keep: "theirs" | "mine") =>
    void tasksApi.resolve(task.id, field, keep).then(onChanged, (e: Error) => toast(e.message, "error"));
  const unlink = async () => {
    const ok = await confirm({
      title: `Stop following ${where}?`,
      body: `This task stays, as your own, and stops changing when ${where} does. Nothing in ${where} changes.`,
      confirmLabel: "Unlink",
    });
    if (ok) void tasksApi.unlink(task.id).then(onChanged, (e: Error) => toast(e.message, "error"));
  };

  const link = synced.url ? (
    <a href={synced.url} target="_blank" rel="noreferrer" className="inline-flex min-w-0 items-center gap-1 font-medium text-ink hover:text-forest">
      <span className="truncate">{synced.title ?? `Open in ${where}`}</span>
      <ExternalIcon size={13} className="shrink-0 text-ink-faint" />
    </a>
  ) : (
    <span className="truncate font-medium text-ink">{synced.title ?? where}</span>
  );

  return (
    <>
      <section className="mt-6 animate-enter" aria-label={`Linked to ${where}`}>
        <div className="inset-surface flex flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-3 text-hint text-ink-soft">
          <NetworkIcon size={16} className="shrink-0 text-forest" />
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5">
            <span>Linked to {where}:</span>
            {link}
          </span>
          <span data-tip={formatDate(synced.synced_at)}>Checked {relativeTime(synced.synced_at)}</span>
          <button className="btn btn-sm btn-ghost -my-1" onClick={() => void unlink()}>
            Unlink
          </button>
          <div className="flex basis-full flex-wrap items-center gap-x-3 gap-y-2">
            <p className="min-w-0 flex-1 basis-64">
              {task.sharing.length
                ? `${task.sharing[0].title}: ${synced.edited.map((f) => FIELD_LABEL[f]).join(", ") || "your changes"}.`
                : synced.edited.length
                  ? `Follows ${where} for what you haven't changed. Changed here only: ${synced.edited.map((f) => FIELD_LABEL[f]).join(", ")}.`
                  : `Follows ${where}: when it changes there, it changes here.`}
            </p>
            {(toSend > 0 || task.sharing.length > 0) && (
              <SendRow task={task} label={`Send ${toSend === 1 ? "it" : `these ${toSend}`} to ${where}`} onChanged={onChanged} />
            )}
          </div>
        </div>

        {synced.removed_at && (
          <div role="status" className="mt-3 rounded-lg border border-line bg-surface-subtle px-4 py-3 text-label">
            <div className="font-semibold">Removed in {where}</div>
            <p className="mt-0.5 text-ui text-ink-soft">
              It's no longer in what Traverse reads from {where}: deleted, archived, or moved to a project Traverse doesn't read. Your copy stays as
              it is. If it comes back, this goes away.
            </p>
          </div>
        )}

        {synced.conflicts.length > 0 && (
          <div role="status" className="mt-3 overflow-hidden rounded-lg border border-sun/30 bg-sun-soft/60">
            <div className="flex items-start gap-2.5 px-4 pt-3">
              <AlertIcon size={16} className="mt-0.5 shrink-0 text-sun-deep" />
              <div>
                <div className="text-label font-semibold text-sun-deep">Changed in {where}</div>
                <p className="mt-0.5 text-ui text-ink-soft">
                  You changed {synced.conflicts.length === 1 ? "this" : "these"} here too, so Traverse kept yours. Choose which to keep.
                </p>
              </div>
            </div>
            <ul className="mt-2 divide-y divide-sun/20 border-t border-sun/20">
              {synced.conflicts.map((c) => (
                <li key={c.field} className="grid gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-center">
                  <span className="text-label font-medium">{c.label}</span>
                  <span className="min-w-0 text-ui">
                    <span className="block text-meta text-ink-soft">Here</span>
                    <span className="break-words">{shown(c.field, task, meta)}</span>
                  </span>
                  <span className="min-w-0 text-ui">
                    <span className="block text-meta text-ink-soft">{where}</span>
                    <span className="break-words">{shown(c.field, c.theirs, meta)}</span>
                  </span>
                  <span className="flex gap-2">
                    <button className="btn btn-sm btn-soft" onClick={() => choose(c.field, "theirs")}>
                      Use {where}'s
                    </button>
                    <button className="btn btn-sm btn-ghost" onClick={() => choose(c.field, "mine")}>
                      Keep mine
                    </button>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
      {dialog}
    </>
  );
}

/** A task that isn't linked, in a project that is: it can be sent to be made there. */
function NotSentYet({ task, project, onChanged }: { task: TaskDetail; project: ProjectDetail | null; onChanged: () => void }) {
  const { app } = useShell();
  const target = project?.synced_with[0];
  if (!project || !target || task.parent_id) return null;
  const where = app.modules.find((m) => m.id === target.module)?.name ?? target.module;
  return (
    <section className="mt-6 animate-enter" aria-label={`Not in ${where} yet`}>
      <div className="inset-surface flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-hint text-ink-soft">
        <NetworkIcon size={16} className="shrink-0 text-ink-faint" />
        <p className="min-w-0 flex-1 basis-64">
          {task.sharing.length
            ? `${task.sharing[0].title}.`
            : `Only in Traverse so far. ${project.name} is linked to ${target.title} in ${where}, so you can add it there.`}
        </p>
        <SendRow task={task} label={`Send to ${where}`} onChanged={onChanged} />
      </div>
    </section>
  );
}
