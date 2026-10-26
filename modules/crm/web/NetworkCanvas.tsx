// The people network on a canvas: people are the only nodes; the lines between them are connections; groups are
// gravity wells (invisible anchors that pull their members together, with a soft labelled outline behind them).
// Meetings and documents appear only as small satellites around the person you've selected.
//
// Where everyone sits is remembered per view (which groups are on, who's in focus) so the map looks the same next
// time: a remembered layout pins people where they settled, new people find room among them, and "Lay out again"
// starts fresh. The wheel scrolls the page; zooming takes ⌘ or Ctrl with it, a pinch, or the buttons.
import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";
import { Minus, Scan } from "lucide-react";
import { PlusIcon, RefreshIcon, icon } from "@core/components/icons";
import { useShell } from "@core/shell";
import type { Evidence, NetGroup, NetLink, NetNode } from "./api";
import { GROUP_META } from "./groups";
import { fillFor, readColors, tracePath } from "./graphShapes";
import type { Colors, Shape } from "./graphShapes";
import { TIER_META } from "./tier";

export interface Highlight {
  nodes: Set<string>;
  links: Set<string>;
}

interface CNode {
  id: string;
  kind: "person" | "well" | "event";
  r: number;
  person?: NetNode;
  gid?: string;
  event?: Evidence;
}
interface CLink {
  id: string;
  type: "tie" | "well" | "event";
  tie?: NetLink;
}
type N = NodeObject<CNode>;
type L = LinkObject<CNode, CLink>;

function radius(n: NetNode): number {
  return Math.min(4.5 + Math.sqrt(n.degree) * 1.2, 12) + (n.is_self ? 3 : 0);
}

/** Convex hull (monotone chain) of points. */
function hull(points: [number, number][]): [number, number][] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (pts.length < 3) return pts;
  const cross = (o: [number, number], a: [number, number], b: [number, number]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: [number, number][] = [];
  for (const p of pts) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) lower.pop();
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (const p of [...pts].reverse()) {
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) upper.pop();
    upper.push(p);
  }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

/** A rounded outline around the members: a hull of circles around each one, drawn through the edge midpoints. */
function tracePool(ctx: CanvasRenderingContext2D, members: { x: number; y: number }[], pad: number): { top: number; cx: number } {
  const around: [number, number][] = [];
  for (const m of members) for (let i = 0; i < 10; i++) around.push([m.x + pad * Math.cos((i * Math.PI) / 5), m.y + pad * Math.sin((i * Math.PI) / 5)]);
  const h = hull(around);
  const mid = (a: [number, number], b: [number, number]): [number, number] => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  ctx.beginPath();
  const start = mid(h[h.length - 1], h[0]);
  ctx.moveTo(start[0], start[1]);
  for (let i = 0; i < h.length; i++) {
    const m = mid(h[i], h[(i + 1) % h.length]);
    ctx.quadraticCurveTo(h[i][0], h[i][1], m[0], m[1]);
  }
  ctx.closePath();
  return { top: Math.min(...h.map((p) => p[1])), cx: members.reduce((s, m) => s + m.x, 0) / members.length };
}

const MinusIcon = icon(Minus);
const ScanIcon = icon(Scan);

type Pos = { x: number; y: number };
const LAYOUTS = "lodge.network.layouts";   // localStorage: {namespace: {viewKey: {t, at: {id: {x, y}}}}}
const MAX_LAYOUTS = 24;                    // per namespace; the oldest go first

function loadLayouts(ns: string): Map<string, Map<string, Pos>> {
  const out = new Map<string, Map<string, Pos>>();
  try {
    const mine = (JSON.parse(localStorage.getItem(LAYOUTS) ?? "{}") as Record<string, Record<string, { t: number; at: Record<string, Pos> }>>)[ns] ?? {};
    for (const [key, v] of Object.entries(mine)) out.set(key, new Map(Object.entries(v.at)));
  } catch {
    /* private window, or storage cleared: start fresh */
  }
  return out;
}

