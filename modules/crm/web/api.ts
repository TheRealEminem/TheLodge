import { json, request } from "@core/api";

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
}

export interface PeoplePage {
  items: PersonRow[];
  total: number;
  tiers: Record<Tier, number>;
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

export const crmApi = {
  dashboard: () => request<Dashboard>("/crm/dashboard"),
  people: (p: { tier?: string; org?: string; tag?: string; q?: string; sort?: string; limit?: number }) =>
    request<PeoplePage>(`/crm/people${qs(p)}`),
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
  mergeEntity: (id: string, intoId: string) => request<Entity>(`/crm/entities/${id}/merge`, json("POST", { into_id: intoId })),
  createRelationship: (body: { source_id: string; target_id: string; kind: string; strength?: number; started_at?: string | null }) =>
    request(`/crm/relationships`, json("POST", body)),
  updateRelationship: (id: string, body: { strength?: number }) => request(`/crm/relationships/${id}`, json("PATCH", body)),
  deleteRelationship: (id: string) => request<void>(`/crm/relationships/${id}`, { method: "DELETE" }),
  setConnection: (personId: string, strength: number | null) =>
    request<Connection>(`/crm/people/${personId}/connection`, json("PUT", { strength })),
  paths: (p: { target: string; through?: string }) =>
    request<{ target: GraphNode; paths: GraphPath[] }>(`/crm/graph/paths${qs(p)}`),
  graph: (p: { center?: string; depth?: number; kinds?: string; max_nodes?: number }) => request<Graph>(`/crm/graph${qs(p)}`),
  meta: () => request<{ relationship_kinds: Record<string, RelKindInfo> }>("/crm/meta"),
  me: () => request<Entity | null>("/crm/me"),
  setMe: (name: string) => request<Entity>("/crm/me", json("PUT", { name })),
  makeMe: (entityId: string) => request<Entity>("/crm/me", json("PUT", { entity_id: entityId })),
  loadDemo: () => request<{ entities: number }>("/crm/admin/demo", json("POST")),
};
