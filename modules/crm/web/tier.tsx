// How well you know someone, shown as signal bars plus a word, so it never depends on colour alone.
import { relativeTime } from "./format";
import type { Connection, Tier } from "./api";

export const TIERS: Tier[] = ["strong", "working", "light", "indirect", "none"];

export const TIER_META: Record<Tier, { label: string; bars: number; blurb: string }> = {
  strong: { label: "Strong", bars: 4, blurb: "Close, trusted relationships" },
  working: { label: "Working", bars: 3, blurb: "People you actively work with" },
  light: { label: "Light", bars: 2, blurb: "You've met or been in touch" },
  indirect: { label: "Indirect", bars: 1, blurb: "Came up in your meetings, or known through your contacts" },
  none: { label: "Not linked", bars: 0, blurb: "Nothing links them to you yet" },
};

export function TierBars({ tier, size = 12 }: { tier: Tier; size?: number }) {
  const n = TIER_META[tier].bars;
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" className="shrink-0">
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} x={i * 3} y={9 - i * 3} width={2.2} height={3 + i * 3} rx={0.6} className={i < n ? "fill-forest" : "fill-line-strong"} />
      ))}
    </svg>
  );
}

export function TierBadge({ tier, size = "sm" }: { tier: Tier; size?: "sm" | "md" }) {
  return (
    <span data-tip={TIER_META[tier].blurb} className={`inline-flex shrink-0 items-center gap-1.5 font-medium ${size === "md" ? "text-label text-ink" : "text-meta text-ink-soft"}`}>
      <TierBars tier={tier} size={size === "md" ? 14 : 12} />
      {TIER_META[tier].label}
    </span>
  );
}

/** One line on why someone sits in their tier: "3 meetings · last 2 months ago". */
export function connectionLine(c: Connection): string {
  const parts: string[] = [];
  if (c.meetings) parts.push(`${c.meetings} meeting${c.meetings === 1 ? "" : "s"}${c.last_met_at ? ` · last ${relativeTime(c.last_met_at)}` : ""}`);
  if (c.roles.length) parts.push(c.roles[0]);
  if (!parts.length && c.context) parts.push(c.context);
  if (!parts.length && c.via.length) parts.push(`via ${c.via.slice(0, 2).map((v) => v.name).join(", ")}`);
  if (!parts.length && c.mutual.length) parts.push(`knows ${c.mutual.slice(0, 2).map((v) => v.name).join(", ")}`);
  if (!parts.length && c.mentions) parts.push(`came up ${c.mentions}×`);
  return parts.join(" · ");
}
