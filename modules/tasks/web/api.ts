import { json, request } from "@core/api";

export type Status = "todo" | "doing" | "waiting" | "done" | "dropped";

export interface Task {
  id: string;
  text: string;
  done: boolean;
  status: Status;
  notes: string;
  priority: number; // 0 none, 1 low, 2 medium, 3 high, 4 urgent (Plane's scale)
  start_on: string | null;
  due_on: string | null;
  assignee_ref: string | null;
  assignee_name: string | null;
  estimate_min: number | null;
  tags: string[];
  project_id: string | null;
  milestone_id: string | null;
  parent_id: string | null;
  sort: number; // your order within its list (fractional)
  source: string; // manual | action-item | ai | import
  source_ref: string | null;
  created_at: string;
  updated_at: string | null;
  completed_at: string | null;
  /** Where it came from, described by that module (null if it's gone or its module is off). */
  came_from: Described | null;
  /** When it's also kept somewhere else (a Plane work item): what it's linked to and what waits for a choice. */
  synced: Synced | null;
  blocked: boolean;
  subtask_count?: number;
  subtasks_done?: number;
}

/** The fields a linked task follows, in the groups that change together. */
export type SyncedField = "text" | "notes" | "status" | "priority" | "start_on" | "due_on" | "assignee";

export interface Synced {
  ref: string; // "plane:<work item id>"
  source: string; // where it's kept: "Plane"
  url: string | null; // where it opens there
  title: string | null; // as that module names it ("SOFTWARE-5 Share the repos")
  removed_at: string | null; // gone from there; the task stays
  synced_at: string;
  /** Fields changed both here and there: their value, until you choose. */
  conflicts: { field: SyncedField; label: string; theirs: Partial<Task> }[];
  /** Fields you've changed here since you both agreed (not sent anywhere yet). */
  edited: SyncedField[];
}

/** Something in another module, as that module describes it. */
export interface Described {
  title: string;
  href: string;
  module: string;
}

export interface Update {
  id: string;
  kind: "comment" | "status" | "summary";
  body: string;
  author_ref: string | null;
  author_name: string | null;
  written_by: string | null;
  created_at: string;
}

export interface TaskDetail extends Task {
  subtasks: Task[];
  blocked_by: { id: string; text: string; status: Status }[];
  blocks: { id: string; text: string; status: Status }[];
  updates: Update[];
}

export interface Labelled<T = string> {
  value: T;
  label: string;
  tone: "trail" | "sun" | "sky" | "forest" | "berry" | "neutral";
}

export interface Meta {
  statuses: Labelled<Status>[];
  open: Status[];
  project_statuses: Labelled[];
  health: Labelled[];
  priorities: Labelled<number>[];
}

/** Worked out from a project's (or milestone's) top-level tasks; never stored. */
export interface Rollup {
  total: number;
  done: number;
  counted: number; // all but dropped
  progress: number | null; // done ÷ counted, null when there's nothing to count
  late: number;
  next_due: string | null;
  by_status: Record<Status, number>;
}

export type Health = "on_track" | "at_risk" | "off_track";

export interface ProjectSummary {
  id: string;
  /** What it's kept in step with elsewhere (a Plane project), described by that module. */
  synced_with: (Described & { ref: string })[];
  name: string;
  summary: string | null;
  brief: string;
  status: string;
  health: Health | null;
  start_on: string | null;
  due_on: string | null;
  owner_ref: string | null;
  owner_name: string | null;
  tags: string[];
  archived: boolean;
  created_at: string;
  rollup: Rollup;
}

export interface Milestone {
  id: string;
  project_id: string;
  name: string;
  due_on: string | null;
  done: boolean;
  done_at: string | null;
  rollup: Rollup;
}

export interface ProjectUpdate extends Update {
  health: Health | null;
}

export interface ProjectDetail extends ProjectSummary {
  milestones: Milestone[];
  latest_status: ProjectUpdate | null;
}

