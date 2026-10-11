import { json, request } from "@core/api";

export interface Task {
  id: string;
  text: string;
  done: boolean;
  source_ref: string | null;
  /** Where it came from, described by that module (null if it's gone or its module is off). */
  source: { title: string; href: string; module: string } | null;
  created_at: string;
}

export const tasksApi = {
  list: () => request<Task[]>("/tasks"),
  count: () => request<{ open: number }>("/tasks/count"),
  create: (text: string) => request<{ id: string }>("/tasks", json("POST", { text })),
  setDone: (id: string, done: boolean) => request<{ ok: true }>(`/tasks/${id}`, json("PATCH", { done })),
  remove: (id: string) => request<void>(`/tasks/${id}`, { method: "DELETE" }),
};
