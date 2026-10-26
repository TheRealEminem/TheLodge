// The rings of closeness: you at the centre, a ring for each tier (strong nearest), and the people on each ring
// gathered into wedges by group, so a group reads as a slice of the circle rather than a cloud. Nothing is laid
// out by simulation: the same book draws the same picture every time. Lines are hidden until you point at or
// choose someone, and a path from you lights up across the rings.
//
// Which groups are wedges: the ones switched on (in that order), or, with none on, the biggest organizations.
// Someone in two wedges sits in the first; everyone in no wedge is in "Everyone else".
import { useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { NetGroup, NetLink, NetNode, Tier } from "./api";
import { GROUP_META } from "./groups";
import type { Highlight } from "./NetworkCanvas";
import { TIER_META } from "./tier";

const RINGS: Tier[] = ["strong", "working", "light", "indirect", "none"];
const AUTO_WEDGES = 8;       // with no group switched on: the biggest organizations
const OTHER = "other";
const MIN_SPAN = 0.26;       // radians: the narrowest a wedge gets, so its label still fits
const LABEL_SPACING = 14;    // px between neighbours on a ring: closer than this and names are left off
const SMALL = 80;            // this many people or fewer: everyone is named
const TOP = -Math.PI / 2;    // angles run clockwise from the top
const DOT: Record<Tier, number> = { strong: 5.5, working: 5, light: 4.5, indirect: 4, none: 3.5 };

interface Placed {
  node: NetNode;
  x: number;
  y: number;
  r: number;
  angle: number;
  wedge: string;
  named: boolean;       // its name is drawn by default (the important ones are drawn regardless)
  inward: boolean;      // on the outermost ring the name sits towards the centre, clear of the wedge labels
}
interface Wedge {
  id: string;
  name: string;
  kind: NetGroup["kind"] | "other";
  start: number;
  end: number;
  count: number;
}
interface Layout {
  cx: number;
  cy: number;
  radii: number[];      // one per ring that is drawn, inner first
  rings: Tier[];
  people: Placed[];
  byId: Map<string, Placed>;
  wedges: Wedge[];
  outer: number;        // the outermost ring's radius
}

const polar = (cx: number, cy: number, r: number, a: number): [number, number] => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
const CHAR = 6.3;   // about a character's width at the label size, for fitting a label to its arc

/** A wedge's label, fitted to the arc it sits on: the count goes first, then the name is shortened. */
function fitLabel(name: string, count: number, arc: number): string {
  const room = Math.max(3, Math.floor((arc - 10) / CHAR));
  const full = `${name} · ${count}`;
  if (full.length <= room) return full;
  if (name.length <= room) return name;
  return `${name.slice(0, Math.max(1, room - 1)).trimEnd()}…`;
}

/** An annular sector from radius r0 to r1 between angles a0 and a1, as an SVG path. */
function sector(cx: number, cy: number, r0: number, r1: number, a0: number, a1: number): string {
  const large = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = polar(cx, cy, r0, a0);
  const [x1, y1] = polar(cx, cy, r0, a1);
  const [x2, y2] = polar(cx, cy, r1, a1);
  const [x3, y3] = polar(cx, cy, r1, a0);
  return `M ${x0} ${y0} A ${r0} ${r0} 0 ${large} 1 ${x1} ${y1} L ${x2} ${y2} A ${r1} ${r1} 0 ${large} 0 ${x3} ${y3} Z`;
}

function layout(nodes: NetNode[], groups: Map<string, NetGroup>, wells: string[], w: number, h: number): Layout {
  const people = nodes.filter((n) => !n.is_self);
  const ringOf = (n: NetNode) => RINGS.indexOf(n.tier ?? "none");

  // Which groups are wedges.
  let ids: string[];
  if (wells.length) ids = wells.filter((g) => groups.has(g));
  else {
    const count = new Map<string, number>();
    for (const p of people) for (const g of p.groups) if (groups.get(g)?.kind === "organization") count.set(g, (count.get(g) ?? 0) + 1);
    ids = [...count.entries()].filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1] || (groups.get(a[0])?.name ?? "").localeCompare(groups.get(b[0])?.name ?? "")).slice(0, AUTO_WEDGES).map(([g]) => g);
  }
  const wedgeOf = (n: NetNode) => ids.find((g) => n.groups.includes(g)) ?? OTHER;
  const members = new Map<string, NetNode[]>();
  for (const p of people) {
    const g = wedgeOf(p);
    members.set(g, [...(members.get(g) ?? []), p]);
  }
  const order = [...ids.filter((g) => members.has(g)), ...(members.has(OTHER) ? [OTHER] : [])];

  // Each wedge's share of the circle: by how many people it holds, with a floor so its label fits.
  const total = people.length || 1;
  let spans = order.map((g) => Math.max(MIN_SPAN, (2 * Math.PI * (members.get(g)?.length ?? 0)) / total));
  const sum = spans.reduce((a, b) => a + b, 0);
  spans = spans.map((s) => (s * 2 * Math.PI) / sum);
  const wedges: Wedge[] = [];
  let at = TOP;
  order.forEach((g, i) => {
    const group = groups.get(g);
    wedges.push({ id: g, name: g === OTHER ? "Everyone else" : group?.name ?? g, kind: g === OTHER ? "other" : group?.kind ?? "tag", start: at, end: at + spans[i], count: members.get(g)?.length ?? 0 });
    at += spans[i];
  });

  // Rings: the four tiers, and "not linked" only when someone is there.
  const used = Math.max(3, ...people.map(ringOf));
  const rings = RINGS.slice(0, used + 1);
  const margin = order.length > 1 || order[0] !== OTHER ? 66 : 36;   // room outside for the wedge labels
  const R = Math.max(80, Math.min(w, h) / 2 - margin);
  const radii = rings.map((_, k) => (R * (k + 1)) / rings.length);
  const cx = w / 2;
  const cy = h / 2;

  const placed: Placed[] = [];
  const small = people.length <= SMALL;
  for (const wedge of wedges) {
    const pad = (wedge.end - wedge.start) * 0.08;
    const span = wedge.end - wedge.start - 2 * pad;
    for (let k = 0; k < rings.length; k++) {
      const onRing = (members.get(wedge.id) ?? []).filter((p) => ringOf(p) === k).sort((a, b) => b.degree - a.degree || a.name.localeCompare(b.name));
      if (!onRing.length) continue;
      const spacing = (radii[k] * span) / onRing.length;
      const crowded = spacing < 11;
      onRing.forEach((p, i) => {
        const angle = wedge.start + pad + (span * (i + 0.5)) / onRing.length;
        const r = radii[k] + (crowded ? (i % 2 ? 6 : -6) : 0);
        const [x, y] = polar(cx, cy, r, angle);
        const tier = p.tier ?? "none";
        const named = small || ((tier === "strong" || tier === "working" || wells.includes(wedge.id)) && spacing >= LABEL_SPACING);
        placed.push({ node: p, x, y, r: DOT[tier], angle, wedge: wedge.id, named, inward: k === rings.length - 1 && rings.length > 1 });
      });
    }
  }
  return { cx, cy, radii, rings, people: placed, byId: new Map(placed.map((p) => [p.node.id, p])), wedges, outer: radii[radii.length - 1] };
}

