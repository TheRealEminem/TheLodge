# The Lodge's own look

The Lodge keeps every family role, component and rule in the family's `DESIGN.md`. It changes the places the
family's `DESIGN.md` §2 leaves to each app, nudges the palette toward its own materials, and swaps the motif inside
`Ambient`, so it reads as a sibling and not as a copy of Trailmix.

**The idea:** *where the trail ends up.* Trailmix is out on the walk. The Lodge is the place you come back to,
where your people are: a cabin by a mountain lake, with a fire going.

## Palette

Same roles, same pairs (`soft` + `deep`), contrast equal to or better than Trailmix's on every pair. The values
live in `identity/tokens.css`; the tables in the family's `DESIGN.md` §3 describe Trailmix.

| Token | Trailmix Day / Dusk | The Lodge Day / Dusk | Why |
| --- | --- | --- | --- |
| `canvas` | `#F8F7F2` / `#0F1513` | `#F7F4EC` / `#0E1416` | Warm linen by day; a spruce-blue night by the lake |
| `surface` | `#FFFEFA` / `#18211D` | `#FFFDF8` / `#172023` | |
| `ink` | `#1C2922` / `#E9EDE8` | `#21271F` / `#ECEAE3` | Olive-black; candlelit paper at night |
| `ink-soft` | `#667269` / `#A1ADA5` | `#666A5F` / `#A9AAA1` | 5.0:1 and 7.9:1 on the canvas |
| `forest` | `#236347` / `#4FA27A` | `#1F5E4B` / `#52A487` | Spruce: a touch deeper and bluer |
| `trail` | `#E86636` / `#EE7445` | `#DE5F31` / `#EC7347` | Ember (white on it is 3.6:1, up from 3.3) |
| `sun` | `#F5B83A` / `#F2BE4E` | `#F2B13C` / `#F3B955` | Lantern |
| `sky` | `#4F86A8` / `#7FB2D3` | `#457F9C` / `#7DB3CF` | Lake |
| `berry` | `#9B5575` / `#CB86A6` | `#9A4F6B` / `#CC85A0` | Lingonberry |
| lines, shadows | forest-tinted | warm olive-tinted (`rgba(56,52,36,…)`, `rgba(40,36,22,…)`) | |

## Artwork and atmosphere

| | Trailmix | The Lodge |
| --- | --- | --- |
| Mark | Low sun and a cream trail | Low sun and a cream A-frame (`Logo`) |
| Hero art | `TrailScene`: rolling hills and a winding trail | `Scene`: snow-capped peaks, a lake with the far shore reflected, an A-frame tucked into pines, a fire with two log seats, a dock and a canoe. The cream path from Trailmix's scene leads up to the lodge door |
| Time of day | Day theme shows day, Dusk theme shows dusk | The scene keeps the clock on both themes (below) |
| Motion | A hiker walks the trail while recording | Smoke from the stove sways slowly (Home only, and never with reduced motion) |
| `Ambient` linework | Topographic contour rings in forest green | Growth rings: the end of a log, top right, with a smaller one bottom left. Rings are wide in the early years and narrow later, with runs of thin years, and a couple of drying checks. Drawn in warm cedar (`--grain`). They also echo the app's circles of closeness |
| `Ambient` glows | Sun and orange glows top right | A sun glow top right and a hearth glow low on the left (`--glow-hearth`), where the room's firelight would be |
| Empty-state badge | Contour rings around a summit | Growth rings around the heart of a log (`Badge`; the host also offers it as `ContourBadge`, the name family modules import) |
| Brand copy | "See you on the trail" | "Come on in" |

## The day in the scene

`Scene` blends between looks through the day by the computer's clock, updating each minute: night,
pre-dawn (a rose band behind the peaks), sunrise (alpenglow on the snow, mist on the lake), morning, midday,
golden hour, sunset (pink snow, the lights coming on) and blue hour. The sun rises from behind the eastern
(left) peaks at about 6:30, crosses the sky and sets behind the western ones at about 19:45; the moon follows its
own arc through the night, and the lake catches whichever is higher. The windows light up from late afternoon
until after sunrise. The looks are the `DAY_KEYS` in `identity/art.tsx`.

The cycle runs on both themes. On the **Dusk theme** the daylight hours are drawn a little dimmer (down to 84%
brightness at midday), so the picture doesn't glare off the dark page; evening and night are unchanged.

To look at any time while developing, add `?hour=18.5` before the `#` (for example
`http://localhost:5173/?hour=6.9#/`). It only works in development builds.

The lodge's own colors (cedar walls, a forest roof with cream trim, lit glass, the canoe) live in those looks,
next to the family's landscape colors. They are artwork, so they stay out of the tokens.
