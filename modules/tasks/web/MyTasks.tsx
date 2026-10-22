// My tasks: what's yours to do (nobody's, or yours), by when; and what's waiting on someone else.
// The view lives in the hash (#/tasks?when=today), so every view can be linked and survives a reload.
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Empty } from "@core/components/blocks";
import { CheckSquareIcon, ClockIcon, PlusIcon, UsersIcon } from "@core/components/icons";
import { Collapse, PageHeader, Segmented, Select, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Task } from "./api";
import { addDays, todayIso } from "./dates";
import { TaskList } from "./TaskRow";

type When = "today" | "week" | "all" | "waiting";
const WHENS: When[] = ["today", "week", "all", "waiting"];

interface Groups {
  late: Task[];
  today: Task[];
  week: Task[];
  later: Task[];
  nodate: Task[];
  unfiled: Task[];
}

function group(tasks: Task[], today: string): Groups {
  const weekEnd = addDays(today, 7);
  const g: Groups = { late: [], today: [], week: [], later: [], nodate: [], unfiled: [] };
  for (const t of tasks) {
    if (t.source === "action-item" && !t.project_id) g.unfiled.push(t);
    else if (!t.due_on) g.nodate.push(t);
    else if (t.due_on < today) g.late.push(t);
    else if (t.due_on === today) g.today.push(t);
    else if (t.due_on <= weekEnd) g.week.push(t);
    else g.later.push(t);
  }
  return g;
}

function Group({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="animate-enter">
      <h2 className="eyebrow mb-2 flex items-baseline gap-2 px-1">
        {title}
        {hint && <span className="text-meta font-normal text-ink-faint">{hint}</span>}
      </h2>
      {children}
    </section>
  );
}

/** The one field you add tasks with. "n" anywhere on the page puts you in it. */
function QuickAdd({ when, inputRef, onAdded }: { when: When; inputRef: React.RefObject<HTMLInputElement>; onAdded: () => void }) {
  const { toast } = useShell();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const placeholder = when === "today" ? "Add a task for today" : when === "waiting" ? "Add something you're waiting on" : "Add a task";
  const add = async () => {
    const value = text.trim();
    if (!value || busy) return;
    setBusy(true);
    try {
      await tasksApi.create({
        text: value,
        ...(when === "today" ? { due_on: todayIso() } : {}),
        ...(when === "waiting" ? { status: "waiting" as const } : {}),
      });
      setText("");
      onAdded();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };
  return (
    <form
      className="mb-6 flex animate-enter gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        void add();
      }}
    >
      <input
        ref={inputRef}
        id="quick-add"
        className="field h-10 flex-1"
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && (e.target as HTMLInputElement).blur()}
        aria-label="New task"
        autoComplete="off"
      />
      <button className="btn btn-md btn-soft" disabled={!text.trim() || busy}>
        <PlusIcon size={16} />
        Add
      </button>
    </form>
  );
}

