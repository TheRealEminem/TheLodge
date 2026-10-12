// Hand-built SVG artwork: the brand mark, the lodge scene, and the growth-ring motif used across the app.
import { useEffect, useId, useRef } from "react";
import type { CSSProperties, ReactNode } from "react";

const reducedMotion = () =>
  typeof window !== "undefined" && (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);

/** Brand mark: a forest tile with a low sun, an A-frame lodge and two elevation lines. */
export function Logo({ size = 36 }: { size?: number }) {
  const id = useId();
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true" className="shrink-0">
      <defs>
        <linearGradient id={`${id}-bg`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2F7B58" />
          <stop offset="1" stopColor="#1B4E37" />
        </linearGradient>
        <linearGradient id={`${id}-sun`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#F8CB5A" />
          <stop offset="1" stopColor="#EE8540" />
        </linearGradient>
        <clipPath id={`${id}-clip`}>
          <rect width="64" height="64" rx="16" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        <rect width="64" height="64" fill={`url(#${id}-bg)`} />
        <path d="M0 42 C 13 34, 26 34, 38 39 S 56 38, 64 34 V64 H0Z" fill="#fff" fillOpacity="0.07" />
        <g fill="none" stroke="#F4EEDC" strokeLinecap="round" strokeWidth="1.3">
          <path d="M-2 49 C 12 43, 26 44, 38 48 S 56 47, 66 43" strokeOpacity="0.2" />
          <path d="M-2 56 C 14 51, 28 52, 40 55 S 56 54, 66 51" strokeOpacity="0.13" />
        </g>
        <circle cx="46" cy="19" r="7" fill={`url(#${id}-sun)`} />
        <path d="M13 53 L31 28 L49 53" fill="none" stroke="#F6EBCF" strokeWidth="4.4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M26.5 53 L31 45.5 L35.5 53" fill="none" stroke="#F6EBCF" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </g>
      <rect x="0.5" y="0.5" width="63" height="63" rx="15.5" fill="none" stroke="#fff" strokeOpacity="0.16" />
    </svg>
  );
}

// ── The lodge ─────────────────────────────────────────────────────────

// The family's landscape palette, plus the lodge itself: cedar walls, a forest roof with cream trim (the
// mark's A), a lake, and a fire in the clearing. By day the glass holds the sky; at dusk every window is lit.
const DAY = {
  skyTop: "#D5E5EB",
  skyMid: "#E8EEE8",
  skyLow: "#F6F0E1",
  sunA: "#F8CF66",
  sunB: "#F0A640",
  glow: "#F5B83A",
  mist: "#FFFFFF",
  mistOpacity: 0.5,
  peakTop: "#B3C9C2",
  peakLow: "#CFDDD3",
  snow: "#F7F6EF",
  snowOpacity: 0.85,
  contour: "#FFFFFF",
  contourOpacity: 0.45,
  shore: "#86AE93",
  pineFar: "#5F8F74",
  lakeTop: "#D3E3E3",
  lakeLow: "#BCD4D2",
  glint: "#FFF4D6",
  reflection: 0.22,
  nearTop: "#6FA181",
  nearLow: "#5B8F6E",
  roof: "#2B5340",
  trim: "#F6EBCF",
  wall: "#D9BC8C",
  plank: "#C7A673",
  deck: "#9C7B52",
  glassA: "#EEF4F1",
  glassB: "#C9DCDB",
  lit: 0,
  pipe: "#3A4A42",
  smoke: "#FFFFFF",
  smokeOpacity: 0.7,
  trail: "#F4E8CB",
  trailEdge: "#D9C79C",
  stone: "#A9B8AA",
  log: "#8A6A45",
  flame: "#E86636",
  flameCore: "#F8CF66",
  fireGlow: 0.18,
  pineNear: "#3E7C5D",
  dock: "#B89668",
  canoe: "#D9693A",
  fore: "#2B6449",
  pineFore: "#23563E",
};

const DUSK: typeof DAY = {
  skyTop: "#151D2C",
  skyMid: "#222A3F",
  skyLow: "#443D58",
  sunA: "#F3E9CA",
  sunB: "#E4D6AE",
  glow: "#F1E6C6",
  mist: "#9A93B8",
  mistOpacity: 0.14,
  peakTop: "#3A495F",
  peakLow: "#304055",
  snow: "#C9D3E6",
  snowOpacity: 0.22,
  contour: "#C9D3E6",
  contourOpacity: 0.12,
  shore: "#24364A",
  pineFar: "#1C2C3A",
  lakeTop: "#2E3753",
  lakeLow: "#232B42",
  glint: "#F1E6C6",
  reflection: 0.3,
  nearTop: "#1F333B",
  nearLow: "#1B2D34",
  roof: "#101D22",
  trim: "#A99C80",
  wall: "#3A332D",
  plank: "#2F2924",
  deck: "#2A241F",
  glassA: "#FBD77E",
  glassB: "#F1A84A",
  lit: 1,
  pipe: "#141F24",
  smoke: "#9A93B8",
  smokeOpacity: 0.32,
  trail: "#8D8370",
  trailEdge: "#6A6252",
  stone: "#3B4A50",
  log: "#2E2620",
  flame: "#EE7445",
  flameCore: "#F8CF66",
  fireGlow: 0.42,
  pineNear: "#172A30",
  dock: "#3A332B",
  canoe: "#6E4436",
  fore: "#13242A",
  pineFore: "#0E1D21",
};

/** A slender two-tier pine silhouette standing on (x, y). */
const pine = (x: number, y: number, h: number) => {
  const w = h * 0.36;
  const t = y - h * 0.42;
  return `M${x} ${y - h}L${x + w * 0.62} ${t}L${x + w * 0.34} ${t}L${x + w} ${y}L${x - w} ${y}L${x - w * 0.34} ${t}L${x - w * 0.62} ${t}Z`;
};

const PEAKS_LINE =
  "M-20 124 C 30 118, 62 110, 96 100 C 120 93, 132 96, 150 104 C 172 113, 196 108, 222 96 C 244 86, 262 76, 276 72 C 284 70, 290 72, 298 77 C 322 92, 350 108, 384 112 C 410 115, 432 106, 460 100 C 484 95, 500 104, 524 112 C 556 121, 592 116, 624 104 C 642 97, 656 89, 668 86 C 676 84, 682 86, 690 91 C 714 106, 748 118, 790 120 C 802 121, 812 121, 820 121";
const SNOW = [
  "M258 81 C 266 75, 272 72, 278 71 C 286 70, 292 73, 300 79 C 292 80, 287 84, 281 81 C 274 84, 266 81, 258 81Z",
  "M654 92 C 660 88, 664 86, 670 85 C 677 84, 683 87, 690 92 C 683 93, 678 96, 673 93 C 666 96, 660 93, 654 92Z",
];
const SHORE_LINE = "M-20 158 C 50 151, 120 147, 200 151 C 270 155, 330 146, 410 147 C 500 148, 560 141, 640 145 C 710 148, 770 150, 820 149";
const SHORE_PINES = [
  [36, 154, 13], [48, 153, 17], [60, 154, 12], [150, 150, 12], [162, 151, 16], [420, 148, 13], [432, 149, 18],
  [446, 148, 11], [574, 144, 14], [586, 145, 19], [598, 144, 12], [722, 149, 15], [734, 150, 11],
];
const STARS = [[60, 34], [132, 22], [206, 52], [262, 30], [338, 56], [418, 22], [470, 60], [660, 40], [712, 70], [760, 30], [108, 80], [380, 36], [596, 24]];
// Two shapes for the smoke from the stove; it sways slowly between them.
const SMOKE = [
  "M354 142 C 349 134, 360 128, 356 120 C 352 112, 365 106, 362 96 C 359 87, 371 81, 371 72",
  "M354 142 C 351 133, 363 129, 360 120 C 357 111, 368 107, 367 97 C 366 88, 378 83, 380 73",
];

/**
 * The lodge by the lake, in layers. With `parallax`, the layers drift a few pixels with the pointer (nearer
 * layers more), and the smoke from the stove drifts up.
 */
export function LodgeScene({ dusk = false, parallax = false, className = "" }: { dusk?: boolean; parallax?: boolean; className?: string }) {
  const id = useId();
  const svg = useRef<SVGSVGElement>(null);
  const P = dusk ? DUSK : DAY;
  const alive = parallax && !reducedMotion();

  useEffect(() => {
    if (!parallax || reducedMotion()) return;
    let raf = 0;
    const onMove = (e: PointerEvent) => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const el = svg.current;
        if (!el) return;
        el.style.setProperty("--px", ((e.clientX / window.innerWidth - 0.5) * -2).toFixed(3));
        el.style.setProperty("--py", ((e.clientY / window.innerHeight - 0.5) * -2).toFixed(3));
      });
    };
    window.addEventListener("pointermove", onMove);
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(raf);
    };
  }, [parallax]);

  // Depth factor -> at most ~5px of travel for the foreground.
  const layer = (depth: number): CSSProperties | undefined =>
    parallax
      ? {
          transform: `translate3d(calc(var(--px, 0) * ${(depth * 1.3).toFixed(2)}px), calc(var(--py, 0) * ${(depth * 0.5).toFixed(2)}px), 0)`,
          transition: "transform 1.1s cubic-bezier(0.2, 0.8, 0.2, 1)",
        }
      : undefined;

  const u = (name: string) => `url(#${id}-${name})`;

  return (
    <svg
      ref={svg}
      viewBox="0 0 800 260"
      preserveAspectRatio="xMidYMax slice"
      className={className}
      role="img"
      aria-label={dusk ? "A lodge by a lake at dusk, its windows lit and a fire going" : "A lodge by a mountain lake on a summer day"}
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.skyTop} />
          <stop offset="0.5" stopColor={P.skyMid} />
          <stop offset="0.85" stopColor={P.skyLow} />
        </linearGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0" stopColor={P.glow} stopOpacity={dusk ? 0.22 : 0.4} />
          <stop offset="1" stopColor={P.glow} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-sun`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.sunA} />
          <stop offset="1" stopColor={P.sunB} />
        </linearGradient>
        <linearGradient id={`${id}-mist`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.mist} stopOpacity="0" />
          <stop offset="0.5" stopColor={P.mist} stopOpacity={P.mistOpacity} />
          <stop offset="1" stopColor={P.mist} stopOpacity="0" />
        </linearGradient>
        <linearGradient id={`${id}-peaks`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.3" stopColor={P.peakTop} />
          <stop offset="0.6" stopColor={P.peakLow} />
        </linearGradient>
        <linearGradient id={`${id}-lake`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.55" stopColor={P.lakeTop} />
          <stop offset="0.8" stopColor={P.lakeLow} />
        </linearGradient>
        <linearGradient id={`${id}-near`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0.75" stopColor={P.nearTop} />
          <stop offset="1" stopColor={P.nearLow} />
        </linearGradient>
        <linearGradient id={`${id}-glass`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.glassA} />
          <stop offset="1" stopColor={P.glassB} />
        </linearGradient>
        <radialGradient id={`${id}-warm`}>
          <stop offset="0" stopColor="#F5B83A" stopOpacity="1" />
          <stop offset="1" stopColor="#F5B83A" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-fire`}>
          <stop offset="0" stopColor="#F0A640" stopOpacity="1" />
          <stop offset="1" stopColor="#E86636" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-smoke`} x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stopColor={P.smoke} stopOpacity={P.smokeOpacity} />
          <stop offset="1" stopColor={P.smoke} stopOpacity="0" />
        </linearGradient>
        <mask id={`${id}-moon`}>
          <circle cx="532" cy="60" r="18" fill="#fff" />
          <circle cx="540" cy="54" r="16" fill="#000" />
        </mask>
        <clipPath id={`${id}-water`}>
          <rect x="-20" y="150" width="840" height="70" />
        </clipPath>
        <g id={`${id}-shore`}>
          <path d={`${SHORE_LINE} V170 H-20Z`} fill={P.shore} />
          <g fill={P.pineFar}>
            {SHORE_PINES.map(([x, y, h], i) => (
              <path key={i} d={pine(x, y, h)} />
            ))}
          </g>
        </g>
      </defs>

      <rect x="-20" y="-20" width="840" height="300" fill={u("sky")} />

      {dusk && (
        <g fill="#F1E6C6" style={layer(0.2)}>
          {STARS.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r={i % 3 ? 0.9 : 1.4} opacity={i % 2 ? 0.55 : 0.8} />
          ))}
        </g>
      )}

      {/* sun (or moon), ringed like an elevation map */}
      <g style={layer(0.5)}>
        <circle cx="532" cy="64" r="130" fill={u("glow")} />
        <g fill="none" stroke={P.glow} strokeWidth="1">
          <circle cx="532" cy="64" r="36" opacity={dusk ? 0.12 : 0.24} />
          <circle cx="532" cy="64" r="52" opacity={dusk ? 0.07 : 0.13} />
        </g>
        {dusk ? <circle cx="532" cy="60" r="18" fill={u("sun")} mask={u("moon")} /> : <circle cx="532" cy="64" r="22" fill={u("sun")} />}
      </g>

      {/* far peaks with their contour lines */}
      <g style={layer(0.9)}>
        <path d={`${PEAKS_LINE} V200 H-20Z`} fill={u("peaks")} />
        <g fill={P.snow} fillOpacity={P.snowOpacity}>
          {SNOW.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
        <g fill="none" stroke={P.contour} strokeWidth="1" strokeOpacity={P.contourOpacity}>
          <path d={PEAKS_LINE} transform="translate(0 11)" />
          <path d={PEAKS_LINE} transform="translate(0 22)" opacity="0.7" />
          <path d={PEAKS_LINE} transform="translate(0 33)" opacity="0.45" />
        </g>
      </g>

      <rect x="-20" y="96" width="840" height="70" fill={u("mist")} style={layer(0.6)} />

      {/* the lake: the far shore and its reflection, and the light on the water */}
      <g style={layer(1.5)}>
        <rect x="-20" y="150" width="840" height="70" fill={u("lake")} />
        <g clipPath={u("water")} opacity={P.reflection}>
          <use href={`#${id}-shore`} transform="translate(0 300) scale(1 -1)" />
        </g>
        <g stroke={P.glint} strokeLinecap="round" strokeWidth="1.6" opacity={dusk ? 0.45 : 0.85}>
          <path d="M512 168 H552" />
          <path d="M520 175 H546" opacity="0.8" />
          <path d="M526 182 H540" opacity="0.6" />
          <path d="M530 189 H536" opacity="0.4" />
        </g>
        <g stroke={P.glint} strokeLinecap="round" strokeWidth="1" opacity={dusk ? 0.18 : 0.4}>
          <path d="M120 172 H150" />
          <path d="M660 180 H688" />
          <path d="M250 186 H268" />
        </g>
        <use href={`#${id}-shore`} />
      </g>

      {/* the clearing, the lodge and the fire */}
      <g style={layer(2.6)}>
        {/* a dock runs out into the lake, with the canoe tied alongside */}
        <g>
          <path d="M574 209 C 578 205, 600 205, 610 206.5" fill="none" stroke={P.canoe} strokeWidth="4.2" strokeLinecap="round" />
          <path d="M560 203.5 H622" stroke={P.dock} strokeWidth="2.6" strokeLinecap="round" />
          <path d="M566 204 V210 M590 204 V210 M614 204 V210" stroke={P.dock} strokeWidth="1.6" strokeLinecap="round" />
        </g>

        <path
          d="M-20 205 C 60 197, 150 196, 232 202 C 282 206, 318 210, 360 211 C 420 212, 470 208, 530 208 C 560 208, 566 212, 590 214 C 660 219, 730 207, 820 204 V280 H-20Z"
          fill={u("near")}
        />

        {/* light from the windows and the fire spills onto the ground */}
        {P.lit > 0 && (
          <g>
            <ellipse cx="338" cy="216" rx="96" ry="18" fill={u("warm")} opacity="0.24" />
            <circle cx="338" cy="176" r="58" fill={u("warm")} opacity="0.14" />
          </g>
        )}
        <ellipse cx="456" cy="226" rx="40" ry="15" fill={u("fire")} opacity={P.fireGlow} />

        <path
          d="M-20 244 C 90 235, 200 239, 300 247 C 400 255, 520 237, 640 239 C 720 240, 780 245, 820 243 V280 H-20Z"
          fill={P.nearLow}
          opacity="0.7"
        />

        {/* pines the lodge is tucked into */}
        <g fill={P.pineNear} stroke={P.pineNear} strokeWidth="1.2" strokeLinejoin="round">
          {[[262, 210, 52], [278, 212, 38], [246, 208, 30], [404, 213, 58], [420, 214, 42], [392, 212, 30]].map(([x, y, h], i) => (
            <path key={i} d={pine(x, y, h)} />
          ))}
        </g>

        {/* the path up from the foreground */}
        <g fill="none" strokeLinecap="round">
          <path d="M268 268 C 292 250, 258 238, 300 230" stroke={P.trailEdge} strokeWidth="12" strokeOpacity="0.6" />
          <path d="M300 230 C 322 225, 334 224, 338 217" stroke={P.trailEdge} strokeWidth="8" strokeOpacity="0.6" />
          <path d="M268 268 C 292 250, 258 238, 300 230" stroke={P.trail} strokeWidth="9" />
          <path d="M300 230 C 322 225, 334 224, 338 217" stroke={P.trail} strokeWidth="5.5" />
        </g>

        {/* the A-frame, drawn at the mark's proportions */}
        <g transform="translate(338 214) scale(1.3) translate(-338 -214)" strokeLinejoin="round">
          <rect x="351.5" y="145" width="5" height="22" rx="1" fill={P.pipe} />
          <rect x="349.5" y="143" width="9" height="3.2" rx="1.2" fill={P.pipe} />
          <path d="M338 139 L387 214 L289 214Z" fill={P.roof} />
          <path d="M338 151 L374 211 L302 211Z" fill={P.wall} />
          <g stroke={P.plank} strokeWidth="0.8">
            <path d="M326 171 V211 M314 191 V211 M350 171 V211 M362 191 V211" />
          </g>
          <path d="M338 158 L358 191 L318 191Z" fill={u("glass")} stroke={P.trim} strokeWidth="1.3" />
          <path d="M338 158 V191 M326 178 H350" stroke={P.trim} strokeWidth="0.8" strokeOpacity="0.8" />
          <rect x="332.5" y="196" width="11" height="15" rx="1" fill={u("glass")} stroke={P.trim} strokeWidth="1" />
          <rect x="309" y="198" width="10" height="7" rx="1" fill={u("glass")} stroke={P.trim} strokeWidth="0.8" />
          <rect x="357" y="198" width="10" height="7" rx="1" fill={u("glass")} stroke={P.trim} strokeWidth="0.8" />
          <path d="M288 214.5 H388" stroke={P.deck} strokeWidth="3.2" strokeLinecap="round" />
          <path d="M292 214 L338 140.5 L384 214" fill="none" stroke={P.trim} strokeWidth="2.8" strokeLinecap="round" />
          <path d={SMOKE[0]} fill="none" stroke={u("smoke")} strokeWidth="2.8" strokeLinecap="round">
            {alive && <animate attributeName="d" values={`${SMOKE[0]};${SMOKE[1]};${SMOKE[0]}`} dur="7s" repeatCount="indefinite" calcMode="spline" keySplines=".45 0 .55 1;.45 0 .55 1" />}
          </path>
        </g>

        {/* the fire, with two logs to sit on */}
        <g transform="translate(20 3)">
          <rect x="410" y="222" width="14" height="3.6" rx="1.8" fill={P.log} transform="rotate(-8 417 224)" />
          <rect x="448" y="223" width="14" height="3.6" rx="1.8" fill={P.log} transform="rotate(10 455 225)" />
          <ellipse cx="436" cy="223.5" rx="7.5" ry="2.6" fill="none" stroke={P.stone} strokeWidth="1.6" />
          <path d="M436 213.5 C 439.5 217, 440 220, 437.8 222.6 L 434.2 222.6 C 432 220, 432.5 217, 436 213.5Z" fill={P.flame} />
          <path d="M436 217.5 C 437.6 219.2, 437.8 220.8, 436.9 222.4 L 435.1 222.4 C 434.2 220.8, 434.4 219.2, 436 217.5Z" fill={P.flameCore} />
        </g>
      </g>

      {/* foreground framing */}
      <g style={layer(4)}>
        <path d="M-20 262 V 222 C 30 216, 88 226, 150 262 Z" fill={P.fore} />
        <path d="M820 262 V 214 C 760 212, 700 230, 650 262 Z" fill={P.fore} />
        <g fill={P.pineFore} stroke={P.pineFore} strokeWidth="1.2" strokeLinejoin="round">
          {[[30, 232, 56], [56, 238, 40], [752, 226, 60], [776, 232, 44]].map(([x, y, h], i) => (
            <path key={i} d={pine(x, y, h)} />
          ))}
        </g>
      </g>
    </svg>
  );
}

