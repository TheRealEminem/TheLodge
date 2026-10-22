// Calendar days, the way task lists talk about them: "3 days late", "Due today", "Fri", "Oct 31".
// Days are "YYYY-MM-DD" with no time zone, read at noon local time so no clock change moves them.

const DAY = 86_400_000;

export const isoDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

export const todayIso = () => isoDay(new Date());

const noon = (iso: string) => new Date(`${iso}T12:00:00`);

/** Days from today to iso: 0 today, 1 tomorrow, -2 two days ago. */
export function daysFromToday(iso: string, today = todayIso()): number {
  return Math.round((noon(iso).getTime() - noon(today).getTime()) / DAY);
}

export function addDays(iso: string, n: number): string {
  const d = noon(iso);
  d.setDate(d.getDate() + n);
  return isoDay(d);
}

export type DueTone = "late" | "soon" | "plain";

/** What a list shows for a due day, and how loudly. Nothing for no date. */
export function dueLabel(iso: string | null, today = todayIso()): { text: string; tone: DueTone; full: string } | null {
  if (!iso) return null;
  const n = daysFromToday(iso, today);
  const d = noon(iso);
  const full = d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  if (n < -1) return { text: `${-n} days late`, tone: "late", full };
  if (n === -1) return { text: "1 day late", tone: "late", full };
  if (n === 0) return { text: "Due today", tone: "soon", full };
  if (n === 1) return { text: "Tomorrow", tone: "soon", full };
  if (n < 7) return { text: d.toLocaleDateString(undefined, { weekday: "short" }), tone: "plain", full };
  const sameYear = d.getFullYear() === noon(today).getFullYear();
  return { text: d.toLocaleDateString(undefined, { month: "short", day: "numeric", ...(sameYear ? {} : { year: "numeric" }) }), tone: "plain", full };
}

/** "45 min", "2 h", "1 h 30 min" from minutes, and back from what someone typed ("1h30", "90m", "2h", "45"). */
export function formatMinutes(min: number | null): string {
  if (min == null) return "";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return h ? (m ? `${h} h ${m} min` : `${h} h`) : `${m} min`;
}

export function parseMinutes(text: string): number | null | undefined {
  const t = text.trim().toLowerCase().replace(/\s+/g, "");
  if (!t) return null;
  const hm = t.match(/^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)(?:m|min)?)?$/);
  if (!hm || (!hm[1] && !hm[2])) return undefined; // not something we can read
  return Math.round((hm[1] ? parseFloat(hm[1]) * 60 : 0) + (hm[2] ? parseInt(hm[2], 10) : 0));
}
