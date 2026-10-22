// A project as a board (#/tasks/projects/<id>/board): a column per status, cards you drag between columns (which
// changes their status) and within one (your order, across milestones). Dropped tasks stay off the board; the list
// view keeps them. Keyboard: arrows move between cards, Alt + ← → moves a card to the next column, Alt + ↑ ↓ moves
// it up or down, Return opens it.
import type { CSSProperties, KeyboardEvent } from "react";
import { Avatar } from "@core/components/blocks";
import { FlagIcon } from "@core/components/icons";
import { StatusChip } from "@core/components/ui";
import { navigate } from "@core/router";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Meta, ProjectDetail, Status, Task } from "./api";
import { dueLabel } from "./dates";
import { afterForStep, dragProps, useDragging, useDropZone } from "./dnd";

const COLUMNS: Status[] = ["todo", "doing", "waiting", "done"];
const isMine = (t: Task) => (!t.assignee_ref && !t.assignee_name) || t.assignee_ref === "core:me";

function Card({ task, milestone, drag, style, onKeyDown }: {
  task: Task;
  milestone: string | null;
  drag: ReturnType<typeof dragProps>;
  style?: CSSProperties;
  onKeyDown: (e: KeyboardEvent<HTMLDivElement>) => void;
}) {
  const due = task.done ? null : dueLabel(task.due_on);
  const someone = !isMine(task) ? task.assignee_name || "Someone" : null;
  return (
    <div
      role="listitem"
      tabIndex={0}
      data-board-card=""
      data-status={task.status}
      aria-label={task.text}
      {...drag}
      style={{ ...(drag.style ?? {}), ...(style ?? {}) }}
      onKeyDown={onKeyDown}
      onClick={() => navigate(`tasks/t/${task.id}`)}
      className="cursor-pointer rounded-lg border border-line bg-surface p-3.5 shadow-sm transition-[transform,box-shadow] duration-150 hover:-translate-y-px hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-forest/30 active:shadow-lg"
    >
      <div className={`text-label leading-snug ${task.done ? "text-ink-soft line-through decoration-ink-faint" : ""}`}>{task.text}</div>
      {milestone && <div className="mt-1 truncate text-hint text-ink-soft">{milestone}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-1.5 empty:hidden">
        {task.blocked && !task.done && <StatusChip tone="trail" label="Blocked" />}
        {task.priority === 4 && !task.done && <StatusChip tone="sun" label="Urgent" />}
        {task.priority === 3 && !task.done && (
          <span className="inline-flex items-center gap-1 text-meta text-ink">
            <FlagIcon size={14} /> High
          </span>
        )}
        {task.subtask_count ? (
          <span className="text-meta tabular-nums text-ink-soft">
            {task.subtasks_done ?? 0} of {task.subtask_count}
          </span>
        ) : null}
        {due && (
          <span
            data-tip={due.full}
            className={`text-meta tabular-nums ${due.tone === "late" ? "font-medium text-trail-deep" : due.tone === "soon" ? "font-medium text-sun-deep" : "text-ink-soft"}`}
          >
            {due.text}
          </span>
        )}
        {someone && (
          <span className="ml-auto" data-tip={someone}>
            <Avatar name={someone} size={22} />
          </span>
        )}
      </div>
    </div>
  );
}

function Column({ status, label, tasks, milestones, onMove, onKey }: {
  status: Status;
  label: string;
  tasks: Task[];
  milestones: Map<string, string>;
  onMove: (id: string, afterId: string | null, status: Status) => void;
  onKey: (e: KeyboardEvent<HTMLDivElement>, task: Task) => void;
}) {
  const ids = tasks.map((t) => t.id);
  const dragging = useDragging();
  const { zone, at, lineFor } = useDropZone(ids, (id, afterId) => onMove(id, afterId, status), "cards");
  return (
    <section
      aria-label={label}
      className="inset-surface flex w-[16.5rem] shrink-0 flex-col rounded-xl p-2.5 lg:w-auto lg:min-w-0 lg:flex-1"
    >
      <h2 className="eyebrow mb-2.5 flex items-baseline justify-between px-1.5 pt-0.5">
        {label}
        <span className="font-normal tabular-nums text-ink-faint">{tasks.length || ""}</span>
      </h2>
      <div role="list" {...zone} className="flex min-h-[5rem] flex-1 flex-col gap-2 pb-1">
        {tasks.map((t, i) => (
          <Card
            key={t.id}
            task={t}
            milestone={t.milestone_id ? milestones.get(t.milestone_id) ?? null : null}
            drag={dragProps(t.id, dragging)}
            style={lineFor(i)}
            onKeyDown={(e) => onKey(e, t)}
          />
        ))}
        {tasks.length === 0 && (
          <p
            className={`grid flex-1 place-items-center rounded-lg border border-dashed text-hint text-ink-faint transition-colors ${
              at !== null ? "border-forest/60 text-forest-deep" : dragging ? "border-line-strong" : "border-transparent"
            }`}
          >
            {dragging ? "Drop here" : "Nothing here"}
          </p>
        )}
      </div>
    </section>
  );
}

export function Board({ project, tasks, meta, onChanged }: { project: ProjectDetail; tasks: Task[]; meta: Meta | null; onChanged: () => void }) {
  const { toast } = useShell();
  const milestones = new Map(project.milestones.map((m) => [m.id, m.name]));
  const byStatus = new Map(COLUMNS.map((s) => [s, tasks.filter((t) => t.status === s).sort((a, b) => a.sort - b.sort)]));
  const label = (s: Status) => meta?.statuses.find((x) => x.value === s)?.label ?? s;

  const focusCard = (id: string) =>
    window.setTimeout(() => document.querySelector<HTMLElement>(`[data-board-card][data-drag-id="${id}"]`)?.focus(), 350);

  const move = (id: string, after_id: string | null, status: Status) => {
    const task = tasks.find((t) => t.id === id);
    if (!task) return;
    void tasksApi
      .move(id, { project_id: project.id, milestone_id: task.milestone_id, after_id, within: "project", status })
      .then(onChanged, (e: Error) => toast(e.message, "error"));
  };

  const onKey = (e: KeyboardEvent<HTMLDivElement>, t: Task) => {
    const col = COLUMNS.indexOf(t.status);
    const list = byStatus.get(t.status) ?? [];
    const i = list.findIndex((x) => x.id === t.id);
    if (e.key === "Enter") {
      e.preventDefault();
      navigate(`tasks/t/${t.id}`);
      return;
    }
    if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    if (e.altKey) {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        const to = COLUMNS[col + (e.key === "ArrowRight" ? 1 : -1)];
        if (!to) return;
        const there = byStatus.get(to) ?? [];
        move(t.id, there.length ? there[there.length - 1].id : null, to);
      } else {
        const after = afterForStep(list.map((x) => x.id), t.id, e.key === "ArrowDown" ? 1 : -1);
        if (after === undefined) return;
        move(t.id, after, t.status);
      }
      focusCard(t.id);
      return;
    }
    // Plain arrows move focus: up and down within the column, left and right to the same place in the next one.
    let target: Task | undefined;
    if (e.key === "ArrowUp" || e.key === "ArrowDown") target = list[i + (e.key === "ArrowDown" ? 1 : -1)];
    else {
      for (let c = col + (e.key === "ArrowRight" ? 1 : -1); c >= 0 && c < COLUMNS.length && !target; c += e.key === "ArrowRight" ? 1 : -1) {
        const there = byStatus.get(COLUMNS[c]) ?? [];
        target = there[Math.min(i, there.length - 1)];
      }
    }
    if (target) document.querySelector<HTMLElement>(`[data-board-card][data-drag-id="${target.id}"]`)?.focus();
  };

  return (
    <>
      <p className="mb-3 px-1 text-meta text-ink-faint">
        Drag a card to change its status or its place. Keyboard: arrows to move around, Alt + arrows to move a card.
      </p>
      <div className="-mx-1 flex gap-3 overflow-x-auto px-1 pb-3">
        {COLUMNS.map((s) => (
          <Column key={s} status={s} label={label(s)} tasks={byStatus.get(s) ?? []} milestones={milestones} onMove={move} onKey={onKey} />
        ))}
      </div>
    </>
  );
}
