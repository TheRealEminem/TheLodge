// One task in a list, used everywhere a task is listed: the round check, the title, a meta line, chips, who's on
// it, and when it's due. A list of them is keyboard-driven: ↑ ↓ move between rows, Space ticks, Return opens.
import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, ReactNode } from "react";
import { Avatar } from "@core/components/blocks";
import { CheckIcon, FlagIcon } from "@core/components/icons";
import { StatusChip } from "@core/components/ui";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Meta, Task } from "./api";
import { dueLabel } from "./dates";
import { afterForStep, dragProps, useDragging, useDropZone } from "./dnd";

const isMine = (t: Task) => (!t.assignee_ref && !t.assignee_name) || t.assignee_ref === "core:me";

export function Check({ done, onToggle, tabIndex }: { done: boolean; onToggle: () => void; tabIndex?: number }) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={done}
      aria-label={done ? "Mark as not done" : "Mark as done"}
      tabIndex={tabIndex}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={`mt-px flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full border transition-colors duration-150 ${
        done ? "border-forest bg-forest text-on-accent" : "border-line-strong bg-surface hover:border-forest/60"
      }`}
    >
      {done && <CheckIcon size={12} strokeWidth={3} className="animate-check-pop" />}
    </button>
  );
}

function Due({ task }: { task: Task }) {
  const due = task.done ? null : dueLabel(task.due_on);
  if (!due) return null;
  const tone = due.tone === "late" ? "font-medium text-trail-deep" : due.tone === "soon" ? "font-medium text-sun-deep" : "text-ink-soft";
  return (
    <span className={`whitespace-nowrap text-meta tabular-nums ${tone}`} data-tip={due.full}>
      {due.text}
    </span>
  );
}