export type ProjectChanges = Partial<Pick<ProjectSummary, "name" | "summary" | "brief" | "status" | "health" | "start_on" | "due_on" | "owner_ref" | "owner_name" | "archived">>;

export interface ListParams {
  project?: string;
  assignee?: string;
  status?: string;
  when?: "late" | "today" | "week" | "waiting";
  q?: string;
  parent?: string;
}

const query = (params: ListParams | Record<string, string>) => {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== "") as [string, string][]).toString();
  return q ? `?${q}` : "";
};

export const tasksApi = {
  list: (params: ListParams = {}) => request<Task[]>(`/tasks${query(params)}`),
  count: (assignee?: string) => request<{ open: number; due_today: number; late: number }>(`/tasks/count${assignee ? `?assignee=${assignee}` : ""}`),
  meta: () => request<Meta>("/tasks/meta"),
  get: (id: string) => request<TaskDetail>(`/tasks/${id}`),
  create: (body: Partial<Task> & { text: string }) => request<{ id: string }>("/tasks", json("POST", body)),
  update: (id: string, changes: Partial<Task>) => request<TaskDetail>(`/tasks/${id}`, json("PATCH", changes)),
  setDone: (id: string, done: boolean) => request<unknown>(`/tasks/${id}`, json("PATCH", { done })),
  remove: (id: string) => request<void>(`/tasks/${id}`, { method: "DELETE" }),
  /** Puts a task after another (null: first). within "project" orders it across milestones (the board). */
  move: (id: string, body: { project_id: string | null; milestone_id: string | null; after_id: string | null; within?: "milestone" | "project"; status?: Status }) =>
    request<unknown>(`/tasks/${id}/move`, json("POST", body)),
  block: (id: string, blockedBy: string) => request<unknown>(`/tasks/${id}/blockers`, json("POST", { blocked_by: blockedBy })),
  unblock: (id: string, blockedBy: string) => request<unknown>(`/tasks/${id}/blockers/${blockedBy}`, { method: "DELETE" }),
  /** A field changed here and there: take theirs, or keep yours. */
  resolve: (id: string, field: SyncedField, keep: "theirs" | "mine") => request<TaskDetail>(`/tasks/${id}/synced`, json("POST", { field, keep })),
  /** Stop following the other side; the task stays, as yours. */
  unlink: (id: string) => request<TaskDetail>(`/tasks/${id}/synced`, { method: "DELETE" }),
  comment: (id: string, body: string) => request<Update>(`/tasks/${id}/updates`, json("POST", { body })),
  projects: (status?: string, archived = false) =>
    request<ProjectSummary[]>(`/tasks/projects${query({ ...(status ? { status } : {}), ...(archived ? { archived: "true" } : {}) })}`),
  project: (id: string) => request<ProjectDetail>(`/tasks/projects/${id}`),
  createProject: (body: ProjectChanges & { name: string }) => request<{ id: string }>("/tasks/projects", json("POST", body)),
  updateProject: (id: string, changes: ProjectChanges) => request<ProjectDetail>(`/tasks/projects/${id}`, json("PATCH", changes)),
  removeProject: (id: string) => request<void>(`/tasks/projects/${id}`, { method: "DELETE" }),
  projectUpdates: (id: string) => request<ProjectUpdate[]>(`/tasks/projects/${id}/updates`),
  postUpdate: (id: string, body: { kind: "status" | "comment"; body: string; health?: Health | null }) =>
    request<ProjectUpdate>(`/tasks/projects/${id}/updates`, json("POST", body)),
  addMilestone: (projectId: string, name: string, dueOn?: string | null) =>
    request<Milestone>(`/tasks/projects/${projectId}/milestones`, json("POST", { name, due_on: dueOn ?? null })),
  updateMilestone: (id: string, changes: { name?: string; due_on?: string | null; done?: boolean }) =>
    request<Milestone>(`/tasks/milestones/${id}`, json("PATCH", changes)),
  removeMilestone: (id: string) => request<void>(`/tasks/milestones/${id}`, { method: "DELETE" }),
};
