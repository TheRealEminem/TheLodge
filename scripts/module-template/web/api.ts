import { json, request } from "@core/api";

export interface Item {
  id: string;
  title: string;
  created_at: string;
}

export const __id__Api = {
  list: () => request<Item[]>("/__id__"),
  get: (id: string) => request<Item>(`/__id__/${id}`),
  create: (title: string) => request<{ id: string }>("/__id__", json("POST", { title })),
  remove: (id: string) => request<void>(`/__id__/${id}`, { method: "DELETE" }),
};
