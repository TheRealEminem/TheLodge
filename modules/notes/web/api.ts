import { json, request } from "@core/api";
import type { Job, Linked } from "@core/api";

export interface NoteListItem {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  job: Job | null;
}

export interface Note extends NoteListItem {
  body: string;
  summary: string | null;
  summary_by: string | null;
  links: Linked[];
}

export const notesApi = {
  list: () => request<NoteListItem[]>("/notes"),
  get: (id: string) => request<Note>(`/notes/${id}`),
  create: (title = "", body = "") => request<{ id: string }>("/notes", json("POST", { title, body })),
  patch: (id: string, changes: { title?: string; body?: string }) => request<{ ok: true }>(`/notes/${id}`, json("PATCH", changes)),
  summarize: (id: string) => request<{ ok: true }>(`/notes/${id}/summarize`, json("POST")),
  remove: (id: string) => request<void>(`/notes/${id}`, { method: "DELETE" }),
};