// ── Growth rings ──────────────────────────────────────────────────────

/** A repeatable 0..1 noise, so the artwork draws the same way every time. */
const noise = (i: number, seed: number) => {
  const x = Math.sin(i * 12.9898 + seed * 78.233) * 43758.5453;
  return x - Math.floor(x);
};

/**
 * The end of a log: growth rings around an off-centre heart, wide years and narrow ones, gently out of round.
 * Neighbouring rings share their wobble, the way real ones do, so they never cross.
 */
function growthRings(cx: number, cy: number, n: number, first: number, avg: number, seed: number, lean = 0.06) {
  const out: { d: string; late: boolean }[] = [];
  let r = first;
  for (let ring = 0; ring < n; ring++) {
    // Young trees put on wide rings and old ones narrow; dry spells come in runs of thin years.
    const age = 1.45 - 0.8 * (ring / n);
    const spell = Math.sin(ring * 0.37 + seed * 3) > 0.55 ? 0.45 : 1;
    const year = avg * age * spell * (0.6 + 0.8 * noise(ring, seed));
    r += Math.max(avg * 0.3, year);
    const ox = cx + Math.cos(seed) * r * lean;
    const oy = cy + Math.sin(seed) * r * lean;
    let d = "";
    for (let k = 0; k <= 144; k++) {
      const t = (k / 144) * Math.PI * 2;
      const wob =
        1 +
        0.024 * Math.sin(2 * t + seed + r * 0.0016) +
        0.016 * Math.sin(3 * t - seed * 1.3 + r * 0.0031) +
        0.008 * Math.sin(5 * t + seed * 0.7 + r * 0.006);
      d += `${k ? "L" : "M"}${(ox + Math.cos(t) * r * wob).toFixed(1)} ${(oy + Math.sin(t) * r * wob).toFixed(1)}`;
    }
    out.push({ d: d + "Z", late: spell < 1 || noise(ring + 97, seed) > 0.8 });
  }
  return { rings: out, outer: r };
}

