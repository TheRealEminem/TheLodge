// How a group (organization, topic or tag) looks and reads. Identity is the label plus the outline style, never
// a colour of its own: solid ring = organization, dashed = topic, dotted = tag.
import type { GroupKind, NetGroup } from "./api";

export const GROUP_META: Record<GroupKind, { one: string; many: string; dash: number[]; verb: string }> = {
  organization: { one: "Organization", many: "Organizations", dash: [], verb: "works there" },
  topic: { one: "Topic", many: "Topics", dash: [6, 4], verb: "took part or came up" },
  tag: { one: "Tag", many: "Tags", dash: [1.5, 3.5], verb: "tagged" },
};

export const GROUP_ORDER: GroupKind[] = ["organization", "topic", "tag"];

/** The outline style as a small swatch, for chips, lists and the legend. */
export function GroupGlyph({ kind, size = 14, className = "" }: { kind: GroupKind; size?: number; className?: string }) {
  const dash = GROUP_META[kind].dash;
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" className={`shrink-0 ${className}`}>
      <rect x="1.2" y="1.2" width="11.6" height="11.6" rx="5" fill="currentColor" fillOpacity="0.1" stroke="currentColor" strokeWidth="1.4"
        strokeDasharray={dash.length ? dash.map((d) => d * 0.8).join(" ") : undefined} strokeLinecap="round" />
    </svg>
  );
}

export function groupMap(groups: NetGroup[] | undefined): Map<string, NetGroup> {
  return new Map((groups ?? []).map((g) => [g.id, g]));
}
