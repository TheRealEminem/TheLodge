# The Lodge's own look

The Lodge keeps every family role, component and rule in the family's `DESIGN.md`. It changes the places the
family's `DESIGN.md` §2 leaves to each app, nudges the palette toward its own materials, and swaps the motif inside
`Ambient`, so it reads as a sibling and not as a copy of Trailmix.

**The idea:** *where the trail ends up.* Trailmix is out on the walk. The Lodge is the place you come back to,
where your people are: a cabin by a mountain lake, with a fire going.

## Palette: lake and lantern

Same roles, same pairs (`soft` + `deep`), every text pair at 4.5:1 or better. The values live in `identity/tokens.css`;
the tables in the family's `DESIGN.md` §3 describe Trailmix. The token names stay the family's (`forest`, `trail`,
`sun`, `sky`, `berry`), so components don't change; what they hold is The Lodge's own.

**Why it isn't Trailmix's green (chosen 2026-10-21).** The target is red-green colorblind eyes (protan/deutan type). Trailmix's
palette tells its meanings apart mostly by green against orange, pink and brown, which those eyes see as the same
olive. Simulated (Machado 2009, full strength), today's spruce and lingonberry dots were only 10 apart in deutan
vision (CIEDE2000; Dusk 5.9) and the tinted chips 2 to 3 apart, so "Added", "Them", "Reading" and plain chips looked
alike. The Lodge now puts every meaning on the axis those eyes keep, blue to yellow, or on a clear step of
lightness, and never on red against green alone.

| Token | Its job | Was (Day / Dusk) | Now (Day / Dusk) | Material |
| --- | --- | --- | --- | --- |
| `forest` | The main action, selection, links, tier bars, done | spruce `#1F5E4B` / `#52A487` | `#1D4F8C` / `#6AA0EC` | Lake at dusk |
| `trail` | Something went wrong; destructive hovers | `#DE5F31` / `#EC7347` | `#D4501C` / `#EF7A45` | Ember, a touch deeper |
| `sun` | Needs you | `#F2B13C` / `#F3B955` | `#F2B705` / `#F6C63C` | Lantern, brighter and yellower |
| `sky` | Working on it · You | `#457F9C` / `#7DB3CF` | `#3290CC` / `#A7D8F5` | Glacier, lighter than the lake |
| `berry` | Them | `#9A4F6B` / `#CC85A0` | `#5C2E1C` / `#D9C4AA` | Cedar (dark by day, birch by night) |

Closest pair of meanings, as dots and buttons (CIEDE2000, under ~10 they look alike): Day 13.7 → 21.4 protan,
10.0 → 19.6 deutan; Dusk 10.9 → 16.4 protan, 5.9 → 12.6 deutan. Tinted chips: Day 2.0 → 3.5 protan (5.8 between
everything but cedar), Dusk 2.2 → 6.2 deutan. Lake and glacier differ by lightness, which is all two blues can do
for these eyes; a chip always carries its word, and "Reading" also has a live dot.

White on lake is 8.2:1 (spruce was 7.6). White on ember is 4.2:1 (was 3.6). Glacier is 3.2:1 on the page, enough for
spinners and dots. Surfaces, ink, lines and shadows are unchanged: warm linen by day, a spruce-blue night by the lake.
To check a change, simulate it: the simulation script and the comparison page aren't kept in the repo.

The mark's tile is lake too (`#3B72B8 → #1D4F8C`), so the icon stands apart from Trailmix's green one in the Dock.

**Warm and cool (Sediment, 2026-10-29).** How someone seems to feel sits on the same blue–yellow axis: warm is lake
(`forest`, solid for very warm, about half strength for warm), cool is lantern (`sun`, solid for very cool, about
60% for cool), and mixed is neutral ink at low strength. "Not enough on file" is an empty band with a dashed line.
Never ember (`trail` stays for errors), never red against green, and every band, dot and gauge carries its word
("Warm", "Leans cool") beside it or in its label. The pieces are `STANCE` and `LEAN` in `modules/sediment/web/bits.tsx`.

## Artwork and atmosphere

| | Trailmix | The Lodge |
| --- | --- | --- |
| Mark | Low sun and a cream trail on a forest tile | Low sun and a cream A-frame on a lake tile (`Logo`) |
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