function storeLayout(ns: string, key: string, at: Record<string, Pos> | null) {
  try {
    const all = JSON.parse(localStorage.getItem(LAYOUTS) ?? "{}") as Record<string, Record<string, { t: number; at: Record<string, Pos> }>>;
    const mine = all[ns] ?? {};
    if (at) mine[key] = { t: Date.now(), at };
    else delete mine[key];
    for (const k of Object.keys(mine).sort((a, b) => mine[b].t - mine[a].t).slice(MAX_LAYOUTS)) delete mine[k];
    all[ns] = mine;
    localStorage.setItem(LAYOUTS, JSON.stringify(all));
  } catch {
    /* nothing to remember with */
  }
}

/** "Amara Diallo" -> "Amara D.", for a crowded map. */
const shortName = (name: string) => {
  const parts = name.trim().split(/\s+/);
  return parts.length > 1 ? `${parts[0]} ${parts[parts.length - 1][0]}.` : name;
};

const TIER_RANK: Record<string, number> = { strong: 1, working: 2, light: 3, indirect: 4, none: 5 };

const linkEnd = (end: L["source"]): string => (typeof end === "object" && end !== null ? String((end as N).id) : String(end));

const EVENT_SHAPE: Record<Evidence["kind"], Shape> = { meeting: "diamond", document: "page" };

