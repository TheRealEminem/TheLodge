import { json, request } from "@core/api";
import type { Job } from "@core/api";

export type Stance = "very_warm" | "warm" | "mixed" | "cool" | "very_cool" | "unknown";
export type Lean = "warm" | "cool" | "neutral";

export interface Evidence {
  date: string;
  source: string;
  text: string;
  quoted: boolean;
  leans: Lean;
}

export interface Reading {
  id: string;
  person_ref: string;
  person_name: string;
  subject_key: string;
  subject_name: string;
  status: "queued" | "done" | "error";
  stance: Stance | null;
  confidence: "low" | "medium" | "high" | null;
  written_by: string | null;
  error: string | null;
  created_at: string;
  read_at: string | null;
  /** While it's queued: its job, which may be waiting (for memory, say) with a reason. */
  job?: Job | null;
  body: {
    summary?: string;
    evidence?: Evidence[];
    drivers?: string[];
    change?: string;
    helps?: string[];
    unknowns?: string[];
    estimate?: number | null;
    characters?: number;
  };
}

export interface Subject {
  key: string;
  name: string;
  kind: "me" | "company" | "product" | "person" | "organization";
  id?: string;
  description?: string;
  terms?: string[];
}

export interface SavedSubject {
  id: string;
  key: string;
  kind: "product" | "person" | "organization";
  ref: string | null;
  name: string;
  description: string;
  terms: string[];
}

export interface AiState {
  label: string;
  model: string;
  ready: boolean;
  reason: string;
  local: boolean;
}

export interface PersonPage {
  missing: boolean;
  person: { ref: string; name: string | null; first?: string; material?: boolean; meetings_with_you?: number };
  subjects: Subject[];
  readings: Reading[];
  provider: AiState;
  transcripts?: boolean;
}

export interface PortraitState {
  portrait: { body: string; written_by: string | null; created_at: string; current: boolean } | null;
  job: Job | null;
  material: boolean;
  /** How many of their own lines from transcripts it was written from. */
  voice: number;
  ready: boolean;
  reason: string;
  provider: string;
  local: boolean;
}

export interface Line {
  id: string;
  conversation_id: string;
  role: "you" | "them";
  body: string;
  status: "queued" | "done" | "error";
  error: string | null;
  written_by: string | null;
  created_at: string;
  /** Phrases in their reply the AI made up, as written in it. */
  guesses: string[];
  /** Phrases in their reply the records support, and the record each rests on. */
  grounds: { phrase: string; source: string }[];
  job?: Job | null;
}

export interface ConversationRow {
  id: string;
  person_ref: string;
  person_name: string;
  scenario: string;
  created_at: string;
  updated_at: string;
  messages: number;
}

export interface Conversation extends Omit<ConversationRow, "messages"> {
  messages: Line[];
}

export interface AiJobs {
  readings: AiState & { choice: string };
  talk: AiState & { choice: string };
}

export type Asked = { unchanged: false; reading: Reading } | { unchanged: true; since: string; reading: Reading };

const enc = encodeURIComponent;

export const sedimentApi = {
  person: (ref: string) => request<PersonPage>(`/sediment/people/${enc(ref)}`),
  take: (ref: string, subject: string, again = false) => request<Asked>(`/sediment/people/${enc(ref)}/readings`, json("POST", { subject, again })),
  forget: (ref: string) => request<void>(`/sediment/people/${enc(ref)}`, { method: "DELETE" }),
  retry: (id: string) => request<Reading>(`/sediment/readings/${id}/retry`, json("POST")),
  remove: (id: string) => request<void>(`/sediment/readings/${id}`, { method: "DELETE" }),
  recent: () => request<Reading[]>("/sediment/recent"),
  subjects: () => request<SavedSubject[]>("/sediment/subjects"),
  addProduct: (name: string, description: string, terms: string[]) =>
    request<SavedSubject>("/sediment/subjects", json("POST", { kind: "product", name, description, terms })),
  addFromBook: (ref: string, kind: "person" | "organization") => request<SavedSubject>("/sediment/subjects", json("POST", { kind, ref })),
  editSubject: (id: string, name: string, description: string, terms: string[]) =>
    request<SavedSubject>(`/sediment/subjects/${id}`, json("PATCH", { name, description, terms })),
  removeSubject: (id: string) => request<void>(`/sediment/subjects/${id}`, { method: "DELETE" }),
  ai: () => request<AiJobs>("/sediment/ai"),
  portrait: (ref: string) => request<PortraitState>(`/sediment/people/${enc(ref)}/portrait`),
  redoPortrait: (ref: string) => request<PortraitState>(`/sediment/people/${enc(ref)}/portrait`, json("POST")),
  conversations: (ref: string) => request<ConversationRow[]>(`/sediment/people/${enc(ref)}/conversations`),
  start: (ref: string, scenario: string) => request<Conversation>(`/sediment/people/${enc(ref)}/conversations`, json("POST", { scenario })),
  conversation: (id: string) => request<Conversation>(`/sediment/conversations/${id}`),
  say: (id: string, text: string) => request<Conversation>(`/sediment/conversations/${id}/lines`, json("POST", { text })),
  retryLine: (id: string) => request<Conversation>(`/sediment/lines/${id}/retry`, json("POST")),
  removeConversation: (id: string) => request<void>(`/sediment/conversations/${id}`, { method: "DELETE" }),
};
