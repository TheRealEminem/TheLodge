// How the network draws things. Kind is the shape; how well you know a person is the fill (solid, lighter
// solid, ring, dotted ring), so neither depends on colour alone.
import type { EntityKind, Tier } from "./api";

export type Shape = "circle" | "square" | "diamond" | "page" | "hexagon";

export const KIND_SHAPE: Record<EntityKind, Shape> = {
  person: "circle",
  organization: "square",
  meeting: "diamond",
  document: "page",
  topic: "hexagon",
};

export const KIND_ORDER: EntityKind[] = ["person", "organization", "meeting", "document", "topic"];

/** Canvas can't read CSS variables, so resolve the tokens (again whenever the theme flips). */
export function readColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string) => s.getPropertyValue(name).trim();
  return {
    forest: v("--forest"),
    ink: v("--text-primary"),
    soft: v("--text-secondary"),
    faint: v("--text-tertiary"),
    surface: v("--surface-solid"),
    edge: v("--border-strong"),
  };
}
export type Colors = ReturnType<typeof readColors>;

export type FillStyle = "solid" | "tint" | "ring" | "dotted" | "neutral";

/** People by tier; everything else is neutral. */
export function fillFor(kind: EntityKind, tier: Tier | null, isSelf: boolean): FillStyle {
  if (isSelf) return "solid";
  if (kind !== "person") return "neutral";
  return tier === "strong" ? "solid" : tier === "working" ? "tint" : tier === "light" ? "ring" : "dotted";
}

/** Trace a kind's shape into a canvas path centred on (x, y) with radius r. */
export function tracePath(ctx: CanvasRenderingContext2D | Path2D, shape: Shape, x: number, y: number, r: number) {
  switch (shape) {
    case "circle":
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, Math.PI * 2);
      break;
    case "square": {
      const s = r * 0.9;
      const k = s * 0.3;
      ctx.moveTo(x - s + k, y - s);
      ctx.arcTo(x + s, y - s, x + s, y + s, k);
      ctx.arcTo(x + s, y + s, x - s, y + s, k);
      ctx.arcTo(x - s, y + s, x - s, y - s, k);
      ctx.arcTo(x - s, y - s, x + s, y - s, k);
      ctx.closePath();
      break;
    }
    case "diamond":
      ctx.moveTo(x, y - r * 1.15);
      ctx.lineTo(x + r * 1.15, y);
      ctx.lineTo(x, y + r * 1.15);
      ctx.lineTo(x - r * 1.15, y);
      ctx.closePath();
      break;
    case "page": {
      const w = r * 0.8;
      const h = r;
      const f = r * 0.4;
      ctx.moveTo(x - w, y - h);
      ctx.lineTo(x + w - f, y - h);
      ctx.lineTo(x + w, y - h + f);
      ctx.lineTo(x + w, y + h);
      ctx.lineTo(x - w, y + h);
      ctx.closePath();
      break;
    }
    case "hexagon":
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i + Math.PI / 6;
        if (i === 0) ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a));
        else ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a));
      }
      ctx.closePath();
      break;
  }
}

/** The same shape as a small SVG, for legends and lists. */
export function ShapeGlyph({ shape, className = "", size = 12, fill = "currentColor" }: { shape: Shape; className?: string; size?: number; fill?: string }) {
  const paths: Record<Shape, JSX.Element> = {
    circle: <circle cx={6} cy={6} r={5} fill={fill} />,
    square: <rect x={1.5} y={1.5} width={9} height={9} rx={2.5} fill={fill} />,
    diamond: <path d="M6 0.5 L11.5 6 L6 11.5 L0.5 6 Z" fill={fill} />,
    page: <path d="M2 1 H7.5 L10 3.5 V11 H2 Z" fill={fill} />,
    hexagon: <path d="M6 0.8 L10.5 3.4 V8.6 L6 11.2 L1.5 8.6 V3.4 Z" fill={fill} />,
  };
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" className={`shrink-0 ${className}`}>
      {paths[shape]}
    </svg>
  );
}