export default function NetworkCanvas({
  nodes, links, groups, wells, showMe, evidence, selectedId, picked, focusId, highlight, hoverWell, height, labels = "auto", remember, inset = 0,
  onNodeClick, onEventClick, onBackgroundClick,
}: {
  nodes: NetNode[];
  links: NetLink[];
  groups: Map<string, NetGroup>;
  wells: string[]; // group ids switched on
  showMe: boolean;
  evidence?: Evidence[] | null; // the selected person's meetings and documents
  selectedId?: string | null;
  picked?: Set<string>;
  focusId?: string | null;
  highlight?: Highlight | null;
  hoverWell?: string | null;
  height?: number;
  labels?: "auto" | "all";
  /** Keep where people settled, under this name, so the same view looks the same next time. */
  remember?: string;
  /** Pixels at the right edge covered by a panel: the map fits and centres in the rest. */
  inset?: number;
  onNodeClick?: (n: NetNode, e: MouseEvent) => void;
  onEventClick?: (e: Evidence) => void;
  onBackgroundClick?: () => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined);
  const [size, setSize] = useState({ w: 300, h: height ?? 300 });
  const [hover, setHover] = useState<{ node: CNode; x: number; y: number } | null>(null);
  const { theme } = useShell();
  const colors = useMemo(() => readColors(), [theme.dusk]);
  const positions = useRef(new Map<string, { x?: number; y?: number }>()); // where everyone was last: the starting point for a new arrangement
  const [layouts] = useState(() => (remember ? loadLayouts(remember) : new Map<string, Map<string, Pos>>())); // settled arrangements, per view
  const [relayout, setRelayout] = useState(0);   // bumped by "Lay out again"
  const viewKey = `${focusId ?? ""}|${wells.join(",")}|${showMe}`;
  const labelBoxes = useRef<{ x0: number; x1: number; y0: number; y1: number }[]>([]); // labels drawn this frame, so they don't pile up
  const fitted = useRef("");
  const touched = useRef(false); // you've panned or zoomed yourself: stop re-fitting the view after each layout
  const reduce = useMemo(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false, []);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: height ?? e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  // force-graph mutates what it's given, so build fresh objects, but start each from where it was last laid out.
  const data = useMemo(() => {
    const people = nodes.filter((n) => showMe || !n.is_self || n.id === selectedId || highlight?.nodes.has(n.id));
    // Drawn in this order, so when labels crowd each other the people who matter most keep theirs.
    people.sort((a, b) => Number(b.is_self) - Number(a.is_self) || (TIER_RANK[a.tier ?? "none"] ?? 5) - (TIER_RANK[b.tier ?? "none"] ?? 5) || b.degree - a.degree || a.name.localeCompare(b.name));
    const present = new Set(people.map((n) => n.id));
    const cn: CNode[] = people.map((n) => ({ id: n.id, kind: "person", r: radius(n), person: n }));
    const cl: { source: string; target: string; id: string; type: CLink["type"]; tie?: NetLink }[] = [];
    for (const l of links) if (present.has(l.source) && present.has(l.target)) cl.push({ id: l.id, source: l.source, target: l.target, type: "tie", tie: l });

    for (const gid of wells) {
      const members = people.filter((n) => n.groups.includes(gid));
      if (!members.length) continue;
      const anchor = `well:${gid}`;
      cn.push({ id: anchor, kind: "well", r: 0, gid });
      for (const m of members) cl.push({ id: `${anchor}>${m.id}`, source: m.id, target: anchor, type: "well" });
    }

    for (const ev of (evidence ?? []).slice(0, 14)) {
      const id = `event:${ev.id}`;
      cn.push({ id, kind: "event", r: 3.8, event: ev });
      if (selectedId && present.has(selectedId)) cl.push({ id: `${id}>${selectedId}`, source: id, target: selectedId, type: "event" });
      for (const p of ev.people) if (present.has(p) && p !== selectedId) cl.push({ id: `${id}>${p}`, source: id, target: p, type: "event" });
    }
    // Wells start at the middle of their members, and every node at its previous place.
    const placed = new Map(cn.map((n) => [n.id, positions.current.get(n.id)]));
    for (const n of cn) {
      if (n.kind === "well") {
        const own = cl.filter((l) => l.target === n.id).map((l) => placed.get(String(l.source))).filter((p): p is { x: number; y: number } => p?.x !== undefined);
        if (own.length && !placed.get(n.id)) placed.set(n.id, { x: own.reduce((s, p) => s + (p.x ?? 0), 0) / own.length, y: own.reduce((s, p) => s + (p.y ?? 0), 0) / own.length });
      }
    }
    // A remembered arrangement for this view pins everyone where they settled; anyone new finds room among them.
    const kept = layouts.get(viewKey);
    const placedNodes = cn.map((n) => {
      const k = kept?.get(n.id);
      return k ? { ...n, x: k.x, y: k.y, fx: k.x, fy: k.y } : { ...n, ...placed.get(n.id) };
    }) as N[];
    return { nodes: placedNodes, links: cl as unknown as L[], people: people.length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, links, wells, showMe, evidence, selectedId, highlight, viewKey, relayout]);

  const members = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const gid of wells) m.set(gid, new Set(nodes.filter((n) => n.groups.includes(gid)).map((n) => n.id)));
    return m;
  }, [nodes, wells]);

  useEffect(() => {
    const f = fg.current;
    if (!f) return;
    f.d3Force("charge")?.strength((n: N) => (n.kind === "well" ? -900 : n.kind === "event" ? -45 : -130));
    const link = f.d3Force("link");
    link?.distance((l: L) => (l.type === "well" ? 26 : l.type === "event" ? 42 : Math.max(38, 86 - (l.tie?.weight ?? 1) * 9)));
    link?.strength((l: L) => (l.type === "well" ? 0.4 : l.type === "event" ? 0.2 : 0.16));
    // A faint pull to the middle keeps loose people and separate groups from drifting off.
    f.d3Force("gravity", (alpha: number) => {
      for (const n of data.nodes) {
        const k = (n.kind === "well" ? 0.02 : 0.03) * alpha;
        n.vx = (n.vx ?? 0) - (n.x ?? 0) * k;
        n.vy = (n.vy ?? 0) - (n.y ?? 0) * k;
      }
    });
    f.d3ReheatSimulation();
  }, [data]);

  useEffect(() => {
    if (!focusId) return;
    const t = setTimeout(() => {
      const n = data.nodes.find((d) => d.id === focusId);
      if (n?.x !== undefined && n.y !== undefined) {
        fg.current?.centerAt(n.x, n.y, reduce ? 0 : 600);
        fg.current?.zoom(1.5, reduce ? 0 : 600);
      }
    }, 900);
    return () => clearTimeout(t);
  }, [focusId, data, reduce]);

  // Fit the people in the groups (all people when none are on), with room for the group labels.
  const fit = () => {
    const g = fg.current;
    if (focusId || !g) return;
    const ms = reduce ? 0 : 500;
    const pad = height ? (wells.length ? 52 : 36) : wells.length ? 90 : 56;
    const shown = (n: NodeObject) => (n as N).kind === "person" && (!wells.length || wells.some((w) => members.get(w)?.has(String(n.id))));
    if (!inset || inset >= size.w) return g.zoomToFit(ms, pad, shown);
    // A panel covers the right edge: fit the people into what's left, and centre them there.
    g.zoomToFit(0, pad, shown);
    g.zoom((g.zoom() * (size.w - inset)) / size.w, 0);
    const c = g.screen2GraphCoords(size.w / 2 + inset / 2, size.h / 2);
    g.centerAt(c.x, c.y, ms);
  };
  // Keep the fit when the canvas changes size or a panel covers part of it, until you've panned or zoomed yourself.
  useEffect(() => {
    if (!touched.current) fit();
  }, [size.w, size.h, inset]); // eslint-disable-line react-hooks/exhaustive-deps
  // Someone chosen under the panel is brought into the open.
  useEffect(() => {
    if (!selectedId || !inset) return;
    const t = setTimeout(() => {
      const g = fg.current;
      const n = data.nodes.find((d) => d.id === selectedId);
      if (!g || !n || n.x === undefined || n.y === undefined) return;
      const p = g.graph2ScreenCoords(n.x, n.y);
      if (p.x < size.w - inset - 24) return;
      const c = g.screen2GraphCoords(size.w / 2 - ((size.w - inset) / 2 - p.x), size.h / 2);
      g.centerAt(c.x, c.y, reduce ? 0 : 400);
    }, 350);
    return () => clearTimeout(t);
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const zoomBy = (f: number) => {
    const g = fg.current;
    if (!g) return;
    touched.current = true;
    g.zoom(g.zoom() * f, reduce ? 0 : 250);
  };
  const layOutAgain = () => {
    layouts.delete(viewKey);
    if (remember) storeLayout(remember, viewKey, null);
    for (const n of data.nodes) positions.current.delete(String(n.id));
    touched.current = false;
    setRelayout((n) => n + 1);
  };

  const dimmed = (id: string) => {
    if (highlight && highlight.nodes.size > 0 && !highlight.nodes.has(id)) return true;
    // With groups on, people outside all of them step back so the groups read clearly.
    if (wells.length && id !== selectedId && !wells.some((w) => members.get(w)?.has(id))) return true;
    if (hoverWell && !members.get(hoverWell)?.has(id)) return members.has(hoverWell);
    return false;
  };

  const inAnyWell = (id: string) => wells.some((w) => members.get(w)?.has(id));

  const drawPools = (ctx: CanvasRenderingContext2D, scale: number) => {
    const byId = new Map(data.nodes.map((n) => [n.id, n]));
    const taken: { x0: number; x1: number; y0: number; y1: number }[] = []; // labels already placed this frame
    for (const gid of wells) {
      const group = groups.get(gid);
      const ids = members.get(gid);
      if (!group || !ids) continue;
      const pts = [...ids].map((id) => byId.get(id)).filter((n): n is N => Boolean(n && n.x !== undefined && n.y !== undefined)) as (N & { x: number; y: number })[];
      if (!pts.length) continue;
      const emphasised = hoverWell === gid || Boolean(selectedId && ids.has(selectedId));
      const faded = Boolean(hoverWell && hoverWell !== gid);
      const { top, cx } = tracePool(ctx, pts, 17);
      ctx.fillStyle = colors.forest;
      ctx.globalAlpha = faded ? 0.03 : emphasised ? 0.14 : 0.075;
      ctx.fill();
      ctx.globalAlpha = faded ? 0.18 : emphasised ? 0.95 : 0.6;
      ctx.strokeStyle = colors.forest;
      ctx.lineWidth = (emphasised ? 1.9 : 1.3) / scale;
      ctx.setLineDash(GROUP_META[group.kind].dash.map((d) => d / scale));
      ctx.stroke();
      ctx.setLineDash([]);
      // The label sits just above the outline.
      const px = Math.min(Math.max(12 / scale, 3), 30);
      ctx.globalAlpha = faded ? 0.3 : 1;
      ctx.font = `600 ${px}px system-ui, -apple-system, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.lineJoin = "round";
      // Two groups can share a top edge: stack their labels instead of printing one over the other.
      const half = ctx.measureText(group.name).width / 2;
      let ly = top - 3 / scale;
      while (taken.some((t) => cx + half > t.x0 && cx - half < t.x1 && ly > t.y0 && ly - px < t.y1)) ly -= px * 1.2;
      taken.push({ x0: cx - half, x1: cx + half, y0: ly - px, y1: ly });
      ctx.lineWidth = 3 / scale;
      ctx.strokeStyle = colors.surface;
      ctx.strokeText(group.name, cx, ly);
      ctx.fillStyle = colors.soft;
      ctx.fillText(group.name, cx, ly);
      ctx.globalAlpha = 1;
    }
  };

  return (
    <div ref={wrap} className="relative h-full w-full overflow-hidden" style={height ? { height } : undefined} onWheel={(e) => { if (e.ctrlKey || e.metaKey) touched.current = true; }} onMouseMove={(e) => { if (e.buttons === 1) touched.current = true; }}>
      <ForceGraph2D<CNode, CLink>
        ref={fg}
        graphData={data}
        width={size.w}
        height={size.h}
        cooldownTicks={150}
        warmupTicks={20}
        enableZoomInteraction={(ev) => ev.ctrlKey || ev.metaKey} // a plain wheel scrolls the page; ⌘/Ctrl with it, or a pinch, zooms
        onEngineStop={() => {
          const at: Record<string, Pos> = {};
          for (const n of data.nodes) {
            positions.current.set(String(n.id), { x: n.x, y: n.y });
            if (n.kind !== "event" && n.x !== undefined && n.y !== undefined) at[String(n.id)] = { x: Math.round(n.x * 10) / 10, y: Math.round(n.y * 10) / 10 };
          }
          layouts.set(viewKey, new Map(Object.entries(at)));
          if (remember) storeLayout(remember, viewKey, at);
          const key = `${viewKey}|${nodes.length}`;
          if (fitted.current !== key) touched.current = false;
          fitted.current = key;
          if (!touched.current) fit();
        }}
        onRenderFramePre={(ctx, scale) => { labelBoxes.current = []; drawPools(ctx, scale); }}
        linkVisibility={(l) => l.type !== "well" && (l.type === "event" || !wells.length || inAnyWell(linkEnd(l.source)) || inAnyWell(linkEnd(l.target)))}
        linkColor={(l) => (highlight?.links.has(l.id) ? colors.forest : l.type === "event" ? colors.faint : colors.edge)}
        linkWidth={(l) => (highlight?.links.has(l.id) ? 2.6 : l.type === "event" ? 0.6 : 0.5 + (l.tie?.weight ?? 1) * 0.3)}
        linkLineDash={(l) => (l.type === "event" ? [2, 2] : l.tie?.basis === "mentioned" ? [1.5, 2.5] : null)}
        nodeVisibility={(n) => n.kind !== "well"}
        nodeCanvasObject={(node, ctx, scale) => {
          const n = node as N;
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          if (n.kind === "event" && n.event) return drawEvent(ctx, n, x, y, scale, colors);
          const person = n.person;
          if (!person) return;
          const r = n.r;
          const faded = dimmed(n.id);
          const base = faded ? 0.18 : 1;
          ctx.globalAlpha = base;
          // A surface-coloured halo keeps overlapping nodes legible.
          ctx.beginPath();
          tracePath(ctx, "circle", x, y, r + 2 / scale);
          ctx.fillStyle = colors.surface;
          ctx.fill();

          const fill = fillFor("person", person.tier, person.is_self);
          ctx.beginPath();
          tracePath(ctx, "circle", x, y, r);
          if (fill === "solid") {
            ctx.fillStyle = colors.forest;
            ctx.fill();
          } else if (fill === "tint") {
            ctx.fillStyle = colors.forest;
            ctx.globalAlpha = base * 0.55;
            ctx.fill();
            ctx.globalAlpha = base;
          } else {
            ctx.strokeStyle = fill === "ring" ? colors.forest : colors.soft;
            ctx.lineWidth = 1.6 / scale;
            if (fill === "dotted") ctx.setLineDash([2 / scale, 2 / scale]);
            ctx.stroke();
            ctx.setLineDash([]);
          }

          if (picked?.has(n.id)) {
            ctx.beginPath();
            tracePath(ctx, "circle", x, y, r + 3.2 / scale);
            ctx.strokeStyle = colors.ink;
            ctx.lineWidth = 2.2 / scale;
            ctx.stroke();
          }
          if (n.id === selectedId) {
            ctx.beginPath();
            tracePath(ctx, "circle", x, y, r + 3.5 / scale);
            ctx.strokeStyle = colors.ink;
            ctx.lineWidth = 1.5 / scale;
            ctx.stroke();
          }

          const important = person.is_self || n.id === selectedId || n.id === focusId || highlight?.nodes.has(n.id) || picked?.has(n.id);
          const inWell = wells.some((w) => person.groups.includes(w));
          const close = person.tier === "strong" || person.tier === "working";
          // A small map names everyone. A big one names the people who matter (you, the selection, a path, group
          // members, close ties, hubs) first and the rest as you zoom in; a crowded map shortens names, and a name
          // that would land on another is left off, the important ones excepted.
          const wanted = labels === "all" || important || data.people <= 80 || scale >= 1.8 || (scale >= 0.8 && (inWell || close)) || (scale >= 0.9 && person.degree >= 8);
          if (wanted && !faded) {
            const crowded = data.people > 40 && scale < 1.4;
            const text = crowded && !important ? shortName(person.name) : person.name;
            const px = Math.max(11 / scale, 2);
            ctx.font = `${important ? 600 : 500} ${px}px system-ui, -apple-system, sans-serif`;
            const w = ctx.measureText(text).width;
            const ty = y + r + 3 / scale;
            const box = { x0: x - w / 2, x1: x + w / 2, y0: ty, y1: ty + px };
            const clash = labelBoxes.current.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0);
            if (!clash || important) {
              labelBoxes.current.push(box);
              ctx.textAlign = "center";
              ctx.textBaseline = "top";
              ctx.lineWidth = 3 / scale;
              ctx.strokeStyle = colors.surface;
              ctx.lineJoin = "round";
              ctx.strokeText(text, x, ty);
              ctx.fillStyle = colors.ink;
              ctx.fillText(text, x, ty);
            }
          }
          ctx.globalAlpha = 1;
        }}
        nodePointerAreaPaint={(node, color, ctx, scale) => {
          const n = node as N;
          ctx.beginPath();
          ctx.arc(n.x ?? 0, n.y ?? 0, Math.max(n.r + 4 / scale, 12 / scale), 0, Math.PI * 2); // a bigger target than the mark
          ctx.fillStyle = color;
          ctx.fill();
        }}
        onNodeHover={(node) => {
          if (!node) return setHover(null);
          const n = node as N;
          const p = fg.current?.graph2ScreenCoords(n.x ?? 0, n.y ?? 0);
          setHover({ node: n, x: p?.x ?? 0, y: p?.y ?? 0 });
          if (wrap.current) wrap.current.style.cursor = "pointer";
        }}
        onNodeClick={(node, event) => {
          const n = node as N;
          if (n.person) onNodeClick?.(n.person, event);
          else if (n.event) onEventClick?.(n.event);
        }}
        onBackgroundClick={() => {
          if (wrap.current) wrap.current.style.cursor = "default";
          onBackgroundClick?.();
        }}
        onZoom={() => hover && setHover(null)} // only when there is one to clear: the graph calls this while mounting, inside its own render
      />
      <div className="panel absolute left-3 top-3 z-10 flex flex-col p-0.5 shadow-md" role="group" aria-label="Zoom">
        <button className="icon-btn h-7 w-7" aria-label="Zoom in" data-tip="Zoom in (or ⌘ and the wheel, or pinch)" onClick={() => zoomBy(1.4)}><PlusIcon size={14} /></button>
        <button className="icon-btn h-7 w-7" aria-label="Zoom out" data-tip="Zoom out" onClick={() => zoomBy(1 / 1.4)}><MinusIcon size={14} /></button>
        <button className="icon-btn h-7 w-7" aria-label="Fit everyone in view" data-tip="Fit everyone in view" onClick={() => { touched.current = false; fit(); }}><ScanIcon size={14} /></button>
        {remember && <button className="icon-btn h-7 w-7" aria-label="Lay out again" data-tip="Lay out again from scratch" onClick={layOutAgain}><RefreshIcon size={14} /></button>}
      </div>
      {hover && (
        <div className="panel pointer-events-none absolute z-10 max-w-64 px-3 py-2 shadow-lg" style={{ left: Math.min(hover.x + 14, size.w - 260), top: hover.y + 14 }}>
          {hover.node.person ? (
            <>
              <div className="text-ui font-medium">{hover.node.person.name}</div>
              {hover.node.person.subtitle && <div className="text-hint text-ink-soft">{hover.node.person.subtitle}</div>}
              <div className="mt-0.5 text-meta text-ink-soft">
                {hover.node.person.tier ? `${TIER_META[hover.node.person.tier].label} · ` : ""}
                {hover.node.person.degree} connection{hover.node.person.degree === 1 ? "" : "s"}
              </div>
              {hover.node.person.groups.length > 0 && (
                <div className="mt-0.5 text-meta text-ink-soft">
                  In {hover.node.person.groups.slice(0, 4).map((g) => groups.get(g)?.name ?? g).join(", ")}
                  {hover.node.person.groups.length > 4 ? ` and ${hover.node.person.groups.length - 4} more` : ""}
                </div>
              )}
            </>
          ) : (
            hover.node.event && (
              <>
                <div className="text-ui font-medium">{hover.node.event.name}</div>
                <div className="text-meta text-ink-soft">{hover.node.event.kind === "meeting" ? "Meeting" : "Document"}{hover.node.event.at ? ` · ${hover.node.event.at.slice(0, 10)}` : ""}</div>
              </>
            )
          )}
        </div>
      )}
    </div>
  );
}

function drawEvent(ctx: CanvasRenderingContext2D, n: N, x: number, y: number, scale: number, colors: Colors) {
  const ev = n.event!;
  ctx.beginPath();
  tracePath(ctx, EVENT_SHAPE[ev.kind], x, y, n.r + 1.5 / scale);
  ctx.fillStyle = colors.surface;
  ctx.fill();
  ctx.beginPath();
  tracePath(ctx, EVENT_SHAPE[ev.kind], x, y, n.r);
  ctx.fillStyle = colors.soft;
  ctx.fill();
  if (scale >= 1.1) {
    ctx.font = `500 ${Math.max(10 / scale, 2)}px system-ui, -apple-system, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    const label = ev.name.length > 28 ? `${ev.name.slice(0, 27)}…` : ev.name;
    ctx.lineWidth = 3 / scale;
    ctx.strokeStyle = colors.surface;
    ctx.lineJoin = "round";
    ctx.strokeText(label, x, y + n.r + 2 / scale);
    ctx.fillStyle = colors.soft;
    ctx.fillText(label, x, y + n.r + 2 / scale);
  }
}
