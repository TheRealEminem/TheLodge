// The host's date and name helpers (core/web/format.ts), plus People's own.
export { formatDate, initials, relativeTime } from "@core/format";

export function monthKey(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long" });
}
