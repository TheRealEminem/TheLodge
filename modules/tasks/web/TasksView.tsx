import { useState } from "react";
import { CheckIcon, CheckSquareIcon, PlusIcon, TrashIcon } from "@core/components/icons";
import { ContourBadge } from "@core/components/illustrations";
import { Collapse, PageHeader, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Task } from "./api";

function TaskRow({ task, onToggle, onDelete }: { task: Task; onToggle: () => void; onDelete?: () => void }) {
  return (
    <div className="group flex items-start gap-3 py-3">
      <button
        role="checkbox"
        aria-checked={task.done}
        aria-label={task.done ? "Mark as not done" : "Mark as done"}
        onClick={onToggle}
        className={`mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-xs border transition-colors duration-150 ${
          task.done ? "border-forest bg-forest text-on-accent" : "border-line-strong bg-surface hover:border-forest/60"
        }`}
      >
        {task.done && <CheckIcon size={14} strokeWidth={2.6} className="animate-check-pop" />}
      </button>
      <div className="min-w-0 flex-1">
        <div className={`text-label leading-snug transition-colors ${task.done ? "text-ink-soft line-through decoration-ink-faint" : ""}`}>{task.text}</div>
        {task.source && (
          <a href={task.source.href} className="mt-0.5 inline-block text-meta text-ink-soft hover:text-forest">
            From {task.source.title}
          </a>
        )}
      </div>
      {onDelete && (
        <button className="icon-btn h-7 w-7 opacity-0 hover:!bg-trail-soft hover:!text-trail-deep focus-visible:opacity-100 group-hover:opacity-100" aria-label="Delete task" onClick={onDelete}>
          <TrashIcon size={16} />
        </button>
      )}
    </div>
  );
}

export default function TasksView() {
  const { toast } = useShell();
  const { data: tasks, reload } = useLive(tasksApi.list);
  const [text, setText] = useState("");
  const [showDone, setShowDone] = useState(false);
  const open = tasks?.filter((t) => !t.done) ?? [];
  const done = tasks?.filter((t) => t.done) ?? [];
  const act = (fn: () => Promise<unknown>) => fn().then(reload, (e: Error) => toast(e.message, "error"));

  return (
    <>
      <PageHeader title="Tasks" subtitle="Action items from everywhere, and anything you add." />
      <form
        className="mb-6 flex animate-enter gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!text.trim()) return;
          void act(() => tasksApi.create(text.trim()));
          setText("");
        }}
      >
        <input className="field h-10 flex-1" placeholder="Add a task" value={text} onChange={(e) => setText(e.target.value)} aria-label="New task" />
        <button className="btn btn-md btn-soft" disabled={!text.trim()}>
          <PlusIcon size={16} />
          Add
        </button>
      </form>

      {!tasks && <Skeleton className="h-32 w-full rounded-xl" />}
      {tasks && open.length === 0 && (
        <div className="inset-surface animate-enter px-4 py-10 text-center">
          <ContourBadge>
            <CheckSquareIcon size={20} />
          </ContourBadge>
          <p className="mt-3 font-medium">Nothing to do</p>
          <p className="mx-auto mt-1 max-w-sm text-label leading-relaxed text-ink-soft">Action items from your notes will gather here.</p>
        </div>
      )}
      {open.length > 0 && (
        <div className="panel animate-enter divide-y divide-line px-5">
          {open.map((t) => (
            <TaskRow key={t.id} task={t} onToggle={() => void act(() => tasksApi.setDone(t.id, true))} onDelete={() => void act(() => tasksApi.remove(t.id))} />
          ))}
        </div>
      )}
      {done.length > 0 && (
        <div className="mt-8">
          <button className="btn btn-sm btn-ghost -ml-3" onClick={() => setShowDone(!showDone)} aria-expanded={showDone}>
            {showDone ? "Hide" : "Show"} {done.length} done
          </button>
          <Collapse open={showDone}>
            <div className="panel mt-2 divide-y divide-line px-5">
              {done.map((t) => (
                <TaskRow key={t.id} task={t} onToggle={() => void act(() => tasksApi.setDone(t.id, false))} />
              ))}
            </div>
          </Collapse>
        </div>
      )}
    </>
  );
}

export function TasksHome() {
  const { data: tasks, reload } = useLive(tasksApi.list);
  const open = tasks?.filter((t) => !t.done) ?? [];
  return (
    <>
      <div className="flex items-center gap-3">
        <span className="well well-forest">
          <CheckSquareIcon size={16} />
        </span>
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.01em]">Tasks</h2>
          <p className="text-hint text-ink-soft">{tasks ? (open.length ? `${open.length} open` : "All done") : "…"}</p>
        </div>
      </div>
      <div className="mt-1 divide-y divide-line">
        {open.slice(0, 3).map((t) => (
          <TaskRow key={t.id} task={t} onToggle={() => void tasksApi.setDone(t.id, true).then(reload)} />
        ))}
      </div>
      <a href="#/tasks" className="btn btn-sm btn-ghost -ml-3 mt-2">
        All tasks
      </a>
    </>
  );
}
