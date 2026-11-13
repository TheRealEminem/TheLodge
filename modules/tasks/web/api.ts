import { json, request } from "@core/api";
import type { Job } from "@core/api";

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
  /** Where its changes wait for you to send them (named by the module sending them), while they wait. */
  sharing: { title: string; href: string }[];
  /** Anything not worth a column: a subtask the AI proposed says which AI ({written_by, edited}). */
  attributes: Record<string, unknown>;
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
  /** The AI that wrote it (or drafted it, when author_ref says who posted it). */
  written_by: string | null;
  /** 1: drafted by AI, then changed by whoever posted it. */
  edited?: number;
  created_at: string;
  /** Where it was offered as a comment, named by the module that took it: waiting for your approval, or posted. */
  shared?: Shared[];
}

export interface Shared {
  title: string;
  href: string;
  state: "waiting" | "posted";
}

/** A subtask the AI proposed: yours to accept (it becomes a subtask), edit or drop. */
export interface StepProposal {
  id: string;
  text: string;
  estimate_min: number | null;
  state: "proposed" | "accepted" | "dropped";
  item_id: string | null;
  edited?: boolean;
}

/** What the AI drafted for you to look over: a project's status update, or a task's subtasks. */
export interface Draft {
  id: string;
  kind: "status" | "breakdown";
  project_id: string | null;
  item_id: string | null;
  status: "drafting" | "ready";
  body: string;
  health: Health | null;
  why: string | null;
  proposals: StepProposal[];
  written_by: string | null;
  edited: boolean;
  created_at: string;
  updated_at: string;
  /** Its job: drafting, or failed with why (JobStatus shows Try again). */
  job: Job | null;
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
  /** Open tasks not linked anywhere yet and not waiting to be sent (0 when the project isn't linked). */
  unshared: number;
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
  /** Asks for your changes to be sent where it's linked (a new task in a linked project: made there). Nothing is sent
   *  yet: it waits for your approval where it's going (task.sharing says where). */
  /** Asks for each of the project's open tasks not linked yet to be made where the project is linked. */
  shareProject: (id: string) => request<{ asked: number }>(`/tasks/projects/${id}/share`, json("POST")),
  share: (id: string) => request<TaskDetail & { asked: { fields: SyncedField[]; new: boolean } }>(`/tasks/${id}/share`, json("POST")),
  comment: (id: string, body: string) => request<Update>(`/tasks/${id}/updates`, json("POST", { body })),
  /** "Break it down": the AI proposes subtasks, in a job. */
  breakdown: (id: string) => request<Draft | null>(`/tasks/${id}/breakdown`),
  breakDown: (id: string) => request<Draft>(`/tasks/${id}/breakdown`, json("POST")),
  /** "Draft a status": the AI drafts the project's status update, in a job. */
  projectDraft: (id: string) => request<Draft | null>(`/tasks/projects/${id}/draft`),
  draftStatus: (id: string) => request<Draft>(`/tasks/projects/${id}/draft`, json("POST")),
  editDraft: (id: string, changes: { body?: string; health?: Health | null }) => request<Draft>(`/tasks/drafts/${id}`, json("PATCH", changes)),
  discardDraft: (id: string) => request<void>(`/tasks/drafts/${id}`, { method: "DELETE" }),
  /** Posts a status draft as the project's update; share_on (a linked task) offers it there too, as a comment. */
  postDraft: (id: string, shareOn?: string | null) =>
    request<ProjectUpdate & { asked?: { title: string; href: string } }>(`/tasks/drafts/${id}/post`, json("POST", shareOn ? { share_on: shareOn } : {})),
  editProposal: (draftId: string, id: string, changes: { text?: string; estimate_min?: number | null; state?: "proposed" | "dropped" }) =>
    request<Draft>(`/tasks/drafts/${draftId}/proposals/${id}`, json("PATCH", changes)),
  /** These proposed subtasks (all still proposed, when ids is left out) become subtasks. */
  acceptProposals: (draftId: string, ids?: string[]) => request<Draft>(`/tasks/drafts/${draftId}/accept`, json("POST", ids ? { ids } : {})),
  /** Offers an update, as a new comment, where a linked task also lives (a project's update: on itemId). It waits for
   *  your approval there. */
  shareUpdate: (id: string, itemId?: string | null) =>
    request<{ title: string; href: string }>(`/tasks/updates/${id}/share`, json("POST", itemId ? { item_id: itemId } : {})),
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