export default function NetworkRings({ nodes, links, groups, wells, me, selectedId, picked, highlight, hoverWell, inset = 0, onNodeClick, onBackgroundClick, onOpenGroup }: {
  nodes: NetNode[];
  links: NetLink[];
  groups: Map<string, NetGroup>;
  wells: string[];
  me: NetNode | null;
  selectedId?: string | null;
  picked?: Set<string>;
  highlight?: Highlight | null;
  hoverWell?: string | null;
  /** Pixels at the right edge covered by a panel: the rings centre in the rest. */
  inset?: number;
  onNodeClick?: (n: NetNode, e: MouseEvent) => void;
  onBackgroundClick?: () => void;
  onOpenGroup?: (gid: string) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 600, h: 500 });
  const [hover, setHover] = useState<string | null>(null);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const lay = useMemo(() => layout(nodes, groups, wells, Math.max(200, size.w - inset), size.h), [nodes, groups, wells, size.w, size.h, inset]);
  const linksOf = useMemo(() => {
    const m = new Map<string, NetLink[]>();
    for (const l of links) {
      m.set(l.source, [...(m.get(l.source) ?? []), l]);
      m.set(l.target, [...(m.get(l.target) ?? []), l]);
    }
    return m;
  }, [links]);

  const focusIds = new Set([hover, selectedId].filter((x): x is string => Boolean(x)));
  const shownLinks = useMemo(() => {
    const out = new Map<string, NetLink>();
    for (const id of focusIds) for (const l of linksOf.get(id) ?? []) out.set(l.id, l);
    return [...out.values()];
  }, [linksOf, hover, selectedId]); // eslint-disable-line react-hooks/exhaustive-deps
  const neighbours = new Set(shownLinks.flatMap((l) => [l.source, l.target]));
  const meId = me?.id ?? null;

  // Someone steps back when a path, a pointed-at group or the switched-on groups leave them out.
  const faded = (p: Placed) => {
    if (focusIds.has(p.node.id) || picked?.has(p.node.id)) return false;
    if (highlight && highlight.nodes.size > 0 && !highlight.nodes.has(p.node.id)) return true;
    if (hoverWell && p.wedge !== hoverWell) return true;
    if (focusIds.size && !neighbours.has(p.node.id)) return true;
    if (wells.length && p.wedge === OTHER) return true;
    return false;
  };
  const fill = (tier: Tier | null) => (tier === "strong" ? "fill-forest" : tier === "working" ? "fill-forest/55" : tier === "light" ? "fill-surface stroke-forest" : "fill-surface stroke-ink-soft");
  const pos = (id: string): [number, number] | null => (id === meId ? [lay.cx, lay.cy] : lay.byId.get(id) ? [lay.byId.get(id)!.x, lay.byId.get(id)!.y] : null);
  const hovered = hover ? lay.byId.get(hover) ?? null : null;
  const fontPx = 11;

  return (
    <div ref={wrap} className="relative h-full w-full overflow-hidden">
      <svg width={size.w} height={size.h} className="block select-none" role="img" aria-label="Your people, closest at the centre, gathered by group">
        <rect width={size.w} height={size.h} fill="transparent" onClick={() => onBackgroundClick?.()} />

        {/* Wedges: one slice per group, labelled outside the rings. */}
        {lay.wedges.map((wd) => {
          const on = wells.includes(wd.id) || hoverWell === wd.id;
          const mid = (wd.start + wd.end) / 2;
          const bottom = Math.sin(mid) > 0;
          const labelR = lay.outer + 22;
          const [lx, ly] = polar(lay.cx, lay.cy, labelR, mid);
          const rot = (mid * 180) / Math.PI + (bottom ? -90 : 90);
          const label = fitLabel(wd.name, wd.count, (wd.end - wd.start) * labelR);
          const dash = wd.kind === "other" ? undefined : GROUP_META[wd.kind].dash.join(" ") || undefined;
          return (
            <g key={wd.id} opacity={hoverWell && hoverWell !== wd.id ? 0.35 : 1}>
              {wd.id !== OTHER && (
                <path d={sector(lay.cx, lay.cy, lay.radii[0] * 0.45, lay.outer + 8, wd.start, wd.end)} className={`fill-forest stroke-forest ${on ? "opacity-[.13]" : "opacity-[.055]"}`} strokeDasharray={dash} strokeWidth={1} />
              )}
              {lay.wedges.length > 1 && (
                <text
                  x={lx}
                  y={ly}
                  transform={`rotate(${rot} ${lx} ${ly})`}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className={`${wd.id === OTHER ? "fill-ink-faint" : "fill-ink-soft cursor-pointer hover:fill-ink"} text-meta font-medium`}
                  onClick={() => wd.id !== OTHER && onOpenGroup?.(wd.id)}
                >
                  <title>{wd.name} · {wd.count}</title>
                  {label}
                </text>
              )}
            </g>
          );
        })}

        {/* The rings, each named at the top. */}
        {lay.radii.map((r, k) => (
          <g key={lay.rings[k]}>
            <circle cx={lay.cx} cy={lay.cy} r={r} className="fill-none stroke-line" strokeWidth={1} strokeDasharray={lay.rings[k] === "none" ? "2 4" : undefined} />
            <text x={lay.cx} y={lay.cy - r} textAnchor="middle" dominantBaseline="middle" className="fill-ink-faint text-caption" style={{ paintOrder: "stroke", stroke: "var(--surface-solid)", strokeWidth: 4, strokeLinejoin: "round" }}>{TIER_META[lay.rings[k]].label}</text>
          </g>
        ))}

        {/* Lines: the path from you, and the ties of whoever is pointed at or chosen. */}
        {highlight && highlight.links.size > 0 && links.filter((l) => highlight.links.has(l.id)).map((l) => {
          const a = pos(l.source);
          const b = pos(l.target);
          return a && b ? <line key={`h${l.id}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className="stroke-forest" strokeWidth={2.5} strokeLinecap="round" /> : null;
        })}
        {shownLinks.map((l) => {
          const a = pos(l.source);
          const b = pos(l.target);
          if (!a || !b || highlight?.links.has(l.id)) return null;
          return <line key={l.id} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} className={l.basis === "direct" ? "stroke-forest" : "stroke-line-strong"} strokeWidth={0.8 + l.weight * 0.35} strokeDasharray={l.basis === "mentioned" ? "2 3" : undefined} strokeLinecap="round" />;
        })}

        {/* People. */}
        {lay.people.map((p) => {
          const id = p.node.id;
          const important = focusIds.has(id) || picked?.has(id) || Boolean(highlight?.nodes.has(id));
          const dim = faded(p);
          const cos = Math.cos(p.angle);
          const sin = Math.sin(p.angle);
          const out = p.inward ? -1 : 1;   // which way from the dot the name goes: away from the centre, or towards it
          const side = cos * out > 0.3 ? "start" : cos * out < -0.3 ? "end" : "middle";
          const lx = p.x + (side === "start" ? p.r + 4 : side === "end" ? -(p.r + 4) : 0);
          const ly = side === "middle" ? p.y + (sin * out < 0 ? -(p.r + 4) : p.r + 4 + fontPx * 0.8) : p.y + fontPx * 0.35;
          return (
            <g key={id} opacity={dim ? 0.22 : 1} className="cursor-pointer" onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover((h) => (h === id ? null : h))} onClick={(e: ReactMouseEvent) => onNodeClick?.(p.node, e.nativeEvent)}>
              <circle cx={p.x} cy={p.y} r={p.r + 6} fill="transparent" />
              {(picked?.has(id) || id === selectedId) && <circle cx={p.x} cy={p.y} r={p.r + 3.5} className="fill-none stroke-ink" strokeWidth={id === selectedId ? 1.5 : 2.2} />}
              <circle cx={p.x} cy={p.y} r={p.r} className={fill(p.node.tier)} strokeWidth={1.6} strokeDasharray={p.node.tier === "indirect" || p.node.tier === "none" || !p.node.tier ? "2 2" : undefined} />
              {(p.named || important) && !dim && (
                <text x={lx} y={ly} textAnchor={side} className={`${important ? "fill-ink font-semibold" : "fill-ink"} pointer-events-none`} style={{ fontSize: fontPx, paintOrder: "stroke", stroke: "var(--surface-solid)", strokeWidth: 3, strokeLinejoin: "round" }}>
                  {p.node.name}
                </text>
              )}
            </g>
          );
        })}

        {/* You, in the middle. */}
        <g>
          <circle cx={lay.cx} cy={lay.cy} r={11} className="fill-forest" />
          <text x={lay.cx} y={lay.cy + 25} textAnchor="middle" className="fill-ink font-semibold" style={{ fontSize: fontPx, paintOrder: "stroke", stroke: "var(--surface-solid)", strokeWidth: 3 }}>{me ? "You" : "You (not set yet)"}</text>
        </g>
      </svg>

      {hovered && (
        <div className="panel pointer-events-none absolute z-10 max-w-64 px-3 py-2 shadow-lg" style={{ left: Math.min(hovered.x + 14, size.w - 260), top: hovered.y + 14 }}>
          <div className="text-ui font-medium">{hovered.node.name}</div>
          {hovered.node.subtitle && <div className="text-hint text-ink-soft">{hovered.node.subtitle}</div>}
          <div className="mt-0.5 text-meta text-ink-soft">
            {hovered.node.tier ? `${TIER_META[hovered.node.tier].label} · ` : ""}
            {hovered.node.degree} connection{hovered.node.degree === 1 ? "" : "s"}
          </div>
          {hovered.node.groups.length > 0 && (
            <div className="mt-0.5 text-meta text-ink-soft">
              In {hovered.node.groups.slice(0, 4).map((g) => groups.get(g)?.name ?? g).join(", ")}
              {hovered.node.groups.length > 4 ? ` and ${hovered.node.groups.length - 4} more` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
