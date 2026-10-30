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

export type Asked = { unchanged: false; reading: Reading } | { unchanged: true; since: string; reading: Reading };

const enc = encodeURIComponent;

export const sedimentApi = {
  person: (ref: string) => request<PersonPage>(`/sediment/people/${enc(ref)}`),
  take: (ref: string, subject: string, again = false) => request<Asked>(`/sediment/people/${enc(ref)}/readings`, json("POST", { subject, again })),
  forget: (ref: string) => request<void>(`/sediment/people/${enc(ref)}/readings`, { method: "DELETE" }),
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
  ai: () => request<AiState & { choice: string }>("/sediment/ai"),
};
