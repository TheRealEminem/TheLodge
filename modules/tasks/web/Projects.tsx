// Projects (#/tasks/projects?status=active): each with its health, how far along it is, when it's due and who owns
// it. A new project starts from its name and opens straight away.
import { useState } from "react";
import { Avatar, Empty } from "@core/components/blocks";
import { PlusIcon } from "@core/components/icons";
import { PageHeader, Segmented, Skeleton } from "@core/components/ui";
import { useLive } from "@core/live";
import { navigate, useQueryParams } from "@core/router";
import { useShell } from "@core/shell";
import { tasksApi } from "./api";
import type { ProjectSummary } from "./api";
import { HealthChip, ProjectTile, Progress } from "./bits";
import { dueLabel } from "./dates";
import { MountainIcon } from "./icons";

type Filter = "active" | "planned" | "done" | "all" | "archived";
const FILTERS: Filter[] = ["active", "planned", "done", "all", "archived"];

/** "Due Oct 31", "Due tomorrow", "Due today", or "3 days late". */
export const dueWords = (text: string, tone: string) =>
  tone === "late" || text.startsWith("Due") ? text : `Due ${text === "Tomorrow" ? "tomorrow" : text}`;

function ProjectRow({ project }: { project: ProjectSummary }) {
  const { data: meta } = useLive(tasksApi.meta);
  const due = dueLabel(project.status === "done" ? null : project.due_on);
  const status = project.status !== "active" ? meta?.project_statuses.find((s) => s.value === project.status) : null;
  return (
    <a
      href={`#/tasks/projects/${project.id}`}
      className="grid grid-cols-[auto_1fr] items-center gap-x-3.5 gap-y-2 px-5 py-3.5 transition-colors hover:bg-forest/[.05] focus-visible:bg-forest/[.05] focus-visible:outline-none sm:grid-cols-[auto_minmax(0,1fr)_minmax(9rem,13rem)_auto]"
    >
      <ProjectTile name={project.name} />
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate text-label font-medium">{project.name}</span>
          {status && <span className="shrink-0 text-meta text-ink-soft">{status.label}</span>}
          <HealthChip health={project.health} meta={meta ?? null} />
        </div>
        {project.summary && <div className="mt-0.5 truncate text-hint text-ink-soft">{project.summary}</div>}
      </div>
      <Progress rollup={project.rollup} className="col-span-2 sm:col-span-1" />
      <div className="col-span-2 flex items-center justify-between gap-3 sm:col-span-1 sm:justify-end">
        {due ? (
          <span
            data-tip={due.full}
            className={`whitespace-nowrap text-meta tabular-nums ${due.tone === "late" ? "font-medium text-trail-deep" : due.tone === "soon" ? "font-medium text-sun-deep" : "text-ink-soft"}`}
          >
            {dueWords(due.text, due.tone)}
          </span>
        ) : (
          <span className="text-meta text-ink-faint">No due date</span>
        )}
        {project.owner_name ? (
          <span data-tip={project.owner_name}>
            <Avatar name={project.owner_name} size={24} />
          </span>
        ) : (
          <span className="w-6" />
        )}
      </div>
    </a>
  );
}

export default function Projects() {
  const { toast } = useShell();
  const [params, setParams] = useQueryParams();
  const filter = (FILTERS.includes(params.get("status") as Filter) ? params.get("status") : "active") as Filter;
  const { data: projects } = useLive(
    () => (filter === "archived" ? tasksApi.projects(undefined, true) : tasksApi.projects(filter === "all" ? undefined : filter)),
    [filter],
  );
  const [name, setName] = useState("");
  const [adding, setAdding] = useState(false);

  const create = async () => {
    const value = name.trim();
    if (!value || adding) return;
    setAdding(true);
    try {
      const { id } = await tasksApi.createProject({ name: value, status: filter === "planned" ? "planned" : "active" });
      navigate(`tasks/projects/${id}`);
    } catch (e) {
      toast((e as Error).message, "error");
      setAdding(false);
    }
  };

  const empty: Record<Filter, [string, string]> = {
    active: ["No projects yet", "Your first project will appear here, with its tasks and how far along it is."],
    planned: ["Nothing planned", "Projects you plan for later will wait here."],
    done: ["Nothing finished yet", "Projects you mark done will be kept here."],
    all: ["No projects yet", "Your first project will appear here, with its tasks and how far along it is."],
    archived: ["Nothing archived", "Archived projects leave the lists but stay searchable, and come back here."],
  };

  return (
    <>
      <PageHeader title="Projects" subtitle="What you're working toward, and how far along each one is." />
      <form
        className="mb-6 flex animate-enter gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        <input
          className="field h-10 flex-1"
          placeholder="Name a new project"
          value={name}
          onChange={(e) => setName(e.target.value)}
          aria-label="New project"
          autoComplete="off"
        />
        <button className="btn btn-md btn-primary" disabled={!name.trim() || adding}>
          <PlusIcon size={16} />
          New project
        </button>
      </form>
      <div className="mb-6 animate-enter overflow-x-auto">
        <Segmented<Filter>
          kind="tab"
          label="Which projects"
          size="sm"
          value={filter}
          onChange={(v) => setParams({ status: v === "active" ? null : v })}
          options={[
            { id: "active", label: "Active" },
            { id: "planned", label: "Planned" },
            { id: "done", label: "Done" },
            { id: "all", label: "All" },
            { id: "archived", label: "Archived" },
          ]}
        />
      </div>
      {!projects && <Skeleton className="h-32 w-full rounded-xl" />}
      {projects && projects.length === 0 && (
        <Empty icon={<MountainIcon size={20} />} title={empty[filter][0]}>
          {empty[filter][1]}
        </Empty>
      )}
      {projects && projects.length > 0 && (
        <div className="panel animate-enter divide-y divide-line overflow-hidden">
          {projects.map((p) => (
            <ProjectRow key={p.id} project={p} />
          ))}
        </div>
      )}
    </>
  );
}
