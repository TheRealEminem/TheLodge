import { json, request } from "@core/api";
import type { Job } from "@core/api";

export type EntityKind = "person" | "organization" | "meeting" | "document" | "topic";
export type Tier = "strong" | "working" | "light" | "indirect" | "none";

export interface EntitySummary {
  id: string;
  kind: EntityKind;
  name: string;
  subtitle: string | null;
  occurred_at: string | null;
  is_self: boolean;
}

export interface Connection {
  tier: Tier;
  score: number;
  strength: number | null;
  user_set: boolean;
  context: string | null;
  roles: string[];
  meetings: number;
  first_met_at: string | null;
  last_met_at: string | null;
  coauthored: number;
  mentions: number;
  last_mentioned_at: string | null;
  mutual: EntitySummary[];
  via: EntitySummary[];
}

export interface PersonRow {
  person: EntitySummary;
  title: string | null;
  org: EntitySummary | null;
  location: string | null;
  tags: string[];
  connection: Connection;
  created_at: string;
  needs_research: boolean;
}

export interface PeoplePage {
  items: PersonRow[];
  total: number;
  tiers: Record<Tier, number>;
  needs_research: number;
}

export interface CaptureStatus {
  configured: boolean;
  /** Why it's off right now (Lockdown), or null. */
  locked: string | null;
  last_run_at: string | null;
  last_ok_at: string | null;
  last_counts: Record<string, number> | null;
  error: string | null;
  key_problem: boolean | null;
  calendars: string[] | null;
}

export interface CaptureSource {
  origin: "granola" | "calendar";
  label: string;
  meetings: number;
  people: number;
  kept: number;
  lines: number;
}

export interface CaptureOverview {
  granola: CaptureStatus;
  calendar: CaptureStatus;
  sources: CaptureSource[];
}

export interface SheetStatus {
  configured: boolean;
  locked: string | null;
  script_version: number;
  last_run_at: string | null;
  last_ok_at: string | null;
  last_counts: Record<string, number> | null;
  error: string | null;
  link_problem: boolean | null;
  spreadsheet: { name: string; url: string } | null;
  /** Tabs held back because many values were emptied or replaced at once. */
  held: Record<string, { cells: number; columns: string[] }> | null;
  decision: "apply" | "restore" | null;
}

export type ResearchState = "needed" | "snoozed" | "dismissed" | "name_needed" | "has_context";

export interface ResearchStatus {
  state: ResearchState;
  until: string | null;
  at: string | null;
}

export interface OrgRow {
  org: EntitySummary;
  tags: string[];
  members: number;
  past: number;
  affiliates: number;
  known: number;
  best_tier: Tier;
  contacts: { person: EntitySummary; tier: Tier }[];
  mine: "current" | "past" | null;
  mentions: number;
  last_activity_at: string | null;
  connected: boolean;
}

export type OrgScope = "known" | "connected" | "mentioned" | "all";

export interface OrgPage {
  items: OrgRow[];
  total: number;
  scopes: Record<OrgScope, number>;
}

export interface Dashboard {
  me: EntitySummary | null;
  counts: Partial<Record<EntityKind, number>>;
  relationships: number;
  pending_reviews: number;
  tiers: Partial<Record<Tier, number>>;
  strong: PersonRow[];
  working: PersonRow[];
  reconnect: PersonRow[];
  lit_up: PersonRow[];
  key_orgs: OrgRow[];
  recent_meetings: { meeting: EntitySummary; attendees: EntitySummary[]; discussed: EntitySummary[] }[];
  research_needed: number;
  research_close: number;
  research: PersonRow[];
  duplicates: number;
  weekly_activity: { week: string; meetings: number }[];
}

export interface Entity {
  id: string;
  kind: EntityKind;
  name: string;
  summary: string | null;
  attributes: Record<string, unknown>;
  tags: string[];
  occurred_at: string | null;
  is_self: boolean;
  source: string;
  subtitle: string | null;
  degree: number;
  last_interaction_at: string | null;
  created_at: string;
}

export interface RelationshipView {
  id: string;
  kind: string;
  direction: "out" | "in";
  label: string;
  other: EntitySummary;
  properties: Record<string, unknown>;
  strength: number;
  started_at: string | null;
  ended_at: string | null;
  source: string;
  evidence: EntitySummary | null;
}