/** A drying check: a thin split running straight in from the bark toward the heart, a little ragged. */
function check(cx: number, cy: number, angle: number, from: number, to: number, width: number, seed: number) {
  const steps = 18;
  const side = (sign: number) =>
    Array.from({ length: steps + 1 }, (_, k) => {
      const f = k / steps;
      const r = to + (from - to) * f;
      const a = angle + 0.0022 * Math.sin(f * 27 + seed) * (1 + f) + 0.0012 * (noise(k, seed) - 0.5);
      const w = (width * Math.pow(f, 1.6) * sign) / 2 / r;
      return [cx + Math.cos(a + w) * r, cy + Math.sin(a + w) * r];
    });
  const pts = [...side(1), ...side(-1).reverse()];
  return pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`).join("") + "Z";
}

const LOG = growthRings(1430, 70, 44, 12, 22, 0.9);
const KNOT = growthRings(120, 990, 15, 10, 17, 2.4, 0.09);
const CHECKS = [
  check(1430, 70, 2.36, LOG.outer, LOG.outer * 0.38, 10, 1),
  check(1430, 70, 2.92, LOG.outer * 0.9, LOG.outer * 0.6, 6, 2),
  check(120, 990, -0.75, KNOT.outer, KNOT.outer * 0.4, 5, 3),
];

/** The app's atmosphere: a soft gradient, a warm light low in the room, and watermark-faint growth rings. */
export function Ambient() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <div className="absolute inset-0" style={{ background: "linear-gradient(180deg, var(--bg-top) 0%, var(--bg) 42%)" }} />
      <div className="absolute inset-0" style={{ background: "radial-gradient(55% 50% at 60% 62%, var(--glow-green), transparent 70%)" }} />
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(34% 28% at 84% 2%, var(--glow-warm), transparent 72%), radial-gradient(48% 44% at 26% 104%, var(--glow-hearth), transparent 72%)",
        }}
      />
      <svg
        viewBox="0 0 1600 1000"
        preserveAspectRatio="xMidYMid slice"
        className="absolute inset-0 h-full w-full"
        style={{
          WebkitMaskImage: "radial-gradient(95% 95% at 78% 18%, #000 30%, transparent 88%)",
          maskImage: "radial-gradient(95% 95% at 78% 18%, #000 30%, transparent 88%)",
        }}
      >
        <g fill="none" stroke="var(--grain)">
          {[...LOG.rings, ...KNOT.rings].map((r, i) => (
            <path key={i} d={r.d} strokeWidth={r.late ? 1.7 : 1} vectorEffect="non-scaling-stroke" />
          ))}
        </g>
        <g fill="var(--grain)">
          {CHECKS.map((d, i) => (
            <path key={i} d={d} />
          ))}
        </g>
      </svg>
    </div>
  );
}

const BADGE = growthRings(32, 32, 4, 13, 4.6, 1.7, 0.05);
const BADGE_CHECK = check(32, 32, -0.8, BADGE.outer, BADGE.outer - 7, 2.2, 1);

/** Empty-state mark: an icon at the heart of a few growth rings. */
export function ContourBadge({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`relative mx-auto flex h-20 w-20 items-center justify-center ${className}`}>
      <svg viewBox="0 0 64 64" className="absolute inset-0 h-full w-full text-forest" aria-hidden="true">
        <g fill="none" stroke="currentColor" strokeWidth="1">
          {BADGE.rings.map((r, i) => (
            <path key={i} d={r.d} opacity={[0.24, 0.17, 0.11, 0.07][i]} vectorEffect="non-scaling-stroke" />
          ))}
        </g>
        <path d={BADGE_CHECK} fill="currentColor" opacity="0.08" />
      </svg>
      <span className="well well-forest relative h-10 w-10 rounded-md">{children}</span>
    </div>
  );
}
