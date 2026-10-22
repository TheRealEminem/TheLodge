// A project (#/tasks/projects/<id>?view=overview|list): what it's for, how far along it is, its milestones, the latest word
// on how it's going, and its tasks, grouped by milestone. Every field saves as you leave it.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { LinkedList } from "@core/components/blocks";
import { BackIcon, NetworkIcon, PencilIcon, PlusIcon, TrashIcon } from "@core/components/icons";
import { ControlRow, Segmented, Select, Skeleton, StatusChip, useConfirm } from "@core/components/ui";
import { formatDate, relativeTime } from "@core/format";
import { useLive } from "@core/live";
import type { RouteProps } from "@core/registry";
import { navigate, useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { Health, Meta, Milestone, ProjectChanges, ProjectDetail, Task } from "./api";
import { HealthChip, Progress } from "./bits";
import { Board } from "./Board";
import { dueLabel } from "./dates";
import { Field } from "./Field";
import { BoardIcon, ListIcon, MilestoneIcon, MountainIcon } from "./icons";
import { dueWords } from "./Projects";
import { Check, TaskList } from "./TaskRow";

type View = "overview" | "list" | "board";

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

/** One line that adds a task where it's shown (a project, or one of its milestones). */
function AddTask({ placeholder, onAdd, inputRef }: { placeholder: string; onAdd: (text: string) => Promise<unknown>; inputRef?: React.RefObject<HTMLInputElement> }) {
  const [text, setText] = useState("");
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        const value = text.trim();
        if (!value) return;
        void onAdd(value).then(() => setText(""));
      }}
    >
      <input ref={inputRef} className="field h-9 flex-1" placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} aria-label={placeholder} autoComplete="off" />
    </form>
  );
}

// ── Overview ──────────────────────────────────────────────────────────

function Brief({ project, save }: { project: ProjectDetail; save: (c: ProjectChanges) => Promise<unknown> }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.brief);
  useEffect(() => setDraft(project.brief), [project.brief]);
  if (!editing && project.brief.trim()) {
    return (
      <div className="panel relative px-5 py-4">
        <button className="icon-btn absolute right-2 top-2 h-8 w-8" aria-label="Edit the brief" onClick={() => setEditing(true)}>
          <PencilIcon size={16} />
        </button>
        <div className="prose-family pr-8">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{project.brief}</ReactMarkdown>
        </div>
      </div>
    );
  }
  return (
    <textarea
      aria-label="Brief"
      autoFocus={editing}
      className="field min-h-[8rem] w-full resize-y py-2.5 leading-relaxed"
      placeholder="What it's for, what done looks like, and anything people should know. Markdown works."
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        if (draft !== project.brief) void save({ brief: draft });
        setEditing(false);
      }}
    />
  );
}

function MilestoneRow({ m, onChanged }: { m: Milestone; onChanged: () => void }) {
  const { toast } = useShell();
  const [confirm, dialog] = useConfirm();
  const change = (c: { name?: string; due_on?: string | null; done?: boolean }) =>
    tasksApi.updateMilestone(m.id, c).then(onChanged, (e: Error) => toast(e.message, "error"));
  const due = m.done ? null : dueLabel(m.due_on);
  return (
    <li className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:gap-4">
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <Check done={m.done} onToggle={() => void change({ done: !m.done })} />
        <Field
          bare
          label="Milestone"
          value={m.name}
          onSave={(v) => (v.trim() ? void change({ name: v.trim() }) : toast("A milestone needs some text", "error"))}
          className={`-mx-1.5 min-w-0 flex-1 rounded-sm border border-transparent bg-transparent px-1.5 py-0.5 text-label font-medium outline-none hover:border-line focus:border-line-strong focus:bg-surface ${m.done ? "text-ink-soft line-through" : ""}`}
        />
      </div>
      <div className="flex items-center gap-3 pl-[30px] sm:pl-0">
        <Progress rollup={m.rollup} className="w-44" />
        <Field type="date" label={`${m.name} is due`} className="h-8 w-[9.5rem] text-hint" value={m.due_on ?? ""} onSave={(v) => void change({ due_on: v || null })} />
        {due?.tone === "late" && <span className="hidden whitespace-nowrap text-meta font-medium text-trail-deep md:inline">{due.text}</span>}
        <button
          className="icon-btn h-8 w-8 hover:!bg-trail-soft hover:!text-trail-deep"
          aria-label={`Delete the milestone ${m.name}`}
          onClick={async () => {
            const ok = await confirm({
              title: `Delete the milestone "${m.name}"?`,
              body: m.rollup.total ? `Its ${m.rollup.total} tasks stay in the project, in no milestone.` : "It has no tasks.",
              confirmLabel: "Delete",
              tone: "danger",
            });
            if (ok) await tasksApi.removeMilestone(m.id).then(onChanged, (e: Error) => toast(e.message, "error"));
          }}
        >
          <TrashIcon size={16} />
        </button>
      </div>
      {dialog}
    </li>
  );
}

