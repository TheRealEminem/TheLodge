# The Trailmix family: design guide

This guide describes how Trailmix looks, moves and talks, so that new apps can join it as siblings: clearly
related, each with its own name and mark. It is written for a person or an AI agent building one of those apps.

**If you are an agent:** read this whole file before writing UI. A new app starts from `starter/` (read its
`ARCHITECTURE.md` too), which already contains the kit. To add the look to some other app, copy `kit/` into it
(see [Section 16](#16-files-in-this-folder)). Use the kit's classes and components instead of re-creating them, and
check the screenshots in `assets/screenshots/` against what you build. The rules in
[Section 14](#14-do-and-dont) are not suggestions.

**In this repository:** The Lodge is one of those siblings. What it does differently from Trailmix is in
[Section 17](#17-the-lodges-own-look); everything else here applies as written.

---

## 1. The idea

> A trail by day, and the same trail at dusk.

Trailmix looks like a well-made field notebook: warm, quiet, outdoorsy, and never cute about it.
Near-white, slightly frosted surfaces sit over a warm "trail-dust" background marked with faint
topographic contour lines. Color is rare and always means something. Forest green is for the main action,
trail orange for the one live thing (recording), sun yellow for "this needs you". Sky blue and berry tell
You and Them apart.

There are two themes, and both are designed: **Day** (light) and **Dusk** (dark). Dusk is not an
inverted Day. It is the same landscape after sunset: accents get lighter, text on accents turns dark, and
shadows turn black because there is no light left to tint them.

When something isn't covered here, ask: *would this feel at home in a good field notebook, on a quiet walk?*
That means calm before clever, warm before cool, and a few things done carefully.

## 2. What makes an app part of the family

| Shared by every app (don't change) | Each app makes its own |
| --- | --- |
| All tokens: colors, type scale, radii, shadows, easing | Name, wordmark and a lowercase tagline ("notes from along the way") |
| Fonts: Geist, Fraunces, Geist Mono | Its mark, built the same way as Trailmix's (see below) |
| Day and Dusk themes, following the OS by default | Its hero illustration, drawn from the same landscape palette |
| The component recipes: `.btn`, `.panel`, `.glass`, `.field`, `.chip`, `.well`… | Which action, if any, is its one "live" action in trail orange |
| Motion: hover lifts, press settles, content rises in | Its section icons and empty-state badges |
| The `Ambient` background (gradient, glows, contour lines) | Copy, within the voice rules in [Section 11](#11-voice-and-copy) |
| The app shell: 288px glass sidebar and an 872px reading column | |
| Voice: plain, warm, short | |

**The mark.** Every family mark is a 64×64 tile with `rx=16`, drawn in SVG. It uses a vertical gradient fill,
a faint lighter hill across the lower third, one or two thin contour lines (cream `#F4EEDC` at 13–20%
opacity), and a hairline white inner border (`stroke-opacity 0.16`). Trailmix puts a low sun (gradient
`#F8CB5A → #EE8540`) and a thick cream trail (`#F6EBCF`) on a forest tile (`#2F7B58 → #1B4E37`). A sibling
keeps the tile, the hills, the contours and the sun, and swaps the trail for its own motif in the same thick
cream stroke (a tent, a river, a summit flag, a compass needle). The tile can stay forest, which reads as most
"family". It can also use the deep end of another family accent, such as a sky tile `#4F86A8 → #285B7A`.
See `Logo` in `kit/src/components/illustrations.tsx` and `assets/logo.svg`.

**Menu bar and template icons** are line art of the same mark: 18×18, round caps, 1.3pt detail lines and a
1.9pt main stroke (see `reference/mac/Brand.swift`).

## 3. Color

Every color is a CSS variable in `kit/src/index.css`, exposed to Tailwind in `kit/tailwind.config.js`.
**Components never contain hex values.** The only exception is illustration artwork.

### Surfaces and text

| Token (Tailwind) | CSS var | Day | Dusk | Use |
| --- | --- | --- | --- | --- |
| `canvas` | `--bg` | `#F8F7F2` | `#0F1513` | Page background (warm off-white / deep green-black) |
| — | `--bg-top` | `#FCFBF8` | `#131B18` | Top of the page gradient (`Ambient`) |
| `glass` | `--surface` | white 72% | `rgba(28,38,33,.62)` | Frosted panels, with backdrop blur |
| `surface` | `--surface-solid` | `#FFFEFA` | `#18211D` | Opaque cards, dialogs, menus, fields |
| `surface-subtle` | `--surface-subtle` | `#F2F1EA` | `#141C19` | Wells, insets, segmented-control track |
| `ink` | `--text-primary` | `#1C2922` | `#E9EDE8` | Body text and headings |
| `ink-soft` | `--text-secondary` | `#667269` | `#A1ADA5` | Hints, metadata, secondary lines |
| `ink-faint` | `--text-tertiary` | `#939B94` | `#6E7A73` | **Icons, placeholders, separators only.** Too faint for reading (2.7:1). |
| `line` | `--border` | forest-black 10% | pale green 8% | Hairlines, panel borders, dividers |
| `line-strong` | `--border-strong` | 16% | 14% | Field and soft-button borders |

### Accents, and what each one means

Each accent has four parts: `DEFAULT` (fills, dots), `hover`, `soft` (a tinted background) and `deep`
(text on its own `soft`; the CSS var ends in `-ink`). Always pair `bg-X-soft` with `text-X-deep`.

| Family | Day | Dusk | Its one job |
| --- | --- | --- | --- |
| `forest` | `#236347` | `#4FA27A` | Primary actions, selection, focus, "done/healthy", links, the brand |
| `trail` (orange) | `#E86636` | `#EE7445` | **The app's single live action** (recording in Trailmix). Also errors and destructive hovers. |
| `sun` (yellow) | `#F5B83A` | `#F2BE4E` | "Needs you": attention, waiting on the user, highlights, flags |
| `sky` | `#4F86A8` | `#7FB2D3` | "Working on it" (in progress), "You", cloud/remote |
| `berry` | `#9B5575` | `#CB86A6` | "Them", the other party. Use it sparingly. |

`on-accent` is white in Day and near-black `#0D1311` in Dusk, which is how Dusk's lighter accents stay readable.
`btn-sun` always uses dark text `#2A2108`.

### Rules

- **Color is for meaning.** If a color doesn't carry one of the jobs above, use ink and surfaces instead.
- **One primary per screen.** Everything else is `btn-soft` or `btn-ghost`.
- **Tints come from opacity on the family colors** (`bg-forest/[.06]` for hover, `bg-forest/10` for counts,
  `border-trail/20` for callout borders). The `color-mix` wrapper in the Tailwind config makes this work.
  Never use Tailwind's `gray-*`, `slate-*`, `zinc-*`, or any default palette.
- **Shadows are tinted forest green in Day** (`rgba(22,40,30,…)`) and never pure black. Dusk uses black.
- **Selection** is forest at 20%. **Focus** is a 2px forest outline at 55% with a 2px offset, or a 3px
  forest 14% ring on fields.

Measured contrast: ink on canvas 14:1. `ink-soft` 4.7:1 (Day) and 7.9:1 (Dusk). Each `deep` on its `soft` is 5–7:1.
White on forest is 7:1. White on trail orange is only 3.3:1, so orange buttons stay short, semibold and at
least 14px.

## 4. Surfaces and depth

The page is built in three layers: the `Ambient` background, frosted chrome (sidebar and top bar), and
content panels.

| Class | Looks like | Use for |
| --- | --- | --- |
| `.glass` | `--surface` + 20px blur + saturate 1.5, `rounded-xl`, hairline, panel shadow, 1px inner top highlight | Panels that float over artwork or the ambient background |
| `.panel` | Solid surface at 88%, same edge and shadow | The default content container (settings groups, summaries) |
| `.inset-surface` | `surface-subtle` at 70% with an inset hairline, `rounded-lg` | Empty states and recessed areas inside a panel |
| `.chrome` / `.chrome-opaque` | `--sidebar-bg` + 18px blur | Sidebar and the narrow-window top bar |
| `.well` / `.well-forest` | 32px rounded-sm square, subtle fill (or forest-soft) | The icon holder at the start of rows and section headings |
| `.art-frame` | Hairline edge, `rounded-hero` (28px), bottom fades to transparent | Hero illustrations |

**Radii** (Tailwind's defaults are replaced): `xs 5` (code, kbd), `sm 8` (buttons-sm, fields, icon buttons,
wells), `md 12` (buttons, menus, nav items), `lg 16` (callouts, toasts, insets), `xl 22` (panels, dialogs),
`hero 28` (artwork), `full` (chips, switches).

**Shadows:** `sm` (resting controls), `md` (tooltips, the live record control), `lg` (menus, dialogs, toasts),
`panel` (two layers, very soft), `chrome` (sidebar edge), `focus`.

Every raised surface has `inset 0 1px 0 var(--highlight)`, a thin light line along its top edge. It's subtle,
and it's a large part of why surfaces look made rather than flat.

## 5. Type

Three typefaces, all self-hosted variable fonts through `@fontsource-variable`:

- **Geist** (`font-sans`) for all interface text.
- **Fraunces** (`font-display`) for titles and the wordmark only. It always gets
  `font-variation-settings: "opsz" 144, "SOFT" 30, "WONK" 0`, semibold, with tight negative tracking. Import
  `@fontsource-variable/fraunces/full.css`, because the plain import lacks the SOFT axis.
- **Geist Mono** (`font-mono`) for timers, durations, keys, paths and code. Numbers that change use
  `tabular-nums`.

**Size scale.** Use these names and never Tailwind's `text-sm`/`text-lg`. It's a dense, desktop-app scale.

| Class | Size | For |
| --- | --- | --- |
| `text-caption` | 11px | Chips, badges, key caps, the tagline |
| `text-meta` | 12px | Timestamps, footnotes, eyebrows, tooltips |
| `text-hint` | 12.5px | Hints under labels, secondary lines |
| `text-ui` | 13.5px | Controls, navigation, small buttons, fields |
| `text-label` | 14px | Row labels, buttons, the body default |
| `text-body` | 15px | Reading text (summaries, descriptions), line-height 1.7 |
| `text-heading` | 16px | Section headings: semibold, `tracking-[-0.01em]` |
| `text-lead` | 17px | Dialog titles |
| `text-wordmark` | 21px | The app name in the sidebar (Fraunces) |
| `.page-title` | clamp 26–32px | Page titles (Fraunces) |
| `.hero-title` | clamp 32–46px | One per hero (Fraunces, line-height 1.06) |
| `.hero-sub` | clamp 15.5–17.5px | The line under a hero, max 600px, `text-wrap: pretty` |

Weights: 400 for text, 500 (`font-medium`) for labels and buttons, 600 (`font-semibold`) for headings,
titles and the primary button. Never use bold 700. An **eyebrow** (`.eyebrow`) is meta size, medium weight and
`ink-soft`, in sentence case. Don't use uppercase letter-spaced eyebrows.

## 6. Layout and spacing

- **Shell:** `Ambient` fixed behind everything. A 288px `.chrome` sidebar with `border-r border-line
  shadow-chrome`, beside the content at `lg` (1024px) and above. Below that it becomes a drawer behind a 56px
  frosted top bar with a scrim. The full drawer pattern is in `reference/web/App.tsx`; the kit's shell just hides it.
- **Content column:** `mx-auto max-w-[872px] px-5 sm:px-8 lg:px-10 pt-7 lg:pt-12 pb-24`.
- **Sidebar inside:** brand block `px-6 pt-7 pb-5` (38px mark + wordmark + tagline), then the primary
  action as a full-width 44px button, a search field with a `⌘K` key cap, nav items (36px, `rounded-md`), and
  grouped lists under eyebrows. Settings and status sit at the bottom above a hairline.
- **Rhythm:** sections are `mb-10`. A section heading is a `.well-forest`, then a heading with a one-line
  blurb, `gap-3`. Panels are `px-5 sm:px-6` with `divide-y divide-line` rows. Rows are `py-3.5`, with
  `gap-3.5` between the well and the label.
- **Rows** (`ControlRow`): well, then label (`text-label font-medium`) with a hint below (`text-hint ink-soft`)
  on the left, and the control right-aligned. This is the pattern for every setting.
- Minimum window: 420×560. Everything must work at 375px wide with no horizontal scroll.

## 7. Components

All of these live in `kit/src/index.css` (classes) and `kit/src/components/ui.tsx` (React).

**Buttons:** `.btn` + a size + a variant.

- Sizes: `btn-sm` (32px, rounded-sm, text-ui), `btn-md` (40px, rounded-md), `btn-lg` (44px), `btn-hero`
  (52px, rounded-lg, text-body semibold).
- Variants:
  - `btn-primary`: forest, with a top-lit gradient, an inner highlight and a colored drop shadow.
  - `btn-record`: trail orange. Reserved for the live action.
  - `btn-sun`: yellow. For "needs you" calls to action.
  - `btn-soft`: surface with a strong hairline. The default secondary.
  - `btn-ghost`: text only, with a forest/6% hover.
  - `btn-danger-ghost`: ghost that turns trail-soft on hover. Use it for delete.
- Every button lifts 1px on hover (with a deeper colored shadow) and settles to `scale(0.98)` in 80ms on press.
  Disabled is 50% opacity. Icons sit at 16px (sm) or 18px, with a gap of 1.5–2.

**Icon buttons:** `.icon-btn` is 36px, `rounded-sm`, `ink-soft`, with a forest/6% hover and `scale(.94)`
on press. An invisible `::after` makes the hit area 2px larger. Every icon button needs `aria-label`,
and usually `data-tip` for a tooltip.

**Fields:** `.field` is rounded-sm with a strong hairline, a surface fill, `text-ui` and 7px vertical
padding. Hover darkens the border; focus gives a forest border at 55% plus the focus ring. A search field
in the chrome is borderless on `bg-forest/[.045]` and becomes a surface on focus.

**Select:** the custom `Select` listbox. It's a portal menu, `rounded-md`, `shadow-lg`, `animate-pop`, with
a check mark for the selected item, optional hint lines, type-ahead and full keyboard support. Use it
instead of the native `<select>`.

**Segmented:** a subtle track holding a sliding white thumb (300ms ease-out). Use it for themes, tabs and
small choices. The active item's icon turns forest.

**Switch:** 44×24, forest when on. The thumb springs across and stretches while pressed.

**Chips:** `.chip` is a 20px pill with `text-caption font-medium` and soft background plus deep ink.
`StatusChip` adds a 6px dot that breathes (`animate-soft-pulse`) while something is live. `SpeakerChip`
shows You in sky and Them in berry.

**Callouts:** for errors, `rounded-lg border border-trail/20 bg-trail-soft/70 p-4 text-label
text-trail-deep`, with a semibold first line ("The summary didn't come through") and the detail under it.

**Tooltips:** add `data-tip="…"` to any element, and one `<TooltipLayer/>` handles all of them. Tooltips are
dark in Day and light in Dusk, appear after 480ms (60ms when moving between tipped elements), and also show
on keyboard focus.

**Dialogs:** `useConfirm()` gives a promise-based confirm with a scrim and 3px blur. The dialog is
`rounded-xl`, 400px wide, `animate-dialog-in`, with a 40px well icon, a `text-lead` title and two buttons on
the right. Focus starts on Cancel. Destructive confirms use `btn-record`.

**Toasts:** `Toast` sits bottom center, `rounded-lg`, `shadow-lg`, with a well icon. Success toasts leave
after 3.4s; errors stay until dismissed.

**Loading:** `Skeleton` is a shimmer in the token colors. `Spinner` is a 14px currentColor arc. `Pulse` is a
ringed live dot.

**Empty states:** an `.inset-surface` containing a `ContourBadge` (an icon well at the summit of three
faint contour rings), a medium-weight line ("No tasks yet") and one `ink-soft` sentence saying what will
appear there.

**Long-form text:** `.prose-family` sets 15px with 1.7 line height. h2 headings carry a 28px
`well-forest` icon. Bullets are 5px forest/50% dots, links are forest with a 30% underline, and code sits on
`surface-subtle`.

**Key caps:** `.kbd` is mono, caption size, with a strong hairline and a 1px bottom "press" shadow.

**Scrubber:** `.range` is a 4px track filled forest up to `--pct`, with a 14px surface thumb ringed in forest.

### Simple by default, Advanced behind a disclosure

A Settings section shows the few choices most people want, in plain words, and nothing else. Everything else (the full
list, paths, sizes, delete, odd options) sits behind one **Advanced** disclosure at the bottom of the same section,
built with `Collapse` and closed on every visit (not remembered). The simple view must be enough on its own. Settings,
Your data is the model: Back up now and three or four restore choices ("An hour ago", "Yesterday", "Last week"), each with
its real date and time; under Advanced, the files on disk and the folder (`ARCHITECTURE.md` §7, backups).

## 8. Icons

The app uses one family only: **Lucide**, at **1.8 stroke**, in `currentColor`. Use 16px for everyday UI, 18px
for important controls and 20px for primary actions and dialog wells. Wrap new icons with the `icon()` helper in
`icons.tsx` so the defaults (and `aria-hidden`) apply. Icons in text color are `ink-soft` at rest, `ink` on
hover and forest when active. Outdoor icons (Compass, Leaf, Signpost, TreePine, Backpack, Flag) are welcome
for section headings; don't let them replace a clearer functional icon.

## 9. Motion

Movement is calm and physical: things lift when you point at them, settle when pressed, and rise gently
into place.

- **Easing:** `--ease-out` `cubic-bezier(.2,.8,.2,1)` for nearly everything. `--ease-spring`
  `cubic-bezier(.34,1.56,.64,1)` only for small playful moments (switch thumb, check pop, icon wiggle on
  the primary button).
- **Durations:** 140–180ms for hovers and color changes, 80ms for press, 200–300ms for menus, thumbs and
  collapses, 480ms for content entering.
- **Entrances:** `animate-enter` (fade + rise 8px). Stagger sibling blocks by 60ms with `animationDelay`.
  Menus use `animate-pop` (from -4px, scale .98), dialogs `animate-dialog-in`, and scrims `animate-fade-in`.
- **Live things:** `animate-soft-pulse` (opacity breathing, 2s), `animate-ring-pulse` (an expanding ring),
  and a hiker dot walking the hero trail while recording.
- **Parallax:** the hero art drifts up to about 5px with the pointer, with nearer layers moving more.
- **Reduced motion is always honored:** the global rule in `index.css` reduces all animation to nothing, and
  illustrations check `prefers-reduced-motion` before animating.

## 10. Atmosphere and illustration

This is what makes an app a Trailmix sibling rather than a generic Tailwind app.

- **`Ambient`** sits behind every screen. It has a vertical `bg-top → bg` gradient, a faint green glow
  low-center, warm sun and orange glows top-right, and two sets of hand-wobbled topographic rings at about 5%
  opacity, masked to fade out. Keep its structure. (The Lodge swaps the motif and one glow; see Section 17.)
- **Hero art** is layered flat-vector landscape in SVG: sky gradient, a sun (or a crescent moon with stars
  at dusk) ringed like an elevation map, mist, a far ridge with contour lines, middle hills with slender
  two-tier pines, near hills, a winding cream trail that narrows into the distance, and dark foreground
  framing. Use the `DAY` and `DUSK` palettes in `illustrations.tsx`. A sibling app draws its own scene
  (a campsite, a lake, a summit) from the same palettes and layer order.
- Art always sits in an `.art-frame` that fades into the page at the bottom, with a soft forest glow blurred
  behind it.
- Everything is drawn in code (SVG). The app uses no stock photos, emoji, 3D or gradient blobs.

## 11. Voice and copy

Plain, warm and brief, like a capable friend who also hikes.

- **Sentence case everywhere:** buttons, headings, menu items, chips.
- **Labels say what happens:** "New recording", "Summarize", "Delete", "Copy". Outdoor flavor belongs to
  brand moments only, such as hero titles ("Ready when you are", "On the trail"), sign-in ("See you on the
  trail"), status ("Trail conditions: Clear skies") and the tagline. Never put it in functional labels.
- **Hints explain consequences,** often as "Off: …": *"Off: the meeting waits for you to press
  “Summarize”."*
- **Errors say what happened, then what to do,** without blame: *"The summary didn't come through."* Then the
  reason and a fix.
- **Empty states** say what will appear: *"Your first recording will appear here."*
- Use curly quotes (“ ” ’), a real ellipsis (`Saving…`), `·` as a separator in metadata, and "You" and "Them"
  for the two sides. Don't use exclamation marks, "Oops", or emoji.

## 12. Accessibility

- Every interactive primitive in `ui.tsx` already has the right roles, keyboard handling and labels. Reuse
  them rather than rebuilding them.
- Icon-only buttons need `aria-label`. Decorative SVG needs `aria-hidden`. Illustrations get `role="img"`
  and a short description.
- Keep visible focus (`:focus-visible`) on everything.
- Never use `ink-faint` for text someone must read.
- Status is never color alone: chips always have a label.
- Pointer targets are at least 28px, with `icon-btn` enlarging the hit area.

## 13. Native (macOS / SwiftUI) parts

Native parts of a family app use the same palette through a `Brand` enum with light and dark pairs. See
`reference/mac/Brand.swift`:

```swift
static let forest = Color(light: 0x236347, dark: 0x4FA27A)
static let trail  = Color(light: 0xE86636, dark: 0xEE7445)
static let sun    = Color(light: 0xF5B83A, dark: 0xF2BE4E)
static let sky    = Color(light: 0x4F86A8, dark: 0x7FB2D3)
static let berry  = Color(light: 0x9B5575, dark: 0xCB86A6)
```

- Native UI uses the system font (SF): titles at 13pt semibold, details at 11pt `.secondary`, and timers at
  20pt semibold `.rounded`.
- Set `.tint(Brand.forest)`.
- The live button is a `RoundedRectangle(cornerRadius: 9, style: .continuous)` filled with `Brand.trail.gradient`,
  with a `trail.opacity(0.35)` shadow (radius 4, y 2).
- Speaker capsules are sky or berry at 18% opacity.
- Menu bar icons are template images of the mark's line art (see `reference/mac/MenuView.swift`).

## 14. Do and don't

**Do**

- Use the kit's classes and components first, and extend them in `index.css` under `@layer components` if
  something is missing.
- Give every new surface and color a Dusk version, and look at both themes.
- Keep one primary action per screen and one live action per app.
- Use `soft` + `deep` pairs for tinted UI.
- Stagger entrances by 60ms and honor reduced motion.
- Keep copy short, in sentence case, and say what happens.

**Don't**

- Don't put hex, `rgb()` or named colors in components (illustrations excepted).
- Don't use Tailwind's default palette (`gray-500`, `blue-600`…) or default type sizes (`text-sm`…).
- Don't add new radii, shadows or easing curves. If one seems needed, add it as a token, not inline.
- Don't use black shadows in Day, pure white backgrounds, or pure black text.
- Don't use orange for anything except the live action, errors and destructive hovers.
- Don't use bold 700, uppercase eyebrows, or Fraunces for anything smaller than a page title (the wordmark is
  the exception).
- Don't use the native `<select>`, `window.confirm`, or browser `title=` tooltips. Use `Select`, `useConfirm` and
  `data-tip`.
- Don't use emoji, stock photos, gradient blobs or glassmorphism beyond `.glass` and `.chrome`.

## 15. Pre-flight checklist

Run these from the new app's root before calling UI work done. Each should print nothing. They pass on the kit
itself; `illustrations.tsx` and `ui.tsx` are skipped because their colors are artwork and the switch thumb's
shadow.

```bash
grep -rnE '#[0-9a-fA-F]{3,8}\b|rgba?\(' src --include='*.tsx' | grep -v -e illustrations.tsx -e components/ui.tsx
grep -rnE '\b(gray|slate|zinc|neutral|stone|red|blue|green|amber|emerald)-[0-9]{2,3}\b' src
grep -rnE '\btext-(xs|sm|base|lg|xl|[2-9]xl)\b' src
grep -rnE '\bfont-bold\b|\buppercase\b' src
grep -rnE '<select\b|window\.confirm\(|<[a-z][a-z0-9]*\b[^>]*\btitle="' src --include='*.tsx'
```

Then look:

- Both themes: switch with the theme control, or set `localStorage["<app>.theme"]` to `"dusk"`.
- The layout at 375px wide and at 1440px wide.
- Keyboard only: can you reach and see everything?
- With reduced motion on.
- Next to `assets/screenshots/`: does it look like a sibling?

Note: after editing `tailwind.config.js`, restart the Vite dev server, because it doesn't hot-reload that file.

## 16. Files in this folder

```
DESIGN.md                    this guide
README.md                    how to start a new app with the kit
kit/                         a working React + Vite + Tailwind 3 app shell: copy it, or copy parts of it
  tailwind.config.js         tokens → Tailwind (radii and shadows replace the defaults)
  postcss.config.js
  index.html                 theme-color meta, favicon
  package.json               the exact dependencies (fonts, lucide-react, Tailwind 3)
  src/index.css              ★ all tokens (Day + Dusk), base styles, component classes
  src/theme.ts               Day/Dusk/System preference hook (rename its storage key per app)
  src/main.tsx               font imports
  src/App.tsx                the app shell + a live specimen of every component; replace its contents
  src/components/ui.tsx      Switch, ControlRow, Select, Segmented, Collapse, chips, tooltips, confirm, toast…
  src/components/icons.tsx   the Lucide wrapper and the icon set
  src/components/illustrations.tsx   Logo, TrailScene (landscape), Ambient, ContourBadge
starter/                     the architecture template: host + modules, already styled with this kit.
                             New apps start here; see starter/ARCHITECTURE.md
reference/                   Trailmix's original files, unchanged, for patterns in real use
  web/                       index.css, tailwind.config.js, theme.ts, App.tsx (drawer + top bar), Sidebar,
                             Settings (sections and rows), Summary (prose + heading icons), Recorder (hero)
  mac/                       Brand.swift (palette + mark), MenuView.swift (native menu styling)
assets/
  logo.svg, favicon.svg      the Trailmix mark
  screenshots/               the kit specimen in Day and Dusk, plus Trailmix itself at dusk
```

The kit differs from Trailmix's originals in four small ways:

- `ui.tsx` drops the Trailmix-only `ProviderSelect` and `TemplateSelect`.
- `StatusChip` takes a generic `tone` and `label`.
- `.prose-summary` is renamed `.prose-family`.
- The theme storage key is `app.theme`.

If the new project uses **Tailwind 4**, move the config's `theme` into an `@theme` block. The CSS variables
in `index.css` carry over unchanged.

## 17. Each app's own look

Everything above is shared by every family app. What Section 2 leaves to each app (its palette's values, mark,
scene, motif, badge and brand copy) lives in that app's `identity/` folder: `tokens.css` (colors, shadows,
atmosphere, for Day and Dusk), `art.tsx` (`Logo`, `Scene`, `Ambient`, `Badge`), `copy.ts`, `public/favicon.svg`
and `mac/` (`Mark.swift`, `AppIcon.icns`). The app's own design notes are in `identity/DESIGN.md`.
