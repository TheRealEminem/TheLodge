// The Lodge's artwork, the identity's half of the family contract (core/web/components/illustrations.tsx re-exports it):
// Logo (the brand mark), Scene (the lodge by the lake, at the time of day it is now), Ambient (the app's atmosphere
// with its growth rings) and Badge (the empty-state mark). Every family app's identity/art.tsx exports these four.
import { useEffect, useId, useRef, useState } from "react";
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
// mark's A), a lake, and a fire in the clearing. The scene keeps the clock: these are its looks through a day,
// and the picture blends between them. `sun`, `moon` and `stars` say how much of each is out; `lit` is how
// much the windows glow.
const DAY = {
  skyTop: "#D5E5EB",
  skyMid: "#E8EEE8",
  skyLow: "#F6F0E1",
  sunA: "#F8CF66",
  sunB: "#F0A640",
  glow: "#F5B83A",
  glowOpacity: 0.4,
  sun: 1,
  moon: 0,
  stars: 0,
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
  glintOpacity: 0.85,
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
type Light = typeof DAY;

// The lodge after dark: each window lit, the fire going, the moon up.
const NIGHT: Light = {
  skyTop: "#151D2C",
  skyMid: "#222A3F",
  skyLow: "#443D58",
  sunA: "#F8CF66",
  sunB: "#F0A640",
  glow: "#F1E6C6",
  glowOpacity: 0,
  sun: 0,
  moon: 1,
  stars: 1,
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
  glintOpacity: 0.45,
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

// Before sunrise: still dark, the stars going, a rose band behind the peaks.
const PREDAWN: Light = {
  ...NIGHT,
  skyTop: "#1B2236",
  skyMid: "#30364F",
  skyLow: "#7A5F72",
  moon: 0.7,
  stars: 0.45,
  mist: "#B7A3B8",
  mistOpacity: 0.2,
  peakTop: "#3F4762",
  peakLow: "#3A4560",
  snow: "#D9C3CD",
  snowOpacity: 0.3,
  contour: "#D6CCDA",
  lakeTop: "#3D3E5A",
  lit: 0.9,
};

// Sunrise: alpenglow on the snow, mist on the water, a light still on in the lodge.
const SUNRISE: Light = {
  ...DAY,
  skyTop: "#8EA7C2",
  skyMid: "#E2C3C3",
  skyLow: "#F6D2A8",
  sunA: "#FFE3A3",
  sunB: "#F59B5A",
  glow: "#F7A25F",
  glowOpacity: 0.5,
  moon: 0.1,
  stars: 0.05,
  mist: "#FFF4EA",
  mistOpacity: 0.6,
  peakTop: "#A7A2BB",
  peakLow: "#C7B9C4",
  snow: "#FFDCCB",
  snowOpacity: 0.9,
  contour: "#FFF1E8",
  contourOpacity: 0.35,
  shore: "#6F8C83",
  pineFar: "#4F6F68",
  lakeTop: "#DCCBD0",
  lakeLow: "#BBBBCB",
  glint: "#FFE2C2",
  glintOpacity: 0.8,
  reflection: 0.25,
  nearTop: "#5C8670",
  nearLow: "#4D7861",
  roof: "#264A3B",
  trim: "#F2E2C8",
  wall: "#C9A985",
  plank: "#B8966B",
  deck: "#8A6C4A",
  glassA: "#F9D38C",
  glassB: "#E8A35A",
  lit: 0.6,
  pipe: "#334038",
  smoke: "#FFF1EA",
  smokeOpacity: 0.6,
  trail: "#EEDCC2",
  trailEdge: "#CDB592",
  stone: "#98A49C",
  log: "#7A5D3E",
  fireGlow: 0.25,
  pineNear: "#355E4D",
  dock: "#A88A63",
  canoe: "#CC6238",
  fore: "#244F40",
  pineFore: "#1D4436",
};

// Early morning: fresh and cool, the mist still lying on the lake.
const MORNING: Light = {
  ...DAY,
  skyTop: "#C9DEEA",
  skyMid: "#E4EDEC",
  skyLow: "#F5EEDF",
  glow: "#F8C25A",
  glowOpacity: 0.42,
  mistOpacity: 0.62,
};

// Golden hour: long warm light, the snow going gold.
const GOLDEN: Light = {
  ...DAY,
  skyTop: "#AFC4D3",
  skyMid: "#F1D2A2",
  skyLow: "#F4B676",
  sunA: "#FFD77E",
  sunB: "#F08C3E",
  glow: "#F6A04A",
  glowOpacity: 0.5,
  mist: "#FFF1D6",
  mistOpacity: 0.3,
  peakTop: "#ADA894",
  peakLow: "#CDBE9E",
  snow: "#FFE6BE",
  snowOpacity: 0.9,
  contour: "#FFF6E0",
  contourOpacity: 0.4,
  shore: "#7D9E7A",
  pineFar: "#577D63",
  lakeTop: "#E8D2A8",
  lakeLow: "#C3BEA2",
  glint: "#FFE7B0",
  glintOpacity: 0.9,
  nearTop: "#6E9A6B",
  nearLow: "#5C885A",
  roof: "#2A4E3A",
  trim: "#F6E4C2",
  wall: "#DDB27C",
  plank: "#C99B62",
  deck: "#9A7448",
  glassA: "#F7E7C2",
  glassB: "#E3C79A",
  lit: 0.15,
  smoke: "#FFF6E6",
  smokeOpacity: 0.6,
  trail: "#F4DDB4",
  trailEdge: "#D6B98A",
  stone: "#A6AE96",
  log: "#86643E",
  fireGlow: 0.22,
  pineNear: "#3B714F",
  dock: "#BC9461",
  canoe: "#DC6A35",
  fore: "#2A5C40",
  pineFore: "#224F37",
};

// Sunset: the sun behind the western peaks, pink on the snow, the lights coming on.
const SUNSET: Light = {
  ...NIGHT,
  skyTop: "#2E3658",
  skyMid: "#6E5A7C",
  skyLow: "#E59468",
  sunA: "#F9B56C",
  sunB: "#E0623E",
  glow: "#F08A50",
  glowOpacity: 0.55,
  sun: 1,
  moon: 0,
  stars: 0.1,
  mist: "#C99AA6",
  mistOpacity: 0.25,
  peakTop: "#4E5172",
  peakLow: "#5D5876",
  snow: "#F0A99A",
  snowOpacity: 0.7,
  contour: "#F3C7C0",
  contourOpacity: 0.18,
  shore: "#3A4A5A",
  pineFar: "#2C3A48",
  lakeTop: "#8A6F86",
  lakeLow: "#4E4B69",
  glint: "#FFC79A",
  glintOpacity: 0.75,
  nearTop: "#2F4640",
  nearLow: "#283C38",
  roof: "#16252A",
  trim: "#C8B08E",
  wall: "#5A4636",
  plank: "#4A3A2E",
  deck: "#3A2E25",
  lit: 0.75,
  pipe: "#1A262A",
  smoke: "#C9A7B4",
  smokeOpacity: 0.4,
  trail: "#A5937A",
  trailEdge: "#7E705C",
  stone: "#4E5A5C",
  log: "#3A2E24",
  fireGlow: 0.38,
  pineNear: "#1D3236",
  dock: "#4A3D31",
  canoe: "#8E4E36",
  fore: "#172A2E",
  pineFore: "#112226",
};

// Blue hour: the last light gone violet, the moon up over the peaks, every window lit.
const BLUE_HOUR: Light = {
  ...NIGHT,
  skyTop: "#19203A",
  skyMid: "#2C3150",
  skyLow: "#5D4A66",
  glow: "#E38A5A",
  glowOpacity: 0.15,
  moon: 0.9,
  stars: 0.6,
  mist: "#8F86AE",
  mistOpacity: 0.16,
  peakTop: "#36425C",
  peakLow: "#323E57",
  snow: "#B9B6D0",
  snowOpacity: 0.25,
  shore: "#25344A",
  pineFar: "#1D2B3A",
  lakeTop: "#353A5A",
  lakeLow: "#262C45",
};

// Minutes after midnight → the look at that moment.
const DAY_KEYS: [number, Light][] = [
  [0, NIGHT],
  [300, NIGHT],
  [345, PREDAWN],
  [405, SUNRISE],
  [480, MORNING],
  [660, DAY],
  [960, DAY],
  [1080, GOLDEN],
  [1170, SUNSET],
  [1215, BLUE_HOUR],
  [1290, NIGHT],
  [1440, NIGHT],
];
const SUN_UP = 390; // 6:30
const SUN_DOWN = 1185; // 19:45
const MOON_UP = 1110; // 18:30
const MOON_DOWN = 450 + 1440; // 7:30 the next morning

const hex = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mixHex = (a: string, b: string, t: number) => {
  const [x, y] = [hex(a), hex(b)];
  return `#${x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
};
function mixLight(a: Light, b: Light, t: number): Light {
  const out: Record<string, string | number> = {};
  for (const k of Object.keys(a) as (keyof Light)[]) {
    const x = a[k];
    const y = b[k];
    out[k] = typeof x === "number" ? x + ((y as number) - x) * t : mixHex(x, y as string, t);
  }
  return out as Light;
}

/** A body's place on its arc across the sky: up from behind the eastern peaks, over, and down behind the western. */
function arc(minutes: number, rise: number, set: number) {
  const m = minutes < rise && set > 1440 ? minutes + 1440 : minutes;
  const t = Math.min(1, Math.max(0, (m - rise) / (set - rise)));
  const height = Math.pow(Math.sin(Math.PI * t), 0.6);
  return { x: 110 + 600 * t, y: 150 - 92 * height, height };
}

/** The scene at a time of day: the blended look, where the sun and moon are, and a few words for screen readers. */
export function lodgeLight(m: number) {
  const i = DAY_KEYS.findIndex(([at]) => at > m);
  const [a, from] = DAY_KEYS[i - 1];
  const [b, to] = DAY_KEYS[i];
  const t = (m - a) / (b - a);
  const light = mixLight(from, to, t * t * (3 - 2 * t));
  const sun = arc(m, SUN_UP, SUN_DOWN);
  const moon = arc(m, MOON_UP, MOON_DOWN);
  const when =
    m < 345 || m >= 1290 ? "at night" : m < 420 ? "at dawn" : m < 600 ? "in the morning" : m < 1050 ? "on a summer day" : m < 1170 ? "at golden hour" : "at dusk";
  return { light, sun, moon, when };
}

/** Minutes past midnight, kept current. In development `?hour=18.5` pins the clock, to look at any time of day. */
function useMinutes() {
  const pinned = import.meta.env.DEV ? Number(new URLSearchParams(window.location.search).get("hour") ?? NaN) : NaN;
  const now = () => {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes();
  };
  const [minutes, setMinutes] = useState(now);
  useEffect(() => {
    if (!Number.isNaN(pinned)) return;
    const tick = setInterval(() => setMinutes(now()), 60_000);
    return () => clearInterval(tick);
  }, [pinned]);
  return Number.isNaN(pinned) ? minutes : (pinned * 60) % 1440;
}

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
const STARS = [[60, 34], [132, 22], [206, 52], [262, 30], [338, 56], [418, 22], [470, 60], [660, 40], [712, 70], [760, 30], [108, 80], [380, 36], [596, 24], [520, 44], [30, 60], [740, 58]];
// Two shapes for the smoke from the stove; it sways slowly between them.
const SMOKE = [
  "M354 142 C 349 134, 360 128, 356 120 C 352 112, 365 106, 362 96 C 359 87, 371 81, 371 72",
  "M354 142 C 351 133, 363 129, 360 120 C 357 111, 368 107, 367 97 C 366 88, 378 83, 380 73",
];
const MOONLIGHT = "#F1E6C6";

/**
 * The lodge by the lake, in layers, at the time of day it is now: sunrise over the eastern peaks, the sun across
 * the sky, golden hour, sunset, blue hour and the moon, on either theme (`dusk` only dims the daylight a little).
 * With `parallax`, the layers drift a few pixels with the pointer (nearer layers more), and the smoke sways.
 */
export function Scene({ dusk = false, parallax = false, className = "" }: { dusk?: boolean; parallax?: boolean; className?: string }) {
  const id = useId();
  const svg = useRef<SVGSVGElement>(null);
  const minutes = useMinutes();
  const { light: P, sun, moon, when } = lodgeLight(minutes);
  const alive = parallax && !reducedMotion();
  const sunR = 22 + 4 * (1 - sun.height);
  // The lake catches whichever is higher in the sky.
  const sunShows = P.sun * Math.min(1, sun.height * 2);
  const moonShows = P.moon * Math.min(1, moon.height * 2);
  const glintX = sunShows >= moonShows ? sun.x : moon.x;
  const glintAmount = P.glintOpacity * Math.max(sunShows, moonShows);
  // On the Dusk theme the daylight hours are shown a little dimmer, so midday doesn't glare off the dark page.
  const dim = dusk ? sunShows * (1 - P.lit) : 0;

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
      style={dim > 0.01 ? { filter: `brightness(${(1 - 0.16 * dim).toFixed(3)}) saturate(${(1 - 0.1 * dim).toFixed(3)})` } : undefined}
      role="img"
      aria-label={`A lodge by a mountain lake ${when}${P.lit > 0.5 ? ", its windows lit" : ""}`}
    >
      <defs>
        <linearGradient id={`${id}-sky`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.skyTop} />
          <stop offset="0.5" stopColor={P.skyMid} />
          <stop offset="0.85" stopColor={P.skyLow} />
        </linearGradient>
        <radialGradient id={`${id}-glow`}>
          <stop offset="0" stopColor={P.glow} stopOpacity={P.glowOpacity} />
          <stop offset="1" stopColor={P.glow} stopOpacity="0" />
        </radialGradient>
        <radialGradient id={`${id}-moonglow`}>
          <stop offset="0" stopColor={MOONLIGHT} stopOpacity="0.22" />
          <stop offset="1" stopColor={MOONLIGHT} stopOpacity="0" />
        </radialGradient>
        <linearGradient id={`${id}-sun`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={P.sunA} />
          <stop offset="1" stopColor={P.sunB} />
        </linearGradient>
        <linearGradient id={`${id}-moondisc`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#F3E9CA" />
          <stop offset="1" stopColor="#E4D6AE" />
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
        <mask id={`${id}-crescent`}>
          <circle cx="0" cy="0" r="18" fill="#fff" />
          <circle cx="8" cy="-6" r="16" fill="#000" />
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

      {P.stars > 0.01 && (
        <g fill={MOONLIGHT} style={layer(0.2)} opacity={P.stars}>
          {STARS.map(([x, y], i) => (
            <circle key={i} cx={x} cy={y} r={i % 3 ? 0.9 : 1.4} opacity={i % 2 ? 0.55 : 0.8} />
          ))}
        </g>
      )}

      {/* the moon and the sun on their arcs, each ringed like an elevation map */}
      <g style={layer(0.5)}>
        {P.moon > 0.01 && (
          <g transform={`translate(${moon.x.toFixed(1)} ${moon.y.toFixed(1)})`} opacity={P.moon}>
            <circle r="120" fill={u("moonglow")} />
            <g fill="none" stroke={MOONLIGHT} strokeWidth="1">
              <circle r="34" opacity="0.12" />
              <circle r="50" opacity="0.07" />
            </g>
            <circle r="18" fill={u("moondisc")} mask={u("crescent")} />
          </g>
        )}
        {P.sun > 0.01 && (
          <g transform={`translate(${sun.x.toFixed(1)} ${sun.y.toFixed(1)})`} opacity={P.sun}>
            <circle r="130" fill={u("glow")} />
            <g fill="none" stroke={P.glow} strokeWidth="1">
              <circle r={sunR + 14} opacity="0.24" />
              <circle r={sunR + 30} opacity="0.13" />
            </g>
            <circle r={sunR} fill={u("sun")} />
          </g>
        )}
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
        {glintAmount > 0.02 && (
          <g stroke={P.glint} strokeLinecap="round" strokeWidth="1.6" opacity={glintAmount} transform={`translate(${(glintX - 532).toFixed(1)} 0)`}>
            <path d="M512 168 H552" />
            <path d="M520 175 H546" opacity="0.8" />
            <path d="M526 182 H540" opacity="0.6" />
            <path d="M530 189 H536" opacity="0.4" />
          </g>
        )}
        <g stroke={P.glint} strokeLinecap="round" strokeWidth="1" opacity={P.glintOpacity * 0.45}>
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
        {P.lit > 0.01 && (
          <g opacity={P.lit}>
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
export function Badge({ children, className = "" }: { children: ReactNode; className?: string }) {
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
