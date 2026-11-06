// A task, as its own page (#/tasks/t/<id>), so any link can open it: from a meeting, search, or the Mac menu.
// Every field saves as you leave it.
import { useState } from "react";
import type { ReactNode } from "react";
import { LinkedList, PersonPicker } from "@core/components/blocks";
import type { PersonChoice } from "@core/api";
import { BackIcon, ChatIcon, SparkleIcon, TrashIcon } from "@core/components/icons";
import { ControlRow, Segmented, Select, Skeleton, StatusChip, useConfirm } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate } from "@core/router";
import { useSettings, useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Status, Task, TaskDetail } from "./api";
import { formatMinutes, parseMinutes } from "./dates";
import { BreakDownButton, BreakdownPanel, OfferUpdate, whoWrote } from "./Drafts";
import { Field } from "./Field";
import { SyncedPanel } from "./Synced";
import { Check, TaskList } from "./TaskRow";

function Block({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="mt-10 animate-enter">
      <div className="mb-2 flex items-center justify-between gap-3 px-1">
        <h2 className="eyebrow">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A stored ref and name as the picker shows them: you by your name (or "You"), someone else by theirs. */
export function personChoice(ref: string | null, name: string | null, yourName: string): PersonChoice | null {
  if (ref === "core:me") return { ref, name: yourName || "You" };
  if (ref || name) return { ref, name: name || "Someone" };
  return null;
}

/** What the picker chose, as the task's fields: your own name isn't stored (you're "core:me" wherever you're named). */
function assigneeFields(who: PersonChoice | null): Partial<Task> {
  if (!who) return { assignee_ref: null, assignee_name: null };
  return { assignee_ref: who.ref, assignee_name: who.ref === "core:me" ? null : who.name };
}

export default function TaskPage({ params }: RouteProps) {
  const id = params.id;
  const { toast } = useShell();
  const yourName = (useSettings().get<string>("core.your_name") ?? "").trim();
  const [confirm, dialog] = useConfirm();
  const { data: task, reload, error } = useLive<TaskDetail>(() => tasksApi.get(id), [id]);
  const { data: meta } = useLive(tasksApi.meta);
  const { data: projectList } = useLive(tasksApi.projects);
  const { data: project } = useLive(() => (task?.project_id ? tasksApi.project(task.project_id) : Promise.resolve(null)), [task?.project_id]);
  const { data: openTasks } = useLive(() => tasksApi.list({ status: "open", parent: "any" }));
  const { data: breakdown, reload: reloadBreakdown } = useLive(() => tasksApi.breakdown(id), [id]);
  const [subtask, setSubtask] = useState("");
  const [comment, setComment] = useState("");
  const [notes, setNotes] = useState<string | null>(null);

  const save = (changes: Partial<Task>) =>
    tasksApi.update(id, changes).then(
      () => reload(),
      (e: Error) => toast(e.message, "error"),
    );

  if (error && (!task || /not found/i.test(error))) {
    return (
      <div className="animate-enter">
        <a href="#/tasks" className="btn btn-sm btn-ghost -ml-3 mb-4">
          <BackIcon size={16} /> My tasks
        </a>
        <p className="text-body text-ink-soft">That task isn't here any more. It may have been deleted.</p>
      </div>
    );
  }
  if (!task) return <Skeleton className="h-64 w-full rounded-xl" />;

  const status = meta?.statuses.find((s) => s.value === task.status);
  const proposedBy = typeof task.attributes?.written_by === "string" ? task.attributes.written_by : null;
  const linked = task.synced && !task.synced.removed_at ? task.synced.source : null;
  const changed = () => void Promise.all([reload(), reloadBreakdown()]);
  const blockable = (openTasks ?? []).filter((t) => t.id !== task.id && !task.blocked_by.some((b) => b.id === t.id));
  const remove = async () => {
    const ok = await confirm({
      title: "Delete this task?",
      body: task.subtasks.length
        ? `"${task.text}" and its ${task.subtasks.length} subtasks will be deleted. This can't be undone.`
        : `"${task.text}" will be deleted. This can't be undone; mark it Dropped instead to keep it.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await tasksApi.remove(task.id).catch((e: Error) => toast(e.message, "error"));
    navigate(task.parent_id ? `tasks/t/${task.parent_id}` : "tasks");
  };

  return (
    <>
      <div className="mb-4 flex animate-enter items-center justify-between gap-3">
        <a href={task.parent_id ? `#/tasks/t/${task.parent_id}` : "#/tasks"} className="btn btn-sm btn-ghost -ml-3">
          <BackIcon size={16} /> {task.parent_id ? "Back to the main task" : "My tasks"}
        </a>
        <button className="btn btn-sm btn-danger-ghost" onClick={() => void remove()}>
          <TrashIcon size={16} /> Delete
        </button>
      </div>

      <header className="animate-enter">
        <div className="flex items-start gap-3">
          <div className="mt-3">
            <Check done={task.done} onToggle={() => void save({ done: !task.done })} />
          </div>
          <Field
            label="Task"
            value={task.text}
            onSave={(v) => (v.trim() ? void save({ text: v.trim() }) : toast("A task needs some text", "error"))}
            bare
            className="page-title -mx-2 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-0.5 outline-none transition-colors hover:border-line focus:border-line-strong focus:bg-surface"
          />
        </div>
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-hint text-ink-soft">
          {status && <StatusChip tone={status.tone} label={status.label} />}
          {task.blocked && <StatusChip tone="trail" label="Blocked" />}
          {task.project_id && projectList && (
            <a href={`#/tasks/projects/${task.project_id}`} className="hover:text-forest">
              {projectList.find((p) => p.id === task.project_id)?.name}
            </a>
          )}
          {task.came_from && (
            <a href={task.came_from.href} className="hover:text-forest">
              From {task.came_from.title}
            </a>
          )}
          {proposedBy && (
            <span className="inline-flex items-center gap-1">
              <SparkleIcon size={13} className="text-ink-faint" />
              Proposed by {proposedBy}
              {task.attributes?.edited ? ", edited by you" : ""}
            </span>
          )}
          <span data-tip={formatDate(task.created_at)}>Added {relativeTime(task.created_at)}</span>
          {task.completed_at && <span>Done {relativeTime(task.completed_at)}</span>}
        </p>
      </header>

      <SyncedPanel task={task} meta={meta ?? null} project={project ?? null} onChanged={() => void reload()} />

      <section className="panel mt-8 animate-enter divide-y divide-line px-5">
        <ControlRow label="Status">
          <Select
            label="Status"
            size="sm"
            className="w-full sm:w-56"
            value={task.status}
            options={(meta?.statuses ?? []).map((s) => ({ value: s.value, label: s.label }))}
            onChange={(v) => void save({ status: v as Status })}
          />
        </ControlRow>
        <ControlRow label="Project" hint={task.parent_id ? "A subtask lives where its main task does." : undefined}>
          <Select
            label="Project"
            size="sm"
            className="w-full sm:w-56"
            disabled={!!task.parent_id}
            value={task.project_id ?? ""}
            options={[{ value: "", label: "No project" }, ...(projectList ?? []).map((p) => ({ value: p.id, label: p.name }))]}
            onChange={(v) => void save({ project_id: v || null })}
          />
        </ControlRow>
        {project && project.milestones.length > 0 && (
          <ControlRow label="Milestone">
            <Select
              label="Milestone"
              size="sm"
              className="w-full sm:w-56"
              disabled={!!task.parent_id}
              value={task.milestone_id ?? ""}
              options={[{ value: "", label: "No milestone" }, ...project.milestones.map((m) => ({ value: m.id, label: m.name }))]}
              onChange={(v) => void save({ milestone_id: v || null })}
            />
          </ControlRow>
        )}
        <ControlRow label="Assignee" hint="No one named: it's yours. Someone else: it's theirs, and shows under Waiting on others.">
          <PersonPicker
            label="Assignee"
            className="w-full sm:w-56"
            placeholder="You"
            noneLabel="No one named (yours)"
            value={personChoice(task.assignee_ref, task.assignee_name, yourName)}
            onChange={(who) => void save(assigneeFields(who))}
          />
        </ControlRow>
        <ControlRow label="Due">
          <Field type="date" label="Due" className="w-full sm:w-56" value={task.due_on ?? ""} onSave={(v) => void save({ due_on: v || null })} />
        </ControlRow>
        <ControlRow label="Start">
          <Field type="date" label="Start" className="w-full sm:w-56" value={task.start_on ?? ""} onSave={(v) => void save({ start_on: v || null })} />
        </ControlRow>
        <ControlRow label="Priority" wrap>
          <Segmented<string>
            label="Priority"
            size="sm"
            value={String(task.priority)}
            onChange={(v) => void save({ priority: Number(v) })}
            options={(meta?.priorities ?? []).map((p) => ({ id: String(p.value), label: p.label }))}
          />
        </ControlRow>
        <ControlRow label="Estimate" hint="Like 45, 2h or 1h30.">
          <Field
            label="Estimate"
            className="w-full sm:w-56"
            placeholder="None"
            value={formatMinutes(task.estimate_min)}
            onSave={(v) => {
              const min = parseMinutes(v);
              if (min === undefined) toast("Write an estimate like 45, 2h or 1h30", "error");
              else void save({ estimate_min: min });
            }}
          />
        </ControlRow>
      </section>

      <Block title="Notes">
        <textarea
          aria-label="Notes"
          className="field min-h-[7rem] w-full resize-y py-2.5 leading-relaxed"
          placeholder="Anything worth remembering about it. Markdown works."
          value={notes ?? task.notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => {
            if (notes !== null && notes !== task.notes) void save({ notes });
            setNotes(null);
          }}
        />
      </Block>

      <Block
        title={`Subtasks${task.subtasks.length ? ` · ${task.subtasks.filter((s) => s.done).length} of ${task.subtasks.length} done` : ""}`}
        action={<BreakDownButton taskId={task.id} draft={breakdown} onChanged={changed} />}
      >
        <BreakdownPanel draft={breakdown} onChanged={changed} />
        {task.subtasks.length > 0 && (
          <div className="mb-2">
            <TaskList tasks={task.subtasks} meta={meta ?? null} onChanged={() => void reload()} label="Subtasks" />
          </div>
        )}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!subtask.trim()) return;
            void tasksApi.create({ text: subtask.trim(), parent_id: task.id }).then(() => {
              setSubtask("");
              void reload();
            }, (err: Error) => toast(err.message, "error"));
          }}
        >
          <input className="field h-9 flex-1" placeholder="Add a subtask" value={subtask} onChange={(e) => setSubtask(e.target.value)} aria-label="New subtask" />
        </form>
      </Block>

      <Block title="Waiting on">
        {task.blocked_by.length > 0 && (
          <ul className="panel mb-2 divide-y divide-line">
            {task.blocked_by.map((b) => (
              <li key={b.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <a href={`#/tasks/t/${b.id}`} className={`min-w-0 truncate text-label ${b.status === "done" ? "text-ink-soft line-through" : ""}`}>
                  {b.text}
                </a>
                <button className="btn btn-sm btn-ghost" onClick={() => void tasksApi.unblock(task.id, b.id).then(() => reload())}>
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        {blockable.length > 0 ? (
          <Select
            label="Waits on another task"
            size="sm"
            className="w-full sm:w-80"
            value=""
            options={[{ value: "", label: "Waits on another task…" }, ...blockable.slice(0, 100).map((t) => ({ value: t.id, label: t.text }))]}
            onChange={(v) => v && void tasksApi.block(task.id, v).then(() => reload(), (e: Error) => toast(e.message, "error"))}
          />
        ) : (
          !task.blocked_by.length && <p className="px-1 text-hint text-ink-soft">Nothing. Tasks it has to wait for will show here.</p>
        )}
        {task.blocks.length > 0 && (
          <p className="mt-3 px-1 text-hint text-ink-soft">
            Holding up: {task.blocks.map((b, i) => (
              <span key={b.id}>
                {i > 0 && ", "}
                <a href={`#/tasks/t/${b.id}`} className="hover:text-forest">{b.text}</a>
              </span>
            ))}
          </p>
        )}
      </Block>

      <Block title="Comments">
        {task.updates.length > 0 && (
          <ul className="mb-3 flex flex-col gap-3">
            {task.updates.map((u) => (
              <li key={u.id} className="inset-surface px-4 py-3">
                <p className="whitespace-pre-wrap text-label leading-relaxed">{u.body}</p>
                <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-ink-soft">
                  <span>
                    {whoWrote(u)} · {relativeTime(u.created_at)}
                  </span>
                  <OfferUpdate update={u} targets={linked ? [task] : []} where={linked} onTask onChanged={changed} />
                </p>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            if (!comment.trim()) return;
            void tasksApi.comment(task.id, comment.trim()).then(() => {
              setComment("");
              void reload();
            }, (err: Error) => toast(err.message, "error"));
          }}
        >
          <input className="field h-9 flex-1" placeholder="Add a comment" value={comment} onChange={(e) => setComment(e.target.value)} aria-label="New comment" />
          <button className="btn btn-sm btn-soft" disabled={!comment.trim()}>
            <ChatIcon size={16} /> Comment
          </button>
        </form>
      </Block>

      <LinkedList of={`tasks:${task.id}`} />
      {dialog}
    </>
  );
}