export interface RoleOut {
  kind: string;
  label: string;
  title: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface Affiliation {
  org: EntitySummary;
  roles: RoleOut[];
  current: boolean;
  known: number;
}

export interface PersonLink {
  person: EntitySummary;
  relation: string;
  detail: string | null;
  current: boolean;
  tier: Tier;
}

export interface EventRef {
  event: EntitySummary;
  role: string;
  with_me: boolean;
  people: EntitySummary[];
  snippet: string | null;
}

export interface EntityContext {
  connection: Connection | null;
  org: OrgRow | null;
  affiliations: Affiliation[];
  people: PersonLink[];
  orgs: { org: EntitySummary; relation: string }[];
  meetings: EventRef[];
  documents: EventRef[];
  topics: EntitySummary[];
}

export interface TimelineEvent {
  id: string;
  at: string;
  type: "meeting" | "document" | "relationship" | "relationship_end" | "note";
  title: string;
  detail: string | null;
  entity: EntitySummary | null;
  via: EntitySummary | null;
}

export interface Note {
  id: string;
  entity_id: string;
  body: string;
  occurred_at: string;
  source: string;
}

export interface GraphNode {
  id: string;
  kind: EntityKind;
  name: string;
  subtitle: string | null;
  degree: number;
  is_self: boolean;
  depth: number | null;
  tier: Tier | null;
}

export interface GraphLink {
  id: string;
  source: string;
  target: string;
  kind: string;
  strength: number;
  label?: string | null; // people paths: the reason for this hop, in words
}

export interface Graph {
  nodes: GraphNode[];
  links: GraphLink[];
  truncated: boolean;
}

export interface GraphPath {
  nodes: GraphNode[];
  links: GraphLink[];
  hops: number;
  score: number;
}

// ---- The people-first network ----

export type GroupKind = "organization" | "topic" | "tag" | "preset";
export interface NetGroup {
  id: string; // "org:…", "topic:…" or "tag:…" ("preset" is the preset on screen, drawn as a group)
  kind: GroupKind;
  name: string;
  size: number;
  ref: string | null; // the organization or topic record, if there is one
}
export interface NetNode {
  id: string;
  name: string;
  subtitle: string | null;
  degree: number;
  is_self: boolean;
  tier: Tier | null;
  depth: number | null;
  groups: string[]; // ids of the groups they're in
  tags: string[];
}
export interface NetWhy {
  text: string;
  ref?: { id: string; kind: EntityKind; name: string };
}
export interface NetLink {
  id: string;
  source: string;
  target: string;
  basis: "direct" | "met" | "mentioned";
  weight: number;
  why: NetWhy[];
}
export interface Network {
  nodes: NetNode[];
  links: NetLink[];
  groups: NetGroup[];
  truncated: boolean;
}
export interface GroupDetail extends NetGroup {
  members: { id: string; name: string; tier: Tier | null; why: string }[];
}
export interface Evidence {
  id: string;
  kind: "meeting" | "document";
  name: string;
  at: string | null;
  role: "took part" | "came up";
  people: string[];
}
export interface SavedView {
  id: string;
  name: string;
  wells: string[];
}

// ---- Presets: questions the network answers ----

export type PresetKind = "at" | "intro" | "investors" | "event" | "bridges" | "followups" | "rule";
export interface PresetSpec {
  kind: PresetKind;
  group?: string; // at: "org:…", "topic:…" or "tag:…"
  target?: string; // intro: a person or organization id
  event?: string; // event: a meeting or document id
  a?: string; // bridges: two group ids
  b?: string;
  name?: string; // rule
  about?: string;
  tags?: string[];
  topics?: string[];
  organizations?: string[];
  events?: string[];
  words?: string[];
  picks?: { id: string; why: string }[];
}
export interface PresetPerson {
  id: string;
  name: string;
  subtitle: string | null;
  tier: Tier | null;
  why: string[];
}
export interface PresetResult {
  title: string;
  about: string;
  spec: PresetSpec;
  people: PresetPerson[];
}
export interface SavedPreset {
  id: string;
  name: string;
  about: string;
  spec: PresetSpec;
  source: "you" | "ai";
  created_at: string;
}
export interface PresetChoices {
  groups: { id: string; kind: GroupKind; name: string; size: number }[];
  events: { id: string; kind: "meeting" | "document"; name: string; at: string | null; size: number }[];
}
export interface PresetIdea {
  name: string;
  about: string;
  spec: PresetSpec;
  count: number;
  sample: string[];
}
export interface PresetAsk {
  id: string;
  request: string; // empty: "suggest some"
  status: "queued" | "done" | "error";
  ideas: PresetIdea[];
  error: string | null;
  written_by: string | null;
  created_at: string;
}

// ---- The inbox ----

export type InboxStatus = "pending" | "processing" | "review" | "applied" | "failed" | "discarded" | "skipped";
export type InboxSource = "manual_note" | "webhook" | "meeting" | "linkedin_csv" | "document" | "spreadsheet";

export interface InboxRow {
  id: string;
  source: InboxSource;
  status: InboxStatus;
  title: string | null;
  occurred_at: string | null;
  error: string | null;
  extractor: string | null;
  created_at: string;
  updated_at: string;
  result: Record<string, unknown> | null;
  filename: string | null;
  category: string | null;
  words: number | null;
  work: Job | null; // the background job reading it: running, queued, or parked with a reason
}

export interface Candidate {
  id: string;
  name: string;
  kind: EntityKind;
  subtitle: string | null;
  score: number;
  reason: string;
}
export interface ProposalEntity {
  ref: string;
  kind: EntityKind;
  name: string;
  role: string;
  title: string | null;
  email: string | null;
  location: string | null;
  linkedin_url: string | null;
  website: string | null;
  summary: string | null;
  tags: string[];
  facts: string[];
  action: "link" | "create" | "skip";
  match_id: string | null;
  ambiguous: boolean;
  is_self: boolean;
  candidates: Candidate[];
}
export interface ProposalRelationship {
  id: string;
  source: string;
  target: string;
  kind: string;
  context: string | null;
  started: string | null;
  ended: string | null;
  include: boolean;
}
export interface Proposal {
  version: number;
  doc_type: "meeting_notes" | "person_profile" | "organization_profile" | "document";
  record: {
    include: boolean;
    kind: "meeting" | "document";
    match_id: string | null;
    title: string;
    occurred_at: string;
    summary: string;
    key_points: string[];
    action_items: string[];
    tags: string[];
  };
  subject_ref: string | null;
  entities: ProposalEntity[];
  relationships: ProposalRelationship[];
  warnings: string[];
}
export interface SheetMappingInfo {
  header_row: number;
  row_kind: "person" | "organization" | "skip";
  columns: { column: string; target: string; attribute_key: string | null }[];
  sheet_tags: string[];
  event_name: string | null;
  event_date: string | null;
  reason: string;
  mapped_by: string; // "rules", or who mapped the columns
}
export interface SheetProposal {
  kind: "spreadsheet";
  sheets: Record<string, SheetMappingInfo>;
}
export interface InboxItem extends InboxRow {
  raw_text: string | null;
  payload: { filename?: string; folder?: string | null; words?: number; triage?: { category: string; process: string; reason: string } };
  proposal: Proposal | SheetProposal | null;
}
export interface InboxSummary {
  counts: Partial<Record<InboxStatus, number>>;
  active: number;
  parked: { count: number; reason: string | null };
}

export interface RelKindInfo {
  label: string;
  inverse: string;
  sources: EntityKind[] | null;
  targets: EntityKind[] | null;
  symmetric: boolean;
}

export interface EntityInput {
  kind: EntityKind;
  name: string;
  summary?: string | null;
  attributes?: Record<string, unknown>;
  tags?: string[];
  occurred_at?: string | null;
}

const qs = (params: Record<string, string | number | undefined | null>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
};

export interface AiRole {
  role: "extraction" | "utility" | "profiles";
  setting: string; // the setting that picks this job's provider
  choice: string; // "auto" or a provider id
  label: string;
  hint: string;
  provider: string; // who would answer right now
  providerLabel: string;
  model: string;
  ready: boolean;
  reason: string;
  local: boolean;
  rules: boolean; // whether "Rules only (no AI)" is a choice for this job
}

// ---- Overviews and questions about a person ----

export interface OverviewState {
  overview: { body: string; written_by: string; created_at: string; current: boolean } | null;
  job: Job | null; // the latest work on it
  material: boolean; // false: nothing on file beyond a name
  ready: boolean; // an AI is set up for this job
  reason: string; // why not, when it isn't
  provider: string;
  local: boolean;
}

export interface Question {
  id: string;
  question: string;
  answer: string | null;
  status: "queued" | "done" | "error";
  error: string | null;
  written_by: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface DuplicateSide {
  id: string;
  name: string;
  kind: EntityKind;
  is_self: boolean;
  degree: number;
  subtitle: string | null;
  email: string | null;
  source: string;
  created_at: string | null;
}

export interface DuplicatePair {
  id: string;
  kind: EntityKind;
  score: number;
  reasons: string[];
  status: "open" | "not_same";
  a: DuplicateSide;
  b: DuplicateSide;
}

export interface MergeRecord {
  id: string;
  source_id: string;
  target_id: string;
  kind: EntityKind;
  name: string;
  created_at: string;
}

type Brief = { id: string; name: string; kind: EntityKind };

export type ResearchLevel = "quick" | "better" | "best";

export interface ResearchRun {
  id: string;
  person_id: string;
  person: string | null;
  level: ResearchLevel;
  batch: boolean;
  status: "queued" | "running" | "waiting" | "done" | "failed" | "cancelled";
  stage: "ask" | "check" | "more" | "write" | "done";
  error: string | null;
  searches: number;
  cost: number;
  inbox_id: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface GeminiOverview {
  ready: boolean;
  reason: string | null;
  level: ResearchLevel;
  batch: boolean;
  budget: number;
  spent: number;
  prices_as_of: string;
  levels: { id: ResearchLevel; label: string; hint: string; models: string[]; estimate: number; estimate_batch: number }[];
  runs: ResearchRun[];
}

export const crmApi = {
  inbox: (statuses?: string) => request<InboxRow[]>(`/crm/ingest/jobs${qs({ status: statuses, limit: 200 })}`),
  inboxSummary: () => request<InboxSummary>("/crm/ingest/summary"),
  inboxItem: (id: string) => request<InboxItem>(`/crm/ingest/jobs/${id}`),
  addNotes: (b: { text: string; title?: string; occurred_at?: string; subject_id?: string }) => request<InboxRow>("/crm/ingest/notes", json("POST", b)),
  addFiles: (files: { file: File; path: string }[], autoApply: boolean, subjectId?: string) => {
    const form = new FormData();
    form.append("auto_apply", String(autoApply));
    if (subjectId) form.append("subject_id", subjectId);
    for (const { file, path } of files) form.append("files", file, path);
    return request<InboxRow[]>("/crm/ingest/files", { method: "POST", body: form });
  },
  applyItem: (id: string, proposal: Proposal) => request<InboxItem>(`/crm/ingest/jobs/${id}/apply`, json("POST", { proposal })),
  discardItem: (id: string) => request<InboxItem>(`/crm/ingest/jobs/${id}/discard`, json("POST")),
  retryItem: (id: string) => request<InboxItem>(`/crm/ingest/jobs/${id}/retry`, json("POST")),
  applyReady: () => request<{ applied: number; held: number }>("/crm/ingest/jobs/apply-ready", json("POST")),
  addLinkedIn: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<InboxRow>("/crm/ingest/linkedin", { method: "POST", body: form });
  },
  resume: () => request<{ resumed: number }>("/crm/ingest/resume", json("POST")),
  aiRoles: () => request<AiRole[]>("/crm/ai"),
  dashboard: () => request<Dashboard>("/crm/dashboard"),
  people: (p: { tier?: string; org?: string; tag?: string; q?: string; sort?: string; limit?: number; needs_research?: string }) =>
    request<PeoplePage>(`/crm/people${qs(p)}`),
  capture: () => request<CaptureOverview>("/crm/capture"),
  captureTest: (which: "granola" | "calendar") =>
    request<Record<string, unknown>>(`/crm/capture/${which}/test`, json("POST")),
  captureSync: () => request<{ queued: number }>("/crm/capture/sync", json("POST")),
  captureRemove: (origin: string) =>
    request<{ meetings: number; people: number; lines: number; kept: number }>(`/crm/capture/${origin}/remove`, json("POST")),
  sheet: () => request<SheetStatus>("/crm/sheet"),
  sheetScript: () => request<{ text: string; version: number }>("/crm/sheet/script"),
  sheetTest: () => request<{ ok: boolean; spreadsheet: { name: string; url: string } | null }>("/crm/sheet/test", json("POST")),
  sheetSync: () => request<{ job: string }>("/crm/sheet/sync", json("POST")),
  sheetDecide: (choice: "apply" | "restore") => request<{ job: string }>("/crm/sheet/decide", json("POST", { choice })),
  researchStatus: (id: string) => request<ResearchStatus>(`/crm/people/${id}/research`),
  setResearch: (id: string, action: "snooze" | "dismiss" | "restore") =>
    request<ResearchStatus>(`/crm/people/${id}/research`, json("POST", { action })),
  geminiOverview: () => request<GeminiOverview>("/crm/research/gemini"),
  startGemini: (personIds: string[], level: ResearchLevel, batch: boolean) =>
    request<{ started: number; skipped: { id: string; reason: string }[]; estimate_each: number }>("/crm/research/gemini", json("POST", { person_ids: personIds, level, batch })),
  geminiRun: (personId: string) => request<{ run: ResearchRun | null }>(`/crm/people/${personId}/research/gemini`),
  cancelRun: (runId: string) => request<ResearchRun>(`/crm/research/gemini/${runId}/cancel`, json("POST")),
  retryRun: (runId: string) => request<ResearchRun>(`/crm/research/gemini/${runId}/retry`, json("POST")),
  researchBrief: (id: string) => request<{ text: string }>(`/crm/people/${id}/research/brief`),
  organizations: (p: { scope?: string; q?: string; tag?: string; sort?: string; limit?: number }) =>
    request<OrgPage>(`/crm/organizations${qs(p)}`),
  entity: (id: string) => request<{ entity: Entity }>(`/crm/entities/${id}`),
  detail: (id: string) => request<{ entity: Entity; relationships: RelationshipView[] }>(`/crm/entities/${id}`),
  context: (id: string) => request<EntityContext>(`/crm/entities/${id}/context`),
  timeline: (id: string) => request<TimelineEvent[]>(`/crm/entities/${id}/timeline`),
  notes: (id: string) => request<Note[]>(`/crm/entities/${id}/notes`),
  addNote: (id: string, body: string) => request<Note>(`/crm/entities/${id}/notes`, json("POST", { body })),
  deleteNote: (id: string) => request<void>(`/crm/notes/${id}`, { method: "DELETE" }),
  entities: (p: { kind?: string; q?: string; sort?: string; limit?: number; tag?: string }) =>
    request<{ items: Entity[]; total: number }>(`/crm/entities${qs(p)}`),
  createEntity: (body: EntityInput) => request<Entity>("/crm/entities", json("POST", body)),
  updateEntity: (id: string, body: Partial<EntityInput>) => request<Entity>(`/crm/entities/${id}`, json("PATCH", body)),
  deleteEntity: (id: string) => request<void>(`/crm/entities/${id}`, { method: "DELETE" }),
  duplicates: (entityId?: string) => request<{ total: number; items: DuplicatePair[] }>(`/crm/duplicates${qs({ entity_id: entityId })}`),
  checkDuplicates: () => request<{ queued: boolean }>("/crm/duplicates/check", json("POST")),
  mergePair: (pairId: string, keepId: string) => request<Brief>(`/crm/duplicates/${pairId}/merge`, json("POST", { keep_id: keepId })),
  notSame: (pairId: string) => request<{ ok: boolean }>(`/crm/duplicates/${pairId}/not-same`, json("POST")),
  merges: (id: string) => request<MergeRecord[]>(`/crm/entities/${id}/merges`),
  undoMerge: (mergeId: string) => request<Brief>(`/crm/merges/${mergeId}/undo`, json("POST")),
  movedTo: (id: string) => request<{ id: string | null }>(`/crm/entities/${id}/moved`),
  mergeEntity: (id: string, intoId: string) => request<Entity>(`/crm/entities/${id}/merge`, json("POST", { into_id: intoId })),
  createRelationship: (body: { source_id: string; target_id: string; kind: string; strength?: number; started_at?: string | null }) =>
    request(`/crm/relationships`, json("POST", body)),
  updateRelationship: (id: string, body: { strength?: number }) => request(`/crm/relationships/${id}`, json("PATCH", body)),
  deleteRelationship: (id: string) => request<void>(`/crm/relationships/${id}`, { method: "DELETE" }),
  setConnection: (personId: string, strength: number | null) =>
    request<Connection>(`/crm/people/${personId}/connection`, json("PUT", { strength })),
  paths: (p: { target: string; through?: string }) =>
    request<{ target: GraphNode; paths: GraphPath[] }>(`/crm/graph/paths${qs(p)}`),
  network: (p: { focus?: string; depth?: number; max_nodes?: number }) => request<Network>(`/crm/network${qs(p)}`),
  group: (id: string) => request<GroupDetail>(`/crm/network/groups/${id}`),
  evidence: (id: string) => request<Evidence[]>(`/crm/network/evidence/${id}`),
  netPaths: (p: { target: string }) => request<{ source: GraphNode; target: GraphNode; paths: GraphPath[] }>(`/crm/network/paths${qs(p)}`),
  tagNames: () => request<{ tag: string; count: number }[]>("/crm/network/tags"),
  retag: (b: { ids: string[]; add?: string[]; remove?: string[] }) => request<{ changed: number }>("/crm/network/tags", json("POST", b)),
  views: () => request<SavedView[]>("/crm/network/views"),
  saveView: (name: string, wells: string[]) => request<SavedView>("/crm/network/views", json("POST", { name, wells })),
  deleteView: (id: string) => request<void>(`/crm/network/views/${id}`, json("DELETE")),
  presets: () => request<SavedPreset[]>("/crm/network/presets"),
  presetChoices: () => request<PresetChoices>("/crm/network/presets/choices"),
  runPreset: (spec: PresetSpec) => request<PresetResult>("/crm/network/presets/run", json("POST", spec)),
  savePreset: (b: { name: string; about?: string; spec: PresetSpec }) => request<SavedPreset>("/crm/network/presets", json("POST", b)),
  deletePreset: (id: string) => request<void>(`/crm/network/presets/${id}`, json("DELETE")),
  presetAsks: () => request<PresetAsk[]>("/crm/network/presets/asks"),
  askForPresets: (request_: string) => request<PresetAsk>("/crm/network/presets/asks", json("POST", { request: request_ })),
  dismissAsk: (id: string) => request<void>(`/crm/network/presets/asks/${id}`, json("DELETE")),
  graph: (p: { center?: string; depth?: number; kinds?: string; max_nodes?: number }) => request<Graph>(`/crm/graph${qs(p)}`),
  meta: () => request<{ relationship_kinds: Record<string, RelKindInfo> }>("/crm/meta"),
  me: () => request<Entity | null>("/crm/me"),
  setMe: (name: string) => request<Entity>("/crm/me", json("PUT", { name })),
  makeMe: (entityId: string) => request<Entity>("/crm/me", json("PUT", { entity_id: entityId })),
  loadDemo: () => request<{ entities: number }>("/crm/admin/demo", json("POST")),
  overview: (personId: string) => request<OverviewState>(`/crm/people/${personId}/overview`),
  redoOverview: (personId: string) => request<OverviewState>(`/crm/people/${personId}/overview`, json("POST")),
  overviewCoverage: () => request<{ people: number; written: number }>("/crm/overviews"),
  questions: (personId: string) => request<Question[]>(`/crm/people/${personId}/questions`),
  ask: (personId: string, question: string) => request<Question>(`/crm/people/${personId}/questions`, json("POST", { question })),
  clearQuestions: (personId: string) => request<void>(`/crm/people/${personId}/questions`, json("DELETE")),
  retryQuestion: (id: string) => request<Question>(`/crm/questions/${id}/retry`, json("POST")),
  pictures: () => request<Record<string, string>>("/crm/pictures"),
  putPicture: (id: string, picture: Blob) => request<void>(`/crm/pictures/${id}`, { method: "PUT", headers: { "Content-Type": picture.type || "image/jpeg" }, body: picture }),
  deletePicture: (id: string) => request<void>(`/crm/pictures/${id}`, json("DELETE")),
  lookUpPicture: (id: string) => request<{ found: boolean }>(`/crm/people/${id}/picture/lookup`, json("POST")),
  lookUpPictures: () => request<{ job: string }>("/crm/pictures/lookup", json("POST")),
  pictureLookup: () => request<{ allowed: boolean; reason: string | null; job: Job | null }>("/crm/pictures/lookup"),
};