function Updates({ project, meta, onChanged }: { project: ProjectDetail; meta: Meta | null; onChanged: () => void }) {
  const { toast } = useShell();
  const { data: all, reload } = useLive(() => tasksApi.projectUpdates(project.id), [project.id]);
  const [health, setHealth] = useState<Health | "">(project.health ?? "");
  const [body, setBody] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [posting, setPosting] = useState(false);
  const earlier = (all ?? []).filter((u) => u.id !== project.latest_status?.id);
  const post = async () => {
    if (!body.trim() || posting) return;
    setPosting(true);
    try {
      await tasksApi.postUpdate(project.id, { kind: health ? "status" : "comment", body: body.trim(), health: health || null });
      setBody("");
      onChanged();
      void reload();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setPosting(false);
    }
  };
  const who = (u: { written_by: string | null; author_ref: string | null; author_name: string | null }) =>
    u.written_by ? `Written by ${u.written_by}` : u.author_ref === "core:me" || !u.author_name ? "You" : u.author_name;
  return (
    <>
      {project.latest_status ? (
        <div className="panel mb-3 px-5 py-4">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <HealthChip health={project.latest_status.health} meta={meta} />
            <span className="text-meta text-ink-soft" data-tip={formatDate(project.latest_status.created_at)}>
              {who(project.latest_status)} · {relativeTime(project.latest_status.created_at)}
            </span>
          </div>
          <div className="prose-family">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{project.latest_status.body}</ReactMarkdown>
          </div>
        </div>
      ) : (
        <p className="mb-3 px-1 text-hint text-ink-soft">No updates yet. Say how it's going, and whether it's on track.</p>
      )}
      <form
        className="inset-surface flex flex-col gap-3 px-4 py-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          void post();
        }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-label font-medium">Write an update</span>
          <Segmented<Health | "">
            label="How it's going"
            size="sm"
            value={health}
            onChange={setHealth}
            options={[{ id: "", label: "Just a note" }, ...(meta?.health ?? []).map((h) => ({ id: h.value as Health, label: h.label }))]}
          />
        </div>
        <textarea
          aria-label="Update"
          className="field min-h-[5rem] w-full resize-y py-2 leading-relaxed"
          placeholder={health ? "What happened, and what's next." : "A note for the record."}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && void post()}
        />
        <div className="flex justify-end">
          <button className="btn btn-sm btn-soft" disabled={!body.trim() || posting}>
            Post {health ? "update" : "note"}
          </button>
        </div>
      </form>
      {earlier.length > 0 && (
        <div className="mt-3">
          <button className="btn btn-sm btn-ghost -ml-3" onClick={() => setShowAll(!showAll)} aria-expanded={showAll}>
            {showAll ? "Hide" : "Show"} {earlier.length} earlier
          </button>
          {showAll && (
            <ul className="mt-2 flex flex-col gap-3">
              {earlier.map((u) => (
                <li key={u.id} className="inset-surface px-4 py-3">
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <HealthChip health={u.health} meta={meta} />
                    <span className="text-meta text-ink-soft">{who(u)} · {relativeTime(u.created_at)}</span>
                  </div>
                  <p className="whitespace-pre-wrap text-label leading-relaxed">{u.body}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}

function Overview({ project, meta, save, reload }: { project: ProjectDetail; meta: Meta | null; save: (c: ProjectChanges) => Promise<unknown>; reload: () => void }) {
  const { toast } = useShell();
  const late = project.rollup.late;
  const counts = project.rollup.by_status;
  const lines = [counts.doing && `${counts.doing} doing`, counts.waiting && `${counts.waiting} waiting`, late && `${late} late`].filter(Boolean);
  return (
    <>
      <section className="panel animate-enter px-5 py-4">
        <Progress rollup={project.rollup} />
        {lines.length > 0 && <p className={`mt-2 text-hint ${late ? "text-trail-deep" : "text-ink-soft"}`}>{lines.join(" · ")}</p>}
      </section>

      <section className="panel mt-4 animate-enter divide-y divide-line px-5">
        <ControlRow label="Status">
          <Select
            label="Status"
            size="sm"
            className="w-full sm:w-56"
            value={project.status}
            options={(meta?.project_statuses ?? []).map((s) => ({ value: s.value, label: s.label }))}
            onChange={(v) => void save({ status: v })}
          />
        </ControlRow>
        <ControlRow label="Owner" hint="Who answers for it. Empty: nobody yet.">
          <Field label="Owner" className="w-full sm:w-56" placeholder="Nobody yet" value={project.owner_name ?? ""} onSave={(v) => void save({ owner_ref: null, owner_name: v.trim() || null })} />
        </ControlRow>
        <ControlRow label="Start">
          <Field type="date" label="Start" className="w-full sm:w-56" value={project.start_on ?? ""} onSave={(v) => void save({ start_on: v || null })} />
        </ControlRow>
        <ControlRow label="Due">
          <Field type="date" label="Due" className="w-full sm:w-56" value={project.due_on ?? ""} onSave={(v) => void save({ due_on: v || null })} />
        </ControlRow>
      </section>

      <Block title="Brief">
        <Brief project={project} save={save} />
      </Block>

      <Block title={`Milestones${project.milestones.length ? ` · ${project.milestones.filter((m) => m.done).length} of ${project.milestones.length} reached` : ""}`}>
        {project.milestones.length > 0 && (
          <ul className="panel mb-2 divide-y divide-line">
            {project.milestones.map((m) => (
              <MilestoneRow key={m.id} m={m} onChanged={reload} />
            ))}
          </ul>
        )}
        <AddTask
          placeholder="Add a milestone, like “Designs signed off”"
          onAdd={(name) => tasksApi.addMilestone(project.id, name).then(reload, (e: Error) => toast(e.message, "error"))}
        />
      </Block>

      <Block title="How it's going">
        <Updates project={project} meta={meta} onChanged={reload} />
      </Block>

      <LinkedList of={`tasks:${project.id}`} />
    </>
  );
}

// ── List ──────────────────────────────────────────────────────────────

function List({ project, meta, tasks, onChanged, addRef }: { project: ProjectDetail; meta: Meta | null; tasks: Task[]; onChanged: () => void; addRef: React.RefObject<HTMLInputElement> }) {
  const { toast } = useShell();
  const add = (text: string, milestone_id: string | null) =>
    tasksApi.create({ text, project_id: project.id, milestone_id }).then(onChanged, (e: Error) => toast(e.message, "error"));
  // Dragging (or Alt + ↑ ↓) puts a task after another in a group; into another group, it changes milestone.
  const moveTo = (milestone_id: string | null) => (id: string, after_id: string | null) =>
    void tasksApi.move(id, { project_id: project.id, milestone_id, after_id }).then(onChanged, (e: Error) => toast(e.message, "error"));
  const ordered = tasks.slice().sort((a, b) => Number(a.done || a.status === "dropped") - Number(b.done || b.status === "dropped") || a.sort - b.sort);
  const loose = ordered.filter((t) => !t.milestone_id);
  return (
    <div className="flex flex-col gap-8">
      <section className="animate-enter">
        <AddTask inputRef={addRef} placeholder={`Add a task to ${project.name}`} onAdd={(text) => add(text, null)} />
        <p className="mt-2 px-1 text-meta text-ink-faint">Drag a task to reorder it or move it to another milestone, or use Alt + ↑ ↓.</p>
      </section>
      {project.milestones.map((m) => {
        const mine = ordered.filter((t) => t.milestone_id === m.id);
        const due = m.due_on && !m.done ? dueLabel(m.due_on) : null;
        return (
          <section key={m.id} className="animate-enter">
            <h2 className="eyebrow mb-2 flex flex-wrap items-baseline justify-between gap-x-3 px-1">
              <span className={`inline-flex items-center gap-1.5 ${m.done ? "line-through" : ""}`}>
                <MilestoneIcon size={14} /> {m.name}
              </span>
              <span className="font-normal tabular-nums">
                {m.rollup.counted ? `${m.rollup.done} of ${m.rollup.counted} done` : "No tasks yet"}
                {due && ` · ${dueWords(due.text, due.tone)}`}
              </span>
            </h2>
            <div className="mb-2">
              <TaskList tasks={mine} meta={meta} onChanged={onChanged} label={m.name} onMove={moveTo(m.id)} />
            </div>
            <AddTask placeholder={`Add to ${m.name}`} onAdd={(text) => add(text, m.id)} />
          </section>
        );
      })}
      {(loose.length > 0 || project.milestones.length > 0) && (
        <section className="animate-enter">
          <h2 className="eyebrow mb-2 px-1">{project.milestones.length ? "No milestone" : "Tasks"}</h2>
          <TaskList tasks={loose} meta={meta} onChanged={onChanged} label="Tasks in no milestone" onMove={moveTo(null)} />
        </section>
      )}
      {tasks.length === 0 && project.milestones.length === 0 && (
        <p className="px-1 text-hint text-ink-soft">No tasks yet. Add the first one above, or add milestones in the overview to group them.</p>
      )}
    </div>
  );
}

// ── The page ──────────────────────────────────────────────────────────

/** The board has its own address, so it can use the full width of the window. */
export function ProjectBoard(props: RouteProps) {
  return <ProjectPage {...props} board />;
}

export default function ProjectPage({ params, board = false }: RouteProps & { board?: boolean }) {
  const id = params.id;
  const { toast } = useShell();
  const [confirm, dialog] = useConfirm();
  const [query, setQuery] = useQueryParams();
  const view: View = board ? "board" : query.get("view") === "list" ? "list" : "overview";
  const { data: project, reload, error } = useLive<ProjectDetail>(() => tasksApi.project(id), [id]);
  const { data: tasks, reload: reloadTasks } = useLive(() => tasksApi.list({ project: id }), [id]);
  const { data: meta } = useLive(tasksApi.meta);
  const addRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (view === "list" && query.get("new")) {
      addRef.current?.focus();
      setQuery({ new: null });
    }
  }, [view, query, setQuery, tasks]);

  const save = (changes: ProjectChanges) => tasksApi.updateProject(id, changes).then(() => reload(), (e: Error) => toast(e.message, "error"));
  const refresh = () => void Promise.all([reload(), reloadTasks()]);

  if (error && (!project || /not found/i.test(error))) {
    return (
      <div className="animate-enter">
        <a href="#/tasks/projects" className="btn btn-sm btn-ghost -ml-3 mb-4">
          <BackIcon size={16} /> Projects
        </a>
        <p className="text-body text-ink-soft">That project isn't here any more. It may have been deleted.</p>
      </div>
    );
  }
  if (!project) return <Skeleton className="h-64 w-full rounded-xl" />;

  const status = meta?.project_statuses.find((s) => s.value === project.status);
  const due = project.status === "done" ? null : dueLabel(project.due_on);
  const open = (tasks ?? []).filter((t) => meta?.open.includes(t.status) ?? !t.done).length;
  const remove = async () => {
    const n = project.rollup.total;
    const ok = await confirm({
      title: `Delete ${project.name}?`,
      body: `Its milestones and updates are deleted too. ${n ? `Its ${n} tasks stay, in no project.` : ""} This can't be undone; archive it instead to keep it whole.`,
      confirmLabel: "Delete",
      tone: "danger",
    });
    if (!ok) return;
    await tasksApi.removeProject(project.id).catch((e: Error) => toast(e.message, "error"));
    navigate("tasks/projects");
  };

  return (
    <>
      <div className="mb-4 flex animate-enter flex-wrap items-center justify-between gap-2">
        <a href="#/tasks/projects" className="btn btn-sm btn-ghost -ml-3">
          <BackIcon size={16} /> Projects
        </a>
        <div className="flex items-center gap-1.5">
          <button className="btn btn-sm btn-primary" onClick={() => navigate(`tasks/projects/${id}?view=list&new=1`)}>
            <PlusIcon size={16} /> New task
          </button>
          <button className="btn btn-sm btn-ghost" onClick={() => void save({ archived: !project.archived })}>
            {project.archived ? "Unarchive" : "Archive"}
          </button>
          <button className="btn btn-sm btn-danger-ghost" onClick={() => void remove()}>
            <TrashIcon size={16} /> Delete
          </button>
        </div>
      </div>

      {project.archived && (
        <p className="mb-4 animate-enter rounded-lg border border-line bg-surface-subtle px-4 py-3 text-hint text-ink-soft">
          Archived: it's out of the lists, but kept whole, and search still finds it.
        </p>
      )}

      <header className="animate-enter">
        <div className="flex items-start gap-3">
          <span className="well well-forest mt-1.5">
            <MountainIcon size={16} />
          </span>
          <Field
            bare
            label="Project name"
            value={project.name}
            onSave={(v) => (v.trim() ? void save({ name: v.trim() }) : toast("A project needs a name", "error"))}
            className="page-title -mx-2 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 py-0.5 outline-none transition-colors hover:border-line focus:border-line-strong focus:bg-surface"
          />
        </div>
        <Field
          bare
          label="Summary"
          placeholder="What done looks like, in one line"
          value={project.summary ?? ""}
          onSave={(v) => void save({ summary: v.trim() || null })}
          className="-mx-2 mt-1 w-full rounded-md border border-transparent bg-transparent px-2 py-1 text-body text-ink-soft outline-none transition-colors placeholder:text-ink-faint hover:border-line focus:border-line-strong focus:bg-surface"
        />
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-hint text-ink-soft">
          {status && project.status !== "active" && <StatusChip tone={status.tone} label={status.label} />}
          <HealthChip health={project.health} meta={meta ?? null} />
          {project.owner_name && <span>{project.owner_name}</span>}
          {due && (
            <span data-tip={due.full} className={due.tone === "late" ? "font-medium text-trail-deep" : due.tone === "soon" ? "font-medium text-sun-deep" : ""}>
              {dueWords(due.text, due.tone)}
            </span>
          )}
          <SyncedWith project={project} />
        </p>
      </header>

      <div className="my-6 animate-enter">
        <Segmented<View>
          kind="tab"
          label="Project views"
          size="sm"
          value={view}
          onChange={(v) => (v === "board" ? navigate(`tasks/projects/${id}/board`) : navigate(`tasks/projects/${id}${v === "list" ? "?view=list" : ""}`))}
          options={[
            { id: "overview", label: "Overview", icon: <MountainIcon size={14} /> },
            { id: "list", label: <>List {open > 0 && <span className="ml-1 tabular-nums text-ink-soft">{open}</span>}</>, icon: <ListIcon size={14} /> },
            { id: "board", label: "Board", icon: <BoardIcon size={14} /> },
          ]}
        />
      </div>

      {view === "overview" ? (
        <Overview project={project} meta={meta ?? null} save={save} reload={refresh} />
      ) : view === "board" && tasks ? (
        <Board project={project} tasks={tasks} meta={meta ?? null} onChanged={refresh} />
      ) : tasks ? (
        <List project={project} meta={meta ?? null} tasks={tasks} onChanged={refresh} addRef={addRef} />
      ) : (
        <Skeleton className="h-32 w-full rounded-xl" />
      )}
      {dialog}
    </>
  );
}

/** "Linked to Plane: Software", for a project kept in step with one elsewhere (named by that module). */
function SyncedWith({ project }: { project: ProjectDetail }) {
  const { app } = useShell();
  return (
    <>
      {project.synced_with.map((s) => (
        <a key={s.ref} href={s.href} className="inline-flex items-center gap-1 hover:text-forest">
          <NetworkIcon size={14} className="text-forest" />
          Linked to {app.modules.find((m) => m.id === s.module)?.name ?? s.module}: {s.title}
        </a>
      ))}
    </>
  );
}