export function TaskRow({
  task,
  meta,
  projectName,
  done,
  onToggle,
  tabIndex = -1,
  onKeyDown,
  extra,
  drag,
  style,
}: {
  task: Task;
  meta: Meta | null;
  projectName?: string | null;
  done: boolean;
  onToggle: () => void;
  tabIndex?: number;
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
  /** Something the list adds at the end of the row, like "Move to…". */
  extra?: ReactNode;
  /** When the list lets you drag its tasks: what dragProps() gives. */
  drag?: ReturnType<typeof dragProps>;
  style?: CSSProperties;
}) {
  const status = task.status !== "todo" && task.status !== "done" ? meta?.statuses.find((s) => s.value === task.status) : null;
  const detail = [
    projectName,
    task.came_from ? `From ${task.came_from.title}` : null,
    task.synced ? `In ${task.synced.source}` : null,
    task.subtask_count ? `${task.subtasks_done ?? 0} of ${task.subtask_count} subtasks` : null,
  ].filter(Boolean);
  const someone = !isMine(task) ? task.assignee_name || "Someone" : null;
  const chips = (
    <>
      {status && <StatusChip tone={status.tone} label={status.label} />}
      {task.blocked && !done && <StatusChip tone="trail" label="Blocked" />}
      {task.synced?.conflicts.length ? <StatusChip tone="sun" label={`Changed in ${task.synced.source}`} /> : null}
      {task.synced?.removed_at && <StatusChip tone="neutral" label={`Removed in ${task.synced.source}`} />}
      <ToSend task={task} />
      {task.priority === 4 && !done && <StatusChip tone="sun" label="Urgent" />}
      {task.priority === 3 && !done && (
        <span className="inline-flex items-center gap-1 text-meta text-ink">
          <FlagIcon size={14} /> High
        </span>
      )}
      {someone && (
        <span data-tip={someone}>
          <Avatar name={someone} size={24} />
        </span>
      )}
      <Due task={{ ...task, done }} />
    </>
  );
  return (
    <div
      role="listitem"
      data-task-row=""
      {...(drag ?? {})}
      style={{ ...(drag?.style ?? {}), ...(style ?? {}) }}
      tabIndex={tabIndex}
      aria-label={`${task.text}${done ? ", done" : ""}`}
      onKeyDown={onKeyDown}
      onClick={() => navigate(`tasks/t/${task.id}`)}
      className="group flex cursor-pointer items-start gap-3 px-5 py-3 transition-colors hover:bg-forest/[.05] focus-visible:bg-forest/[.05] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-forest/30"
    >
      <Check done={done} onToggle={onToggle} tabIndex={-1} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-3">
          <a
            href={`#/tasks/t/${task.id}`}
            tabIndex={-1}
            onClick={(e) => e.stopPropagation()}
            className={`min-w-0 flex-1 text-label leading-snug transition-colors ${done ? "text-ink-soft line-through decoration-ink-faint" : ""}`}
          >
            {task.text}
          </a>
          <div className="hidden shrink-0 items-center gap-2 sm:flex">{chips}</div>
        </div>
        {detail.length > 0 && <div className="mt-0.5 truncate text-hint text-ink-soft">{detail.join(" · ")}</div>}
        <div className="mt-1.5 flex flex-wrap items-center gap-2 empty:hidden sm:hidden">{chips}</div>
        {extra && (
          <div className="mt-2" onClick={(e) => e.stopPropagation()}>
            {extra}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Tasks as a keyboard-driven list. Ticking one shows it done for a moment before it leaves an open list (tick again
 * to take it back); the change is saved when it leaves, or at once if you go elsewhere.
 */
export function TaskList({
  tasks,
  meta,
  projects,
  onChanged,
  extra,
  label,
  onMove,
}: {
  tasks: Task[];
  meta: Meta | null;
  projects?: Map<string, string>;
  onChanged: () => void;
  extra?: (t: Task) => ReactNode;
  label: string;
  /** Lets you drag tasks into and around this list (and move them with Alt + ↑ ↓): where a task should go. */
  onMove?: (id: string, afterId: string | null) => void;
}) {
  const { toast } = useShell();
  const [focus, setFocus] = useState(0);
  const [settling, setSettling] = useState<Map<string, boolean>>(new Map());
  const timers = useRef(new Map<string, { timer: number; done: boolean }>());

  const save = (id: string, done: boolean) =>
    tasksApi.setDone(id, done).then(
      () => onChanged(),
      (e: Error) => toast(e.message, "error"),
    );

  // Going elsewhere saves whatever is still settling.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const [id, p] of pending) {
        window.clearTimeout(p.timer);
        void tasksApi.setDone(id, p.done).catch(() => undefined);
      }
      pending.clear();
    };
  }, []);

  const toggle = (t: Task) => {
    const now = settling.get(t.id) ?? t.done;
    const next = !now;
    const pending = timers.current.get(t.id);
    if (pending) {
      window.clearTimeout(pending.timer);
      timers.current.delete(t.id);
      setSettling((s) => new Map(s).set(t.id, next));
      if (next === t.done) {
        setSettling((s) => {
          const out = new Map(s);
          out.delete(t.id);
          return out;
        });
        return; // ticked and unticked again: nothing to save
      }
    }
    setSettling((s) => new Map(s).set(t.id, next));
    const timer = window.setTimeout(() => {
      timers.current.delete(t.id);
      void save(t.id, next).finally(() =>
        setSettling((s) => {
          const out = new Map(s);
          out.delete(t.id);
          return out;
        }),
      );
    }, 900);
    timers.current.set(t.id, { timer, done: next });
  };

  const ids = tasks.map((t) => t.id);
  const dragging = useDragging();
  const { zone, lineFor } = useDropZone(ids, (id, afterId) => onMove?.(id, afterId));

  const keys = (i: number, t: Task) => (e: KeyboardEvent<HTMLDivElement>) => {
    if (onMove && e.altKey && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
      // Alt + ↑ ↓ moves the task itself; focus follows it once the list has reloaded.
      e.preventDefault();
      const after = afterForStep(ids, t.id, e.key === "ArrowDown" ? 1 : -1);
      if (after !== undefined) {
        onMove(t.id, after);
        window.setTimeout(() => document.querySelector<HTMLElement>(`[data-task-row][data-drag-id="${t.id}"]`)?.focus(), 350);
      }
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      // Across every list on the page (Late, Today…), in the order they're shown.
      e.preventDefault();
      const all = Array.from(document.querySelectorAll<HTMLElement>("[data-task-row]"));
      const next = all[all.indexOf(e.currentTarget) + (e.key === "ArrowDown" ? 1 : -1)];
      if (next) next.focus();
      else setFocus(i);
    } else if (e.key === " ") {
      e.preventDefault();
      toggle(t);
    } else if (e.key === "Enter") {
      e.preventDefault();
      navigate(`tasks/t/${t.id}`);
    }
  };

  if (onMove && tasks.length === 0) {
    // An empty list still takes a dropped task, and says so while one is being dragged.
    return (
      <div
        {...zone}
        role="list"
        aria-label={label}
        className={`rounded-lg border border-dashed px-4 text-center text-hint text-ink-soft transition-[padding,border-color] ${
          dragging ? "border-forest/50 py-4" : "border-transparent py-0"
        }`}
      >
        {dragging ? "Drop a task here" : null}
      </div>
    );
  }
  if (tasks.length === 0) return null;

  return (
    <div role="list" aria-label={label} className="panel divide-y divide-line overflow-hidden" {...(onMove ? zone : {})}>
      {tasks.map((t, i) => (
        <TaskRow
          key={t.id}
          task={t}
          meta={meta}
          projectName={t.project_id ? projects?.get(t.project_id) : null}
          done={settling.get(t.id) ?? t.done}
          onToggle={() => toggle(t)}
          tabIndex={i === Math.min(focus, tasks.length - 1) ? 0 : -1}
          onKeyDown={keys(i, t)}
          extra={extra?.(t)}
          drag={onMove ? dragProps(t.id, dragging) : undefined}
          style={onMove ? lineFor(i) : undefined}
        />
      ))}
    </div>
  );
}

/** A linked task's changes not sent yet: how many, or that they wait for you to send them. */
export function ToSend({ task }: { task: Task }) {
  if (task.sharing?.length) return <StatusChip tone="sun" label="Waiting to send" />;
  const n = task.synced && !task.synced.removed_at ? task.synced.edited.length : 0;
  return n ? <StatusChip tone="neutral" label={`${n} ${n === 1 ? "change" : "changes"} to send`} /> : null;
}