export default function MyTasks() {
  const { toast } = useShell();
  const [params, setParams] = useQueryParams();
  const when = (WHENS.includes(params.get("when") as When) ? params.get("when") : "today") as When;
  const today = todayIso();
  const input = useRef<HTMLInputElement>(null);
  const [showDone, setShowDone] = useState(false);

  const { data: mine, reload: reloadMine } = useLive(() => tasksApi.list({ assignee: "mine", status: "todo,doing" }));
  const { data: waiting, reload: reloadWaiting } = useLive(() => tasksApi.list({ when: "waiting" }));
  const { data: done, reload: reloadDone } = useLive(() => tasksApi.list({ assignee: "mine", status: "done" }));
  const { data: meta } = useLive(tasksApi.meta);
  const { data: projectList } = useLive(tasksApi.projects);
  const projects = useMemo(() => new Map((projectList ?? []).map((p) => [p.id, p.name])), [projectList]);
  const reload = () => void Promise.all([reloadMine(), reloadWaiting(), reloadDone()]);

  // "n" to add; the sidebar's New task arrives as ?new=1.
  useEffect(() => {
    if (params.get("new")) {
      input.current?.focus();
      setParams({ new: null });
    }
  }, [params, setParams]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      if (e.key !== "n" || e.metaKey || e.ctrlKey || e.altKey || el.closest("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      input.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const g = useMemo(() => group(mine ?? [], today), [mine, today]);
  const counts: Record<When, number> = {
    today: g.late.length + g.today.length,
    week: g.late.length + g.today.length + g.week.length,
    all: (mine ?? []).length,
    waiting: (waiting ?? []).length,
  };
  const recentDone = (done ?? []).slice().sort((a, b) => (b.completed_at ?? "").localeCompare(a.completed_at ?? "")).slice(0, 20);
  const list = (tasks: Task[], label: string, extra?: (t: Task) => ReactNode) => (
    <TaskList tasks={tasks} meta={meta ?? null} projects={projects} onChanged={reload} extra={extra} label={label} />
  );
  const moveTo = (t: Task) =>
    projectList?.length ? (
      <Select
        label="Move to a project"
        size="sm"
        className="w-full sm:w-64"
        value=""
        options={[{ value: "", label: "Move to…" }, ...projectList.map((p) => ({ value: p.id, label: p.name }))]}
        onChange={(id) => id && void tasksApi.update(t.id, { project_id: id }).then(reload, (e: Error) => toast(e.message, "error"))}
      />
    ) : null;

  const sections: ReactNode[] = [];
  const add = (key: string, title: string, tasks: Task[], hint?: string, extra?: (t: Task) => ReactNode) => {
    if (tasks.length) sections.push(<Group key={key} title={title} hint={hint}>{list(tasks, title, extra)}</Group>);
  };
  if (when === "waiting") {
    add("waiting", "Waiting on others", waiting ?? [], "marked Waiting, or someone else's");
  } else {
    add("late", "Late", g.late);
    add("today", "Today", g.today);
    if (when !== "today") add("week", "This week", g.week);
    if (when === "all") {
      add("later", "Later", g.later);
      add("nodate", "No date", g.nodate);
      add("unfiled", "Not in a project yet", g.unfiled, "action items from your meetings", moveTo);
    }
  }
  const loading = !mine || !waiting;
  const empty: Record<When, [ReactNode, string, string]> = {
    today: [<ClockIcon size={20} />, "Nothing due today", "Tasks due today, and anything late, will appear here."],
    week: [<ClockIcon size={20} />, "Nothing due this week", "Tasks due in the next seven days will appear here."],
    all: [<CheckSquareIcon size={20} />, "Nothing to do", "Tasks you add, and action items from your meetings, will appear here."],
    waiting: [<UsersIcon size={20} />, "Nothing waiting on others", "Tasks you mark Waiting, or give to someone else, will appear here."],
  };

  return (
    <>
      <PageHeader
        title="My tasks"
        subtitle={loading ? "…" : counts.today ? `${counts.today} to do today${g.late.length ? `, ${g.late.length} of them late` : ""}.` : "Nothing due today."}
      />
      <QuickAdd when={when} inputRef={input} onAdded={reload} />
      <div className="mb-6 animate-enter overflow-x-auto">
        <Segmented<When>
          key={WHENS.map((w) => counts[w]).join("-")} // measure the highlight again once the counts are in
          kind="tab"
          label="Which tasks"
          size="sm"
          value={when}
          onChange={(v) => setParams({ when: v === "today" ? null : v })}
          options={[
            { id: "today", label: <>Today <Count n={counts.today} /></> },
            { id: "week", label: <><Short narrow="Week" wide="This week" /> <Count n={counts.week} /></> },
            { id: "all", label: <><Short narrow="All" wide="Everything" /> <Count n={counts.all} /></> },
            { id: "waiting", label: <><Short narrow="Waiting" wide="Waiting on others" /> <Count n={counts.waiting} /></> },
          ]}
        />
      </div>

      {loading && <Skeleton className="h-32 w-full rounded-xl" />}
      {!loading && sections.length === 0 && <Empty icon={empty[when][0]} title={empty[when][1]}>{empty[when][2]}</Empty>}
      {!loading && sections.length > 0 && <div className="flex flex-col gap-8">{sections}</div>}

      {when === "all" && recentDone.length > 0 && (
        <div className="mt-8">
          <button className="btn btn-sm btn-ghost -ml-3" onClick={() => setShowDone(!showDone)} aria-expanded={showDone}>
            {showDone ? "Hide" : "Show"} {recentDone.length} done
          </button>
          <Collapse open={showDone}>
            <div className="mt-2">{list(recentDone, "Done")}</div>
          </Collapse>
        </div>
      )}
    </>
  );
}

/** A tab's name, shorter on a phone so all four fit. */
function Short({ narrow, wide }: { narrow: string; wide: string }) {
  return (
    <>
      <span className="sm:hidden">{narrow}</span>
      <span className="hidden sm:inline">{wide}</span>
    </>
  );
}

function Count({ n }: { n: number }) {
  return n ? <span className="ml-1 tabular-nums text-ink-soft">{n}</span> : null;
}
