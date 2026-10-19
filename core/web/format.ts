// Dates and names, the same way in every module: "3 days ago", "Oct 18, 2026", "AR".
const DAY = 86_400_000;

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = now - new Date(iso).getTime();
  const days = Math.round(Math.abs(diff) / DAY);
  const future = diff < 0;
  let text: string;
  if (days === 0) return "today";
  if (days === 1) return future ? "tomorrow" : "yesterday";
  if (days < 14) text = `${days} days`;
  else if (days < 60) text = `${Math.round(days / 7)} weeks`;
  else if (days < 365 * 2) text = `${Math.round(days / 30)} months`;
  else text = `${Math.round(days / 365)} years`;
  return future ? `in ${text}` : `${text} ago`;
}

export function formatDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = {}): string {
  if (!iso) return "—";
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00`) : new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", ...opts });
}

export function initials(name: string): string {
  const parts = name.replace(/[^\p{L}\p{N}\s'-]/gu, "").trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}
