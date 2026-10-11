import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import type { ForceGraphMethods, LinkObject, NodeObject } from "react-force-graph-2d";
import { useShell } from "@core/shell";
import type { Graph, GraphLink, GraphNode } from "./api";
import { KIND_LABEL } from "./bits";
import { KIND_SHAPE, fillFor, readColors, tracePath } from "./graphShapes";
import { TIER_META } from "./tier";

type N = NodeObject<GraphNode & { r: number }>;
type L = LinkObject<GraphNode & { r: number }, GraphLink>;

export interface Highlight {
  nodes: Set<string>;
  links: Set<string>;
}

function radius(n: GraphNode): number {
  const base = n.kind === "meeting" || n.kind === "document" ? 3.5 : 4.5;
  return Math.min(base + Math.sqrt(n.degree) * 1.5, 15) + (n.is_self ? 3 : 0);
}

const endId = (end: L["source"]): string => (typeof end === "object" && end !== null ? String((end as N).id) : String(end));

export default function NetworkCanvas({ graph, height, selectedId, focusId, highlight, onNodeClick, onBackgroundClick, labels = "auto" }: {
  graph: Graph;
  height?: number;
  selectedId?: string | null;
  focusId?: string | null;
  highlight?: Highlight | null;
  onNodeClick?: (n: GraphNode) => void;
  onBackgroundClick?: () => void;
  labels?: "auto" | "all";
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const fg = useRef<ForceGraphMethods<N, L> | undefined>(undefined);
  const [size, setSize] = useState({ w: 300, h: height ?? 300 });
  const [hover, setHover] = useState<{ node: GraphNode; x: number; y: number } | null>(null);
  const { theme } = useShell();
  const colors = useMemo(() => readColors(), [theme.dusk]);
  const positions = useRef(new Map<string, { x?: number; y?: number }>());
  const reduce = useMemo(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false, []);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize({ w: e.contentRect.width, h: height ?? e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [height]);

  // force-graph mutates its input, so hand it copies, and keep the positions of nodes we've already laid out.
  const data = useMemo(() => ({
    nodes: graph.nodes.map((n) => ({ ...n, r: radius(n), ...positions.current.get(n.id) })) as N[],
    links: graph.links.map((l) => ({ ...l })) as L[],
  }), [graph]);

  useEffect(() => {
    const f = fg.current;
    if (!f) return;
    f.d3Force("charge")?.strength(-160);
    f.d3Force("link")?.distance((l: L) => {
      const s = data.nodes.find((n) => n.id === endId(l.source));
      return s?.kind === "meeting" || s?.kind === "document" ? 34 : 56;
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

  const dimmed = (id: string) => Boolean(highlight && highlight.nodes.size > 0 && !highlight.nodes.has(id));

  return (
    <div ref={wrap} className="relative h-full w-full overflow-hidden" style={height ? { height } : undefined}>
      <ForceGraph2D<GraphNode & { r: number }, GraphLink>
        ref={fg}
        graphData={data}
        width={size.w}
        height={size.h}
        cooldownTicks={140}
        warmupTicks={20}
        onEngineStop={() => {
          for (const n of data.nodes) positions.current.set(String(n.id), { x: n.x, y: n.y });
          if (!focusId) fg.current?.zoomToFit(reduce ? 0 : 500, 48);
        }}
        linkColor={(l) => (highlight?.links.has(l.id) ? colors.forest : colors.edge)}
        linkWidth={(l) => (highlight?.links.has(l.id) ? 2.5 : 0.4 + l.strength * 0.3)}
        nodeCanvasObject={(node, ctx, scale) => {
          const n = node as N;
          const x = n.x ?? 0;
          const y = n.y ?? 0;
          const r = n.r;
          const shape = KIND_SHAPE[n.kind];
          const faded = dimmed(n.id);
          ctx.globalAlpha = faded ? 0.18 : 1;

          // A surface-coloured halo keeps overlapping nodes legible.
          ctx.beginPath();
          tracePath(ctx, shape, x, y, r + 2 / scale);
          ctx.fillStyle = colors.surface;
          ctx.fill();

          const fill = fillFor(n.kind, n.tier, n.is_self);
          ctx.beginPath();
          tracePath(ctx, shape, x, y, r);
          if (fill === "solid") {
            ctx.fillStyle = colors.forest;
            ctx.fill();
          } else if (fill === "tint") {
            ctx.fillStyle = colors.forest;
            ctx.globalAlpha = (faded ? 0.18 : 1) * 0.55;
            ctx.fill();
            ctx.globalAlpha = faded ? 0.18 : 1;
          } else if (fill === "neutral") {
            ctx.fillStyle = colors.soft;
            ctx.fill();
          } else {
            ctx.strokeStyle = fill === "ring" ? colors.forest : colors.soft;
            ctx.lineWidth = 1.6 / scale;
            if (fill === "dotted") ctx.setLineDash([2 / scale, 2 / scale]);
            ctx.stroke();
            ctx.setLineDash([]);
          }

          if (n.id === selectedId) {
            ctx.beginPath();
            tracePath(ctx, shape, x, y, r + 3.5 / scale);
            ctx.strokeStyle = colors.ink;
            ctx.lineWidth = 1.5 / scale;
            ctx.stroke();
          }

          const important = n.is_self || n.id === selectedId || n.id === focusId || highlight?.nodes.has(n.id);
          // Zoomed out, only hubs among people and organizations get names; close up, everything does.
          const hub = n.kind !== "meeting" && n.kind !== "document" && n.degree >= 8;
          if ((labels === "all" || important || scale >= 1.8 || (scale >= 0.9 && hub)) && !faded) {
            ctx.font = `${important ? 600 : 500} ${Math.max(11 / scale, 2)}px system-ui, -apple-system, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            const ty = y + r + 3 / scale;
            ctx.lineWidth = 3 / scale;
            ctx.strokeStyle = colors.surface;
            ctx.lineJoin = "round";
            ctx.strokeText(n.name, x, ty);
            ctx.fillStyle = colors.ink;
            ctx.fillText(n.name, x, ty);
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
        onNodeClick={(node) => onNodeClick?.(node as N)}
        onBackgroundClick={() => {
          if (wrap.current) wrap.current.style.cursor = "default";
          onBackgroundClick?.();
        }}
        onZoom={() => setHover(null)}
      />
      {hover && (
        <div className="panel pointer-events-none absolute z-10 max-w-64 px-3 py-2 shadow-lg" style={{ left: Math.min(hover.x + 14, size.w - 260), top: hover.y + 14 }}>
          <div className="text-ui font-medium">{hover.node.name}</div>
          {hover.node.subtitle && <div className="text-hint text-ink-soft">{hover.node.subtitle}</div>}
          <div className="mt-0.5 text-meta text-ink-soft">
            {KIND_LABEL[hover.node.kind].one}
            {hover.node.tier && ` · ${TIER_META[hover.node.tier].label}`} · {hover.node.degree} connection{hover.node.degree === 1 ? "" : "s"}
          </div>
        </div>
      )}
    </div>
  );
}
