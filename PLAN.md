# The Lodge: implementation plan

_Planning document, written 2026-10-08. Tick the boxes as chunks close. Work one chunk at a time and stop at its
"done when" so the owner can look before the next one starts._

The Lodge is DynaCRM (the owner's relationship CRM: who he knows, how well, and what he knows about them) rebuilt
as a native Apple silicon Mac app on the Trailmix family starter. This file says what we're building, what we
decided, and the order we build it in.

## Progress

| # | Chunk | Size | Status |
| --- | --- | --- | --- |
| 0 | Baseline: repo, toolchain, an empty app that launches | S | ☑ 2026-10-08 |
| 1 | Data layer on SQLite | M | ☑ 2026-10-08 |
| 2 | Graph, connection tiers, views, dashboard (API) | M | ☑ 2026-10-08 |
| 3 | The owner's real data across, with a parity report | S–M | ☑ 2026-10-08 |
| 4 | Identity, shell, Home, People, Organizations | L | ☑ 2026-10-08 |
| 5 | Profiles and manual editing | L | ☑ 2026-10-08 |
| 6 | Network canvas and path finder | M | ☑ 2026-10-10 |
| 6b | **People-first network: groups as gravity wells** | M–L | ☑ 2026-10-11 |
| 7 | AI layer in the host (structured output, providers, settings) | M | ☑ 2026-10-10 (Claude and Gemini paths wait on the owner's keys) |
| 8 | Ingestion pipeline (documents, notes, review, jobs) | L | ☑ 2026-10-12 (real-Claude canary waits on the owner's key) |
| 9 | Inbox and review screens | L | ☑ 2026-10-12 (spreadsheet mapping view moves to chunk 10) |
| 10 | Importers: spreadsheets, LinkedIn, recorded meetings | M | ☑ 2026-10-12 |
| 11 | Mac polish: mark, menu, signing, disk image | M | ☑ 2026-10-12 |
| 12 | Capture automation: Granola and calendars | M | ☑ 2026-10-12 |
| 13 | Cutover and hardening | S–M | ☑ 2026-10-23 (all in on the local app; Keychain dropped, see the result) |
| 14 | **Research flags: people who need deep research** (asked for 2026-10-12) | M | ☑ 2026-10-12 |
| 15 | **Find someone from Home; AI overviews and questions on profiles** (asked for 2026-10-13) | M | ☑ 2026-10-13 |
| 16 | **Profile pictures** (asked for 2026-10-13) | M | ☑ 2026-10-23 (by hand, and Gravatar if you allow it; Contacts matching not built) |
| 17 | **Shared Google Sheet: a second way in for anyone** (asked for 2026-10-18) | M | ☑ 2026-10-18 (not yet run against a real Google Sheet) |
| 18 | **Bulk research import, Gemini-shaped briefs, flagged duplicates** (asked for 2026-10-18) | M–L | ☑ 2026-10-19 (not yet run on a real Gemini report) |
| 19 | **The Lodge runs Gemini research itself** (asked for 2026-10-18) | M | ☑ 2026-10-19 (usual level: Better through Batch) |
| 20 | **Network presets: focused questions, and lists the AI writes** (asked for 2026-10-21) | M | ☑ 2026-10-21 (AI lists not yet run against a real model) |
| 21 | **Lake and lantern: a colorblind-safe palette for The Lodge** (asked for 2026-10-21) | S–M | ☑ 2026-10-21 |
| 22 | **On this Mac: a local-only path, recommended from the Mac's specs** (asked for 2026-10-23; family first) | L | ☑ 22a–f built 2026-10-23, in the family at c6f4648 (released as 0.4.0 on 2026-10-24) |
| 23 | **Backups that roll over** (asked for 2026-10-24) | S–M | ☐ the family spec is written (`ARCHITECTURE.md` §7); the code is being done in Traverse's `core/`, and The Lodge takes it with `scripts/sync-family` |

Milestones: **A** "it runs" = 0 · **B** "your data, natively" = 1–3 · **C** "browse and rate in the app" = 4–6
(The owner can stop using Docker for reading; AI intake still needs the old app) · **D** "feature parity" = 7–10 ·
**E** "shipped" = 11–13.

Sizes are relative effort (S ≈ one sitting, M ≈ a few, L ≈ many), not calendar time.

---

## 1. The idea in five lines

- The family starter (`_reference/Trailmix Design Family/starter/`) is a Python (FastAPI) server and a React web
  app, packaged in a small Swift menu-bar host that bundles its own arm64 Python and shows the UI in a WebKit
  window. Output: `dist-app/The Lodge.app` and a `.dmg`. Nothing to install, no Docker, no Postgres.
- DynaCRM is already that shape (FastAPI + React), so this is a **port onto the host**, not a rewrite.
- The scoring, tiers, graph search and page views already run in memory over a loaded snapshot (about 1,100
  lines). They port with only the loader replaced. The database-bound code is the real work: ingestion (931
  lines), spreadsheets (419), fuzzy matching, merge, the entity API and the timeline.
- The UI is re-skinned onto the Trailmix kit (Tailwind 3, tokens, hash router, `useLive`), so The Lodge looks and
  behaves like a sibling of Trailmix and can later merge with it as modules.
- Later, "other people in the owner's organization" means running the same server in Docker with real accounts. The
  starter only has a single shared token today, so that is future host work, not part of this plan (§7).

"Native" here means a real arm64 `.app` that installs by drag-and-drop, lives in the menu bar, runs offline, and
updates itself. The UI is WebKit, like Trailmix. A full SwiftUI rewrite is a different, much larger project and
would give up the family design, the browser and Docker options, and most of the existing Python (D1).

## 2. Decisions

Defaults are what we'll do unless the owner says otherwise. "Revisit" says when a decision gets reopened.

| # | Decision | Default | Revisit when |
| --- | --- | --- | --- |
| D1 | Architecture | Family starter: Python server + React in a WebKit window, Swift menu-bar host | Never, unless native-only features (widgets, Spotlight) become the point |
| D2 | App identity | Name **The Lodge**, id `lodge`, env prefix `LODGE`, port **8791**, tagline lowercase (proposal: "who you know, and how well"). The owner: a family tile with an A-frame roofline in place of the trail | Chunk 4 |
| D3 | Bundle ID | **`com.thelodge.app`** (chosen 2026-10-12). Permanent: changing it later breaks updates and granted permissions | Never |
| D4 | Modules in `app.json` | `["crm", "tasks"]`. `notes` stays in the repo as the reference module but is switched off | Chunk 4 |
| D5 | One module or several | One `crm` module (graph, tiers, inbox, importers). Splitting ingestion out would make it write another module's tables, which rule 1 forbids | When Trailmix merges in as `meetings` |
| D6 | Meetings and documents | Stay CRM-owned *interaction records* (they are the evidence behind relationships). A future `meetings` module publishes an event and the CRM links to it | Merge with Trailmix |
| D7 | Database | SQLite (WAL) + FTS5; fuzzy name matching in Python over an in-memory index | Chunk 1 (if matching quality regresses) |
| D8 | API keys | Entered by the owner in Settings → AI (write-only in the UI; stored in the app's SQLite file under `~/Library/Application Support/The Lodge/`). Env presets still work. Agents never read or copy the old `.env` or `API Keys/` | Chunk 13 (Keychain option) |
| D9 | AI roles | Extraction = Claude Opus 5.5, utility (column mapping, triage) = Gemini Flash, as chosen earlier. Local Ollama and others selectable | Chunk 22: new installs follow the path setup recommends; the owner's install keeps these |
| D10 | Signing | **Ad-hoc, chosen 2026-10-12**, until teammates exist. Ad-hoc means Gatekeeper's first-launch dance and permissions asked again after each update. Developer ID + notarization needs a paid Apple Developer account | Chunk 11 |
| D11 | Updates | **Manual disk image** (chosen 2026-10-12): `updateRepo` stays empty, because the starter's updater reads **public** GitHub releases and this repo is private. **Superseded 2026-10-22:** the repo is public and 0.3.0 has in-app updates with betas | Chunk 22d: Lockdown stops the automatic checks |
| D12 | "Live action" colour | Trail orange is reserved for one live action. The Lodge's default: none (orange only for errors, destructive hovers, and a "syncing" dot if chunk 12 happens) | Chunk 4 |
| D13 | Graph colours | Kind is carried by shape plus one tone; forest marks selection and your path; no new hues. Validate with the `dataviz` skill (colour-vision safe) | Chunk 6 |
| D14 | Perspective | `me` is passed as a parameter through the tier code, never read from a global, so a second user's view is possible later | Now (chunk 2) |
| D15 | Webhook | Kept, but only reachable in server mode (the local app listens on 127.0.0.1). Local capture is pull-based (chunk 12) | Chunk 10 |

## 3. What carries over and what changes

| DynaCRM | The Lodge |
| --- | --- |
| Postgres 17 + `pg_trgm` | SQLite + FTS5; trigram score in Python |
| SQLAlchemy async + Alembic | `db.query/execute` + append-only `MIGRATIONS` per module |
| UUID keys | Random text ids (`db.new_id()`); old UUIDs become their hex form |
| JSONB `attributes`, ARRAY `tags` | JSON text columns (`json_extract`, `json_each`) |
| `entities`, `relationships`, `notes` | `crm_entities`, `crm_relationships`, `crm_notes` |
| `ingestion_jobs` (state + proposal + result) | `crm_inbox` (proposal, review state) + host `core_jobs` (work state) |
| async routes, `asyncio.gather` imports (4 at once) | sync routes in the threadpool; host jobs with lanes (chunk 8) |
| Roles "extraction"/"utility" in `app_settings` | Host `ai.*` providers + `crm.extraction_provider` / `crm.utility_provider` |
| `.env` keys | Settings → AI |
| React 19, Tailwind 4, react-router, TanStack Query | React 18, Tailwind 3 + Trailmix tokens, hash router, `useLive` |
| nginx + Docker Compose (3 containers) | One `.app` (the same server still runs in Docker if wanted) |
| `.pytest_cache`, 1,186 lines of tests | Ported chunk by chunk; the tests are the safety net |

## 4. Invariants: lessons from DynaCRM, don't regress them

Each of these cost a debugging round. Port the tests that pin them.

1. **Claude structured output** needs the flat "strict" schema (every field required, `""` instead of null,
   `blank_to_none` after) or Opus answers "Schema is too complex". Use **streaming** (long outputs), `max_tokens`
   32000, never disable thinking, and send the `server-side-fallback-2026-07-01` beta with `fallbacks="default"`.
   The host's current `ai.complete` is non-streaming and 16,000 tokens: don't reuse it for extraction.
2. **Provider-wide failures stop the work** (no credit, bad key, bad model, rate limit, unreachable, any non-
   content 4xx/5xx). Only content failures (refusal, max_tokens, bad structure) may fall back to rules.
3. **A rules-based fallback result is never auto-applied.** It always goes to review.
4. **Ambiguous names are never auto-linked.** A name that matches several records waits for the owner.
5. **Dedupe by content hash** across live statuses *and* discarded, so re-importing a folder skips what the owner
   already threw away (the Cool Cap summary stays discarded).
6. **Serialize applies** and re-check for an exact existing match when creating, or concurrent jobs make
   duplicate people.
7. **Org matching ignores generic words** ("Foundation", "Consulting"…): Oak Foundation ≠ PGX Foundation.
8. **Spreadsheets:** placeholders ("na", "–", "?") are not names; a row can be an organization; a first name is
   matched against people at the *same organization* (by id), not globally.
9. **The owner's rating wins:** a `knows` edge with `properties.user_set` overrides the automatic tier.
10. **Michael Fairweather and Mickey Fairweather are different people.** Never merge them.
11. **Keys are the owner's to enter.** Agents never read `.env` or `API Keys/`, never ask for keys in chat, and never
    send the owner's email to an external service.

---

## 5. Chunks

Every chunk ends with `scripts/check` green (server tests, types, web build, style rules) unless noted.

### Chunk 0 · Baseline: repo, toolchain, an empty app that launches (S)

Goal: prove the build and packaging path before any CRM code exists. This is the part we can't test from a plan.

- [x] **Layout.** Copy `starter/` to the repo root so `app.json`, `core/`, `modules/`, `mac/`, `scripts/` sit in
  `TheLodge/`. Copy `DESIGN.md` to the root and fix the `../DESIGN.md` links. Move `DynaCRM (OLD)` and
  `Trailmix Design Family` into `_reference/` (git-ignored: the old folder holds `.env`, `API Keys/`, the data
  folder and a Postgres dump).
- [x] `git init`. `.gitignore`: `data/`, `dist/`, `dist-app/`, `build/`, `node_modules/`, `.venv/`, `_reference/`.
- [x] **`app.json`**: name, id, tagline, bundle ID, env prefix, port 8791 (add it to the port table in
  `ARCHITECTURE.md`), `modules: ["notes","tasks"]` for now.
- [x] **Python for development.** This Mac's `python3` is 3.9.6; the host needs 3.11+ (CI uses 3.12). Install one
  (Homebrew `python@3.12`, or `uv`) and point `scripts/dev` at it. The shipped app bundles its own 3.14, so this
  is a developer-only requirement. _Installing software: confirm with the owner first._
- [x] `scripts/check` is green on the untouched starter. `scripts/dev` serves on http://localhost:5173.
- [x] `scripts/build-app.sh` builds `dist-app/The Lodge.app`. Launch it with the isolated command from
  `ARCHITECTURE.md` §11 (`env -i … LODGE_DATA_DIR=/tmp/x LODGE_NO_OPEN=1 …`) and confirm the server answers.
- [x] **Spike:** add `python-docx`, `openpyxl`, `pypdf`, `python-pptx`, `python-dateutil`, `python-multipart` to
  `requirements.txt`, rebuild, and confirm they install into the bundled Python 3.14 (arm64 wheels, `lxml` is the
  one to watch). Record the app's size.

**Done when:** an empty "The Lodge" opens from `dist-app/` on this Mac and survives quit and relaunch; the document
libraries import inside the bundled Python.
**Depends on:** nothing. Needs the owner's yes for the Python install and the layout move.


_Result: Python 3.12 venv (Homebrew) for dev; `scripts/check` green (18 tests); `The Lodge.app` is 171 MB, bundled Python 3.14.7 imports docx/openpyxl/pypdf/pptx/lxml; isolated launch answers `/api/app`, no stray process. Not yet done by hand: opening the app window (the isolated test skips it)._

### Chunk 1 · Data layer on SQLite (M)

- [x] `scripts/new-module crm "People"`; set `modules` to `["crm","tasks"]`.
- [x] **Migration 1:** `crm_entities` (id, kind, name, summary, attributes JSON, tags JSON, occurred_at, is_self,
  source, created/updated), `crm_relationships` (source, target, kind, properties JSON, strength 1–5,
  started/ended, source, evidence_id), `crm_notes`, `crm_inbox`, and an FTS5 table. Keep the Postgres
  constraints: one `is_self` row (partial unique index), unique (source, target, kind), no self-loop, strength
  range, cascade on delete, evidence `SET NULL`. An expression index on `json_extract(attributes,'$.email')`.
- [x] Plain dataclasses `Entity`, `Edge`, `Note` using the **same attribute names** as the old ORM models, so the
  in-memory services port unchanged.
- [x] `store.py`: CRUD, `upsert_edge`, aliases, tags, merge (moves edges, notes and tags; keeps the loser's name as
  an alias; never makes a self-loop or a duplicate edge), delete, FTS reindex.
- [x] **Fuzzy matching without `pg_trgm`.** `resolve.py` scores names and aliases with a Python trigram similarity
  over an index cached until the host's change counter moves. Keep the thresholds and rules: exact email, alias
  0.97, the 0.6 match threshold, the generic-org-words rule, ambiguity.
- [x] Port `kinds.py` (unchanged), `edges.py`, and the CRUD routes (`entities`, `relationships`, `notes`) under
  `/api/crm/…`.
- [x] Port `test_entities.py` (CRUD, merge, alias matching, generic org words).

**Done when:** the ported tests pass, and a fixture of 30+ name pairs from the real data (Stacey Hollis/Hollys,
Oak/PGX Foundation, Michael/Mickey Fairweather, OEN/Northwest Entrepreneurship Network, "Dr. Rowe"/Dan Rowe…)
gives the same match / ambiguous / no-match verdicts the Postgres version gave (record them from the old app's
`find_candidates` before it is retired).
**Depends on:** 0.

_Result: `modules/crm` (kinds, model dataclasses, store, resolve, routes) with 15 tests; `scripts/check` green (28 tests). `word_similarity` reimplements pg_trgm's rule exactly (best Jaccard over a run of the text's trigram sequence), and the matcher gives the **same pick and ambiguity as Postgres on all 1,430 recorded queries** (real names, recorded from the old app into `modules/crm/tests/fixtures/real_names.json`, git-ignored; the test skips without it). Not done in this chunk: the entity list has no subtitle/degree/last-interaction yet (they come with the views in chunk 2); the web half is still the template placeholder (chunk 4)._

### Chunk 2 · Graph, connection tiers, views, dashboard (M)

- [x] `load_snapshot()` (entities + edges) cached until the host change counter moves.
- [x] Port `graph.py` (BFS paths, ego network, overview), `connections.py` (tiers; takes `me_id` as a parameter,
  D14), `views.py`, `dashboard.py`, `timeline.py`, `summaries.py`.
- [x] Routes: `/people`, `/organizations`, `/entities/{id}` with `/context`, `/timeline`, `/notes`, `/graph`,
  `/graph/paths`, `/dashboard`, `PUT /people/{id}/connection`, `/me`.
- [x] `Module.search` (FTS5 + fuzzy) and `Module.describe` for the host's ⌘K search and link lists.
- [x] Port the demo seed and `test_connections.py`, `test_graph.py`, the dashboard test.

**Done when:** the tier, rating, org-scope, profile-context and big-event tests from DynaCRM pass **unchanged**
(same expected tiers), and `/docs` lists the endpoints.
**Depends on:** 1.

_Result: `snapshot.py` (cached against `store.version()`), `connections.py`, `views.py` (`views.get(me_id)`, perspective-aware, D14), `graph.py`, `timeline.py`, `listing.py`, `dashboard.py`, `seed.py`, `routes_people.py`; 18 endpoints under `/api/crm`. The old tier, rating, org-scope, profile-context, big-event and path tests pass with their **original expectations** (only the client calls changed); 43 tests in total, `scripts/check` green. Differences from the old API: ids are text, `GET /me` returns the full entity, and the dashboard counts the inbox from `crm_inbox`. Not yet measured: speed on large data (chunk 13)._

### Chunk 3 · The owner's real data across, with a parity report (S–M)

- [x] `scripts/import-dynacrm`: reads the old Postgres (the running container on 127.0.0.1:5433, or the dump
  restored to a scratch DB) and writes `crm_*`: UUID → hex ids, tags, aliases, attributes, **all notes including the
  original transcripts**, edges with `user_set` and `evidence_id`, and the ingestion-job history (content hashes
  and statuses) so FirstData is still treated as already imported and discarded files stay discarded.
- [x] Idempotent (upsert by id). Never touches settings or keys.
- [x] `scripts/parity`: compares old API and new for counts per kind, edge counts, tier distribution, the top-25
  `/people` order, org scopes, and ten random profile contexts.
- [x] Copying, not re-running the AI import: re-extraction would cost Opus credits and give different results.

**Done when:** parity reports no unexplained differences. For reference, on 2026-09-26: 128 people besides the owner, 175
organizations, 38 topics, 27 documents, 12 meetings; tiers 9 strong / 12 working / 58 light / 29 indirect /
20 not linked; org scopes 90 / 151 / 24 / 175.
**Depends on:** 2. **Milestone B.**

_Result: `scripts/import-dynacrm.py` (writes to `./data` by default, a scratch copy; pass `--data-dir` for the real app folder at cutover) and `scripts/parity.py` (old API on :8010 vs the new one). Copied 381 entities (129 people incl. you, 175 organizations, 38 topics, 27 documents, 12 meetings), 839 relationships, 589 notes (37 over 5,000 characters, i.e. transcripts, intact) and 108 inbox rows; a second run changes nothing. **Parity: 153 checks, no differences** (dashboard, people in four sorts, organizations in three scopes, context + detail + timeline for 38 pages, paths for ten targets in both modes, entity lists for every kind, graph overview). Differences fixed on the way, all in the new code: relationship ties now ordered by (time, id), "who brought them up" by (count, name), timelines by (time, id), org timelines include your own meetings when you work there. One deliberate change: for the 13 people with several current employers the old app named a different employer in lists than on profiles; The Lodge uses the newest everywhere (parity skips those employer fields). Timestamps are now stored with microseconds. psycopg was installed in `.venv` for the import script only (not in `requirements.txt`)._

### Chunk 4 · Identity, shell, Home, People, Organizations (L)

- [x] **Identity (D2, D12):** name, tagline, the mark (`Logo` in `illustrations.tsx`, `favicon.svg`), decide the live
  action. Follow `DESIGN.md` §2.
- [x] `modules/crm/web/index.tsx`: nav (People, Organizations, Network, Meetings & docs, Inbox with a badge),
  routes under `crm/…`, a Home card, the API client.
- [x] Home: tier tiles, strong, working, "lit up by your meetings", reconnect, where you know people, meetings per
  week (with its table view).
- [x] People: tier filter with counts, search, organization and tag filters, sorts. Organizations: the four scopes
  ("where you know people" by default), contacts per organization.
- [x] Rebuild with the kit's components (`Section`, `ControlRow`, `Select`, `Segmented`, chips, `Skeleton`, empty
  states, `useConfirm`, `data-tip`) and `useLive`. **No** TanStack Query, react-router, `confirm()`, native
  `<select>`, uppercase eyebrows, bold 700, raw colours, or default Tailwind sizes. The tier signal-bars glyph
  stays (ordinal, always beside a text label).
- [x] Day and Dusk, at 375 px and 1440 px.

**Done when:** `scripts/check` is clean including the §15 rules, Day and Dusk screenshots sit next to
`assets/screenshots/` and read as a sibling, the real data renders, and ⌘K finds people and organizations.
**Depends on:** 3.

_Result: `modules/crm/web/` (api, tier, bits, People, Organizations, Home block, ActivityChart, a stand-in profile at `#/crm/e/:id`); real data renders. Identity: the A-frame lodge mark (`Logo`, `favicon.svg`), no orange live action (D12 default). Host changes: the hash router gained query params (`useQueryParams`, so filters live in the URL), `ModuleWeb.homeWide` (a module can lay out its own Home sections), more icons, and a fix to the starter's dev proxy (`"/api"` also caught the web app's own `api.ts`, giving a blank page in `scripts/dev`; now `"^/api/"`). Search ranks name matches above mentions. Checked: `scripts/check` green (43 tests, types, build, style rules); Dusk and Day at 1280 px with real data, Day at 375 px with no horizontal scroll, tier filter via URL, ⌘K search. **Not yet checked:** keyboard-only pass, reduced motion, Dusk at 375 px, side-by-side with the kit screenshots (the owner to eyeball). Navigation shows only People and Organizations; Network, Meetings & docs and Inbox arrive with their chunks._

### Chunk 5 · Profiles and manual editing (L)

- [x] Person profile tabs (Overview, Meetings, Documents, People, Notes & history), the "You & them" card with
  rating dots and "Use automatic", Work & affiliations.
- [x] Organization profile (Your way in, people groups, related organizations, latest), meeting / document / topic
  pages with tier badges on attendees.
- [x] Create and edit entities, add relationships (strength, since), notes, merge, delete, "This is me".
- [x] `Module.describe` so the host's `LinkedList` can show a person or meeting from a task (already registered in chunk 1; not exercised in the UI yet, since no module links to these records).

**Done when:** every action DynaCRM profiles had works, and changing a rating moves Home's tiers live.
**Depends on:** 4.

_Result: `Profile.tsx` (person with Overview / Meetings / Documents / People / Notes and history tabs; organization with Your way in, people groups, related organizations, latest; topic; meeting and document pages with tier badges), `cards.tsx` (You & them with rating dots and "Use automatic", work and affiliations, how you're connected, timeline, notes, relationships), `forms.tsx` (dialog, entity picker, create/edit, merge, add relationship), `Library.tsx` (Meetings and documents list with Documents and Topics tabs; added so these records can be browsed). Create buttons on People and Organizations. Tab state is in the URL (`?tab=`). Verified in the browser with a throwaway copy of the real data: rating (live, "set by you"), tabs, edit dialog, notes (appears on the timeline), organization and meeting pages, picker and merge dialog, no horizontal overflow at 375 px. Bug found and fixed: dialogs inside an animated ancestor were mispositioned (a transformed parent becomes the `fixed` box), so `Dialog` renders in a portal. Not exercised by hand: delete confirm, creating a record through the dialog, merge completion (merge itself is covered by the chunk 1 tests), keyboard-only pass. "Mini network" neighbourhood graph and the Network button arrive with chunk 6._

### Chunk 6 · Network canvas and path finder (M)

- [x] Keep `react-force-graph-2d` (the one web dependency this app adds, because it earns its place). Colours from
  CSS variables, kind by shape (D13), selection and path in forest, kind filters, focus and depth, legend.
- [x] "How do I reach X?" ranked by tie strength, optionally through people only.
- [x] A table alternative for accessibility. Check WebKit canvas performance at the 600-node cap.
- [x] Validate the palette with the `dataviz` skill.

**Done when:** paths for ten sample targets match the old app, it works by keyboard, and it looks right in both themes.
**Depends on:** 5. **Milestone C.**

_Result: `Network.tsx` (kind filters, focus + depth, "Find path to…", side panel with paths and the selected record, Graph/List toggle), `NetworkCanvas.tsx` (react-force-graph-2d, lazy-loaded as its own 186 kB chunk), `graphShapes.tsx`, `GraphLegend.tsx`, and a Neighborhood card on person and organization profiles with an Open link. Encoding (D13): kind = shape (circle, square, diamond, page, hexagon); how well you know a person = fill style (solid forest, lighter forest, forest ring, dotted ring), everything else neutral; selection = ink ring; the highlighted path = forest links with the rest dimmed. No new hues, and nothing depends on colour alone (tier is also in the legend, tooltip, side panel and list). The dataviz validator is for categorical palettes (it says so), so it wasn't applicable to an ordered scale; contrast and redundancy rules were applied by hand. Server: graph nodes carry `tier`. Host: routes can be `wide` (`ModuleWeb.routes[].wide`). Verified in the browser on a copy of the real data: 354 nodes render, focus on a person, a highlighted path to an organization, list view (354 rows) and selection panel, no horizontal overflow at 375 px. Path results come from the same code that matched the old app in chunk 3 (graph overview parity now differs by the added `tier` field, which `scripts/parity.py` ignores); I did not rerun the old-app comparison this chunk. Not done: keyboard navigation inside the canvas itself (the List view is the accessible route), a Day-theme look at the graph, and zoom-to-fit is loose on a phone (a few distant nodes shrink the layout)._

### Chunk 7 · AI layer in the host (M)

- [x] `ai.structured(prompt, system, schema, choice)`: adapters ported from DynaCRM: Claude (strict flat schema,
  streaming, fallback beta; invariant 1), Ollama native (`format`, `num_ctx`), OpenAI-compatible (json_schema →
  json_object → plain, one repair retry). `AIError.provider_down` (invariant 2).
- [x] Module settings `crm.extraction_provider` and `crm.utility_provider` (auto or a provider id), a Settings
  section that shows which model does which job, a "Test" per provider.
- [x] Keys via Settings (D8). `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` env presets still work.
- [x] Host tests with fake transports: stream fakes, error classification (credit, auth, rate, too long, refusal,
  max_tokens), the repair retry.

**Done when:** "Test" passes for each provider the owner configures, and a structured call round-trips a sample schema.
**Depends on:** 0 (can run in parallel with 4–6).

_Result: `ai.structured(prompt, system, Schema, choice, max_tokens)` returns `(validated object, provider id)`; adapters are in `core/server/ai_adapters.py`, schema helpers in `ai_schema.py` (ported from DynaCRM). Claude: flat strict schema, streamed, `server-side-fallback-2026-07-01` beta on the models that take it, thinking never touched, 32000 tokens. Ollama: native `/api/chat` with `format` and a context window sized to the prompt (8k to 32k), kept loaded 5 min so a batch doesn't reload the model. OpenAI-compatible (OpenAI, Gemini through its compatibility endpoint, DeepSeek, custom): json_schema, then json_object, then plain with the shape in the prompt, plus one repair retry. `AIError.provider_down` is true for anything that says nothing about the text (no credit, bad key or model, rate limit, unreachable, any other request error) and false for refusal, out of output space, wrong shape and over-long input; a fallback chain is provider-down only if every provider tried was. Module jobs: `modules/crm/server/roles.py` (`crm.extraction_provider` defaults to Claude, `crm.utility_provider` to Gemini, either can be `auto` = the app-wide provider or any provider id; `roles.structured(role, …)` is what chunk 8 calls). Settings: the AI section can now set up any provider (key, model, Test), not just the first one, and a "People: AI jobs" section shows which provider and model does each job and whether it's ready, with a Test per job. "Test" is a real structured round trip, so it proves the way jobs will call it. Env presets (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) still work. 41 new host tests with fake transports (`core/tests/test_ai.py`); `scripts/check` green with 85 tests. **Verified live:** the Ollama test against your local `qwen2.5:7b` (structured output works, 0.7 s warm) and the Settings screens. **Not verified:** the real Claude and Gemini calls, which need your keys; Claude's streaming and schema path is only tested against a fake of the SDK. The first real "Test" for Claude is the check. Also the `ai.complete` path (summaries) is unchanged apart from carrying `provider_down`._




_Result: server `people_net.py` (derives the people-only graph and the groups from the snapshot, cached on `store.version()`), `routes_network.py` (`/network`, `/network/groups/{id}`, `/network/evidence/{person}`, `/network/paths`, `/network/tags` GET and POST, `/network/views`), `crm_views` table (migration 2). On the owner's real data: 129 people, 156 lines (96 direct, 54 mentioned together, 6 met; 92 of them go through the owner, so without "Your ties" the network is 64 lines among 48 people), and **73 groups** (22 organizations, 16 topics, 35 tags) with 75 people in more than one. Lines say why in words ("Both took part in X", "Y came up in Z"). Topics need a score of 2 (took part = 2, came up = 1), so one passing mention doesn't make someone part of a topic; hand-linked (`related_to`) counts. Same employer is a group, never a pile of lines; the owner himself is in no group. Web: new `NetworkCanvas.tsx` (people only; each switched-on group is an invisible anchor the members are pulled toward, so someone in two groups sits between them; soft labelled outline per group, solid ring organization / dashed topic / dotted tag, labels stack when groups share a top edge; people outside the groups fade; evidence satellites for the selected person), `Network.tsx` (group chips, "Biggest" suggestions, search picker, saved views, Your ties, focus, path finder over people, side panels), `NetworkPanels.tsx` (person, group, picked-people panels, tag editor), `GroupsPage.tsx` (Organizations, topics and tags in one list), profile card "Their circle" (person) or "Their people" (organization, drawn as its group). Sidebar is now People, Network, Groups, Tasks; organizations, meetings and documents, and topics are still there as routes, linked from the Groups page. 12 new server tests (`test_network.py`); `scripts/check` green with 97 tests. **Verified in a browser on the real-data copy:** groups switched on from the URL (BVC with mentor; Cinder Labs with vaccine cold chain with mentor), selecting a person (panel, why-lines, tags, satellites), adding a tag from the panel (saved), the Groups page, an organization profile card, Day theme and a 390 px phone with no horizontal overflow. **Not exercised by hand:** shift-click picking and the bulk tag panel, Save view and Delete view dialogs, focus mode and the path finder in this new view (the server side of all three is tested), keyboard-only use of the canvas (the List view is the accessible route). Known rough edges: when two groups share most of their people their outlines sit almost on top of each other (that's the overlap, but it can be hard to read), and a person with many groups gets a long chip list in the panel._

### Chunk 7 · AI layer in the host (M)

- [x] `ai.structured(prompt, system, schema, choice)`: adapters ported from DynaCRM: Claude (strict flat schema,
  streaming, fallback beta; invariant 1), Ollama native (`format`, `num_ctx`), OpenAI-compatible (json_schema →
  json_object → plain, one repair retry). `AIError.provider_down` (invariant 2).
- [x] Module settings `crm.extraction_provider` and `crm.utility_provider` (auto or a provider id), a Settings
  section that shows which model does which job, a "Test" per provider.
- [x] Keys via Settings (D8). `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` env presets still work.
- [x] Host tests with fake transports: stream fakes, error classification (credit, auth, rate, too long, refusal,
  max_tokens), the repair retry.

**Done when:** "Test" passes for each provider the owner configures, and a structured call round-trips a sample schema.
**Depends on:** 0 (can run in parallel with 4–6).

_Result: `ai.structured(prompt, system, Schema, choice, max_tokens)` returns `(validated object, provider id)`; adapters are in `core/server/ai_adapters.py`, schema helpers in `ai_schema.py` (ported from DynaCRM). Claude: flat strict schema, streamed, `server-side-fallback-2026-07-01` beta on the models that take it, thinking never touched, 32000 tokens. Ollama: native `/api/chat` with `format` and a context window sized to the prompt (8k to 32k), kept loaded 5 min so a batch doesn't reload the model. OpenAI-compatible (OpenAI, Gemini through its compatibility endpoint, DeepSeek, custom): json_schema, then json_object, then plain with the shape in the prompt, plus one repair retry. `AIError.provider_down` is true for anything that says nothing about the text (no credit, bad key or model, rate limit, unreachable, any other request error) and false for refusal, out of output space, wrong shape and over-long input; a fallback chain is provider-down only if every provider tried was. Module jobs: `modules/crm/server/roles.py` (`crm.extraction_provider` defaults to Claude, `crm.utility_provider` to Gemini, either can be `auto` = the app-wide provider or any provider id; `roles.structured(role, …)` is what chunk 8 calls). Settings: the AI section can now set up any provider (key, model, Test), not just the first one, and a "People: AI jobs" section shows which provider and model does each job and whether it's ready, with a Test per job. "Test" is a real structured round trip, so it proves the way jobs will call it. Env presets (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) still work. 41 new host tests with fake transports (`core/tests/test_ai.py`); `scripts/check` green with 85 tests. **Verified live:** the Ollama test against your local `qwen2.5:7b` (structured output works, 0.7 s warm) and the Settings screens. **Not verified:** the real Claude and Gemini calls, which need your keys; Claude's streaming and schema path is only tested against a fake of the SDK. The first real "Test" for Claude is the check. Also the `ai.complete` path (summaries) is unchanged apart from carrying `provider_down`._


### Chunk 6b · People-first network: groups as gravity wells (M–L)

The owner's direction (2026-10-11): the app is about **how people connect to people, and why**. Documents and meetings are
the evidence underneath and show only when you click a person. Organizations are not nodes: they're **groups of
people**, drawn as gravity wells. Topics (and free tags like hardware, customer, mentor) are another kind of well, so
the network can be browsed by interest or profession.

Proposed decisions (change any of them):

- **D16 Only people are nodes.** Edges are person to person, each with a *why*. Direct ones are the 97 `knows`,
  `introduced_by` and `reports_to` edges; derived ones come from shared meetings, the same organization and being
  mentioned together, each carrying its evidence (click a line: "met in Northwest Innovation Showcase; both work at BVC").
  Most of the connection today is indirect (233 `mentioned_in`, 182 `works_at`, 105 `discussed_in`, 60 `attended`),
  so without derived links the people-only graph would be nearly empty.
- **D17 A well is a named set of people.** One mechanism, three sources: an organization (works at / advises /
  invested in), a topic (people linked to it through their meetings and documents, or directly), or a **tag** you put on
  people (the 18 mentors, 18 founders, 15 prospects already in the data). Members are pulled toward a shared centre and
  a soft outline with a label is drawn behind them. Identity is the label plus the outline style (solid = organization,
  dashed = topic, dotted = tag), never a new colour (D13).
- **D18 Someone in several wells stays one node**, placed at the weighted middle of the wells that are switched on, so
  the overlap between two wells *is* the people who bridge them. Only the wells you switch on (chips above the canvas,
  default none, suggested 3 to 6) pull and draw; clicking a person lights up every well they belong to. Nothing needs
  duplicating or choosing a "primary" organization.
- **D19 Documents and meetings hide until a person is selected,** then fan out as small satellites (and list in the side
  panel). The "Meetings and documents" library stays but moves out of the main navigation.
- **D20 Tagging is quick and bulk:** select people in the network or a list, add or remove a tag, save the current set of
  switched-on wells as a named view. Tags are free text; nothing to set up first.

Steps:

- [ ] Server: `GET /graph/people` (nodes = people; edges with kind direct/derived, weight, reasons) and
  `GET /groups` (organizations, topics, tags with members and why each is a member), computed from the snapshot.
- [ ] Canvas: people only; well force (members attracted to their centre, bridging people to the weighted middle),
  soft hulls with labels, chips to switch wells on and off, hover and click to light up a well or a person's wells,
  selected person fans out their meetings and documents. Tier styling stays.
- [ ] Tags: add and remove on a person, bulk from a selection, saved views.
- [ ] Reframe the rest to match: Organizations page becomes Groups (organizations, topics, tags); profile neighbourhood
  card uses the same people-only view; keep parity checks for anything the old app also computed.

**Done when:** on your real data, switching on "BVC" and "mentor" shows two labelled clusters with the people in both sitting
between them; clicking a person shows why each line to them exists and their documents; tagging three people "hardware"
and switching that tag on pulls them together.
**Depends on:** 2, 6. Independent of 7 to 13, so it can go before chunk 8.

### Chunk 8 · Ingestion pipeline (L)

- [x] `crm_inbox` lifecycle (pending → review → applied / discarded / failed / skipped) with host jobs
  `crm/extract`.
- [x] **Job lanes** (small host change): cloud providers run 4 at a time, a local model runs 1. The host's single
  worker would turn DynaCRM's 3½-minute import into about an hour.
- [x] Port `documents.py` (docx incl. tables, pdf, pptx incl. notes, txt, md), triage, extraction schema and
  prompts, the proposal builder, `apply` (global lock, exact-match recheck), `needs_review`, content-hash dedupe
  (invariants 3–6), and the rules-based fallback.
- [x] Provider-down raises `jobs.Wait("Anthropic is out of credit…")`: the batch parks with a reason and resumes
  on **Go** after the owner tops up, instead of failing everything.
- [x] Publish `actions.found` for a meeting's action items, so the existing `tasks` module creates follow-ups
  linked back to the meeting.
- [x] Port `test_ingest.py`, `test_llm.py` and the file-batch tests.

**Done when:** tests are green with a fake AI; one real canary document (the owner's key, one FirstData file) yields
the same shape of proposal as DynaCRM did; killing the server mid-batch and restarting resumes with no duplicates.
**Depends on:** 2, 7.

_Result: host: job **lanes** (`jobs.register(..., lane="cloud")` runs four at a time; a function of the target can choose per job; everything else stays one at a time; `jobs.waiting(module, kind)`; `Module.lanes`). CRM: `inbox.py` (the `crm_inbox` table's access), `documents.py` (docx incl. tables, pdf, pptx incl. speaker notes, txt, md, the content hash), `extraction.py` (the `Extraction` and `Triage` schemas, the prompts, the rules-based reader), `ingest.py` (job creation, triage, context, extraction, proposal, apply, the host job `crm/extract`), `routes_ingest.py` (`/api/crm/ingest/notes`, `/files`, `/jobs`, `/jobs/{id}` with `apply`, `discard`, `retry`, `/jobs/apply-ready`, `/summary`, `/resume`). Behaviour: the extraction job is in the cloud lane when a cloud model does it and in the one-at-a-time lane for a local model or rules; a provider-wide failure puts the item back in line, trips a 60 second breaker so the rest of the batch parks without being tried, and shows the reason ("AI provider unavailable: Claude (Anthropic): The Anthropic account is out of credit… Press Resume when it's fixed."); **Resume** (or changing any AI or People setting, which is usually the fix) sends everything parked on its way; a content failure falls back to rules with a warning and is never auto-applied; ambiguous names are never auto-linked; apply is one transaction under a lock with an exact-match re-check, so a failure changes nothing; discarded and already-imported content is skipped with a reason; an applied meeting publishes `actions.found` (its whole list, which is what the tasks module replaces a source's open tasks with) and the tasks module turns them into tasks. A new "Rules only (no AI)" choice for each People AI job. Spreadsheets are recorded as "not supported yet" (chunk 10), and the meeting and webhook routes also come in chunk 10 (the meeting pipeline itself is here and tested through `ingest.create_meeting_job`). 29 new tests (`test_ingest.py`, three more in `test_core.py`), run six times in a row without a flake; `scripts/check` green with 126 tests. **Verified live** with the local `qwen2.5:7b` on three of your real notes, in a scratch copy of the data: proposals have the same keys as DynaCRM's, link to your existing people (Stacey Hollis, Dan Rowe, Mickey Fairweather…) and read sensibly for a 7B model (10 and 7 entities where Opus found 16 and 9); the local lane ran them one at a time; killing the server with -9 mid-batch and starting it again finished all five items exactly once with no duplicate people; a missing Claude key parks the work with the reason shown. **Not verified:** the real Claude and Gemini calls (need your keys), so the "one FirstData file with Opus" canary is still open. Worth knowing: the 7B read "Zed Zulu" as an organization as well as a person on one auto-applied test note, so a small local model shouldn't be left on auto-apply for things you care about; Claude is the one to trust._

### Chunk 9 · Inbox and review screens (L)

- [x] Drop zone and folder picker (the Swift window already supports folders), paste notes ("Sort & review"), the
  queue with progress, filters and "Approve all ready", per-job review (match editing, relationships on/off,
  warnings), retry and discard, spreadsheet mapping view, "Needs you" chips via `JobStatus`.
- [x] Sidebar Inbox badge counts what needs the owner.

**Done when:** a small folder imports end to end through the UI (fake AI, then one real run).
**Depends on:** 8.

_Result: `Inbox.tsx` (a drop zone that also reads whole folders with their paths, file and folder pickers, an "add to your people automatically" choice, paste notes with an optional title and date, "Read by …" showing who does the extraction job, the queue with filters and counts, a "Paused" banner with the reason and **Resume**, and "Add everything that's ready" behind a confirmation), `InboxItem.tsx` (the review: warnings, the record's title, date, summary, key points, action items and tags; each person, organization or topic as Same as / New / Skip with the candidate list, a search for another record and a link to open it; each relationship on or off; Discard behind a confirmation; "Add to your people" disabled until every "Same as" has a record; applied, failed, skipped and discarded states; the original text), `drop.ts`, `inboxBits.tsx`. Both screens are loaded only when opened. The sidebar's Inbox badge counts items waiting for review plus failed ones. Spreadsheet mapping view: nothing to show until chunk 10 makes spreadsheets importable. **Verified in a browser** on a scratch copy of your data: dropping three files (two queued, one skipped as too short), the queue and its filters, opening an item that the local model had read from one of your real notes, adding it (it opened the new meeting and the badge went down), a parked item showing the Paused banner and reason, and no horizontal overflow at 390 px. **Not exercised by hand:** dragging a real folder from Finder (the folder reading is written against WebKit's directory entries and untested here), the native file and folder pickers, Discard, Retry and "Add everything that's ready", editing a match with the search box, keyboard-only use, and the Dusk theme on these screens. The "one real run" of the Done-when was the local Ollama reading from chunk 8, reviewed and added here; a run with Claude waits on your key._

### Chunk 10 · Importers: spreadsheets, LinkedIn, recorded meetings (M)

- [x] Spreadsheet import (invariant 8): AI column mapping with a synonym fallback, org-row detection, `met_with` →
  `knows` from teammates, relationship strength.
- [x] LinkedIn `Connections.csv` (official export only; idempotent; dated by "Connected On").
- [x] `POST /api/crm/ingest/meeting` (title, start, attendees with emails, notes, transcript): matches invitees by
  email, dedupes by `external_id` and content, attaches to an existing same-day meeting (`find_existing_meeting`).
- [x] The webhook endpoint (D15).

**Done when:** the five FirstData spreadsheets import into a scratch database with the old app's counts (using
recorded column mappings, since the AI step isn't deterministic); a replayed meeting does not duplicate.
**Depends on:** 8. **Milestone D** after 9 and 10.

_Result: `spreadsheets.py` (column mapping by the utility AI with a synonym fallback; a provider-wide failure parks the sheet instead of guessing; the importer, from DynaCRM, in the caller's transaction so a failure changes nothing; a recorded mapping can be replayed with `payload.mappings`), `linkedin.py`, and routes `POST /api/crm/ingest/linkedin`, `/meeting` (202, or 200 with the earlier item when it was seen before) and `/webhook` (payload shapes as before; added automatically only if the new setting `crm.webhook_auto_apply` is on). A spreadsheet is recorded as applied with the mapping used, shown on the item page ("Where each column went"). Webhook auth is the host's: D15 holds (only reachable from other machines in server mode, with the access token as `Authorization: Bearer …`); the old `X-Webhook-Token` header is gone. The inbox page has an "Other ways in" card (LinkedIn upload, the endpoints) and Settings has a switch for webhook auto-add. 14 new tests (`test_import.py`) and `scripts/parity-sheets.py`. **Parity, checked against the old code itself:** the old app's counts can't be reproduced from its recorded results alone, because the database it started from (what was already in it when the five sheets went in) is unknown. So `scripts/parity-sheets.py` runs DynaCRM's own importer (in its image, against a scratch Postgres database) and this one over the five recorded mappings from the same starting records in the same order, in two different setups: every per-sheet count is identical, and so are all 129 people and organizations and all 164 and 168 lines. `scripts/check` is green with 140 tests. **Verified in a browser** on a scratch copy of the data: a real spreadsheet imported, with its mapping shown; a LinkedIn file imported; the "Other ways in" card. **Not exercised by hand:** the LinkedIn file picker and a real Granola send (the endpoint is tested), the spreadsheet import with a real AI mapping (needs a key; the mapping used by the old app is what the parity run replays), and the Dusk theme on these screens._

### Chunk 11 · Mac polish (M)

- [x] Menu-bar template icon (`mac/Sources/AppHost/Mark.swift`, line art of the same mark, 18×18) and
  `mac/AppIcon.icns`.
- [x] Menu items, window size, Open at Login, data folder permissions.
- [x] Decide D3, D10, D11. Build with `scripts/build-app.sh --dmg`.
- [x] This Mac has the Command Line Tools only (no Xcode): don't use `@State`, `@Entry` or `#Preview` in Swift.
- [x] Behaviour checks: kill the server → it restarts (up to 3 times in 2 minutes) then explains; quit leaves no
  stray process; two copies of the app don't fight over the port.

**Done when:** the `.dmg` installs into `/Applications` on this Mac, the first-launch steps are written down, and
CI builds it on a version tag.
**Depends on:** 4 (earlier is fine).

_Result: decisions D3 = `com.thelodge.app`, D10 = ad-hoc, D11 = manual disk image (see the table). The menu bar icon is now the A-frame lodge with its door and the low sun (`Mark.swift`), and the app icon is the same mark (`mac/AppIcon.icns`, drawn by `scripts/make-icon.swift`). Menu: Open The Lodge, Inbox, Open at Login, Show Data Folder, Show Server Log, Quit (and Check for Updates, only if an update repo is set). The data folder is readable only by you (0700, database 0600), fixed in the host (`db.init`) so it also holds for a development run and a server install, with a test; it was world-readable before and your real folder was tightened when the new app first ran. `scripts/build-app.sh --dmg` makes `The Lodge-0.1.0-arm64.dmg` (112 MB, with its `.sha256`); I mounted it, checked the checksum, that it holds the app and an Applications link, and that the ad-hoc signature verifies (macOS's Gatekeeper rejects it, as expected, hence the first-launch steps in `INSTALL.md`). **I installed it into `/Applications` on this Mac** from that image and ran it on your real data (129 people, as before); the old copy in `dist-app` is the same build. `scripts/check-app.py` checks the built app on a spare port with its own data folder (13 checks, all pass): the server starts as the app's child; a killed server is started again, and after three crashes in two minutes the app stops trying (the menu then explains from the log; I haven't read that menu text on screen); quitting leaves no server, and force-killing the app doesn't either; a second copy shares the first one's server and closing it doesn't stop it. The release workflow (`.github/workflows/release.yml`, on a `v*` tag) parses and builds with the same script, but **I haven't run it on GitHub**: a tag push would, and the first run may need small fixes (the runner's Swift is older than this Mac's). Not done: reading the menu text on screen, a signed or notarized build, automatic updates._

### Chunk 12 · Capture automation: Granola and calendars (spike, then M)

- [ ] **Spike:** what Granola exposes to third-party apps: its MCP server (`https://mcp.granola.ai/mcp`, OAuth;
  tools `list_meetings`, `get_meetings`, `get_meeting_transcript`, `query_granola`) versus an API key. Until that is
  answered, a Claude Code session can pull meetings and POST them to the chunk 10 endpoint (works today).
- [ ] Sync as an idempotent job. The host has **no scheduler**; add a tiny recurring-job facility (or a startup
  thread in the module).
- [ ] Google Calendar through private iCal URLs (no OAuth): create meeting records with attendee emails ahead of
  time; transcripts later attach to the same meeting by time and attendees.

**Done when:** a new Granola meeting shows up in The Lodge without the owner doing anything, joined to its calendar event.
**Depends on:** 10.

**Result (2026-10-12).**
- **Spike answer:** Granola has an official public API (`https://public-api.granola.ai/v1`, docs.granola.ai) with
  personal API keys made in the Granola app (Settings, Connectors, API keys) and sent as a bearer token. It needs a
  Business or Enterprise plan, allows 5 requests a second, and returns the note's summary, its calendar event
  (scheduled start and invitee emails), attendees, and the transcript (a separate paged endpoint when too large). The
  MCP server (`mcp.granola.ai`) is OAuth through a browser sign-in, which doesn't suit a background sync, so it isn't
  used. Fallback if the owner's plan has no API access: the manual/Claude Code pull into `/ingest/meeting` still works.
- **Host:** `core/server/schedule.py` and `Module.recurring`: a kind of job queued every N seconds (0 = paused) on the
  ordinary job runner; finished rows are cleared so a 15-minute job leaves one row. Settings names ending `_secret` are
  write-only like keys and tokens. 3 tests.
- **Granola** (`granola.py`): every 15 minutes once a key is saved (and straight away when it's pasted), list notes
  from the last few days (the first run goes back `crm.granola_days`, 30), skip those already seen, fetch the rest, and
  send each through `create_meeting_job`, the same path as `/ingest/meeting`. Invitee emails match people; your own email
  on your profile marks which attendee is you. Auto-add is on by default (`crm.granola_auto_apply`) and still holds
  anything ambiguous or read by rules alone. Rate-limit retries, 401/403 recorded for Settings instead of raised.
- **Calendar** (`ics.py`, `calendar_sync.py`): secret iCal addresses (`crm.calendar_secret`, several allowed), hourly. A
  small RFC 5545 reader (time zones, repeats with exceptions and edits, declines, cancellations, skips all-day).
  Meetings are made from the last 7 and next 14 days only when you haven't declined, there are 2-20 invitees, and at
  least one is already in your people by email. Strangers on an invite are not made people (their emails are kept on the
  meeting). Cancelled or removed events are removed again unless something has since been written into them.
- **Joined:** a Granola note finds the calendar's meeting by time and shared people (the existing same-meeting match) and
  adds its summary, points and Granola id to it. Meetings still to come don't count as having met (a guard added to the
  connection scoring, which counted every dated meeting).
- **Tagged for removal (the owner's request):** everything a sync creates carries its origin in `source` (`granola`,
  `calendar`) on the meeting, the people and organizations it created, and the lines and notes. Not a tag: a tag would
  become a group on the network. Settings shows "Remove what came from Granola / Calendar" with counts first;
  removal deletes the meetings, the people it made that nothing else holds on to, its other lines and notes, marks its
  inbox items discarded so Granola doesn't bring them back, and leaves calendar meetings that now hold notes.
- **Verified:** 20 new tests (17 in `test_capture.py`, 3 for the scheduler) against a fake Granola and a fake calendar feed, including the join,
  the removal, a key Granola refuses, a busy Granola and the 413 transcript path. In a browser on a copy of the real
  data with a local iCal file: pasting an address synced it, the status line, and the removal dialog and removal.
  `scripts/check` is green with 174 tests.
- **Not verified:** a real Granola key (the API shapes come from its published docs; the paged-transcript response
  shape is a best reading); a real Google secret address (recurring events in particular); the sync inside the Mac app
  over a day; the Dusk theme beyond the screens I opened.

### Chunk 13 · Cutover and hardening (S–M)

- [ ] Nightly backup and restore (Settings), JSON export, an upgrade test (an old database file plus a newer
  migration), performance on synthetic 50,000 entities / 250,000 edges (the snapshot cache), keys-at-rest option
  (Keychain) if wanted.
- [ ] The owner uses The Lodge daily. Stop the Docker stack, archive `DynaCRM (OLD)`, keep the Postgres dump.

**Done when:** a week of daily use without opening the old app, and a restore from backup has been tried.
**Depends on:** everything. **Milestone E.**

**Result (2026-10-12): built; the daily-use week is the owner's.**
- **Backup and restore** (`core/server/backup.py`, Settings, Your data): SQLite online backup each day (skipped if one
  under 20 hours old exists, because the app restarts often), "Back up now", kept 14 daily / 20 manual / 5 "before a
  restore", in the data folder's `backups/` (0700 folder, 0600 files). Restore verifies the file (SQLite's check, and
  refuses one from a newer app), keeps a backup of what it replaces, copies over the live database, brings an older
  one up to date with the migrations (and puts the old state back if that fails), and publishes `core.restored` so the
  CRM drops its caches. The restore can itself be restored. **Tried on a copy of the real data:** backup (10.3 MB),
  five people deleted, restore, 129 people back, the lists serving.
- **JSON export** (`Module.export`, the CRM's `exporting.py`): people, organizations, meetings, documents, topics,
  relationships, notes and saved views as readable JSON in `exports/`, with no settings or keys. Real data: 381
  records, 839 lines, 589 notes, 3.5 MB. (Written to the data folder rather than downloaded, because the app window
  has no download handling.)
- **Upgrade test** (`test_upgrade.py`): a database made with only the first release's schema and holding data is
  brought to today's, nothing lost, and starting again changes nothing; backups from older schemas restore likewise.
- **Performance** (`scripts/perf.py`, synthetic 50,000 records and 250,000 lines, 129 MB): warm reads are 20-200 ms
  (people list 87, search 5, a person's page 41, Home 560, organizations 199); the first read after any write rebuilds
  the in-memory graph, which took about 6 s and now takes about 3.5 s; the network view 2 s; the graph overview 1.2 s;
  backup 3-5 s and export 10 s (background). Two fixes came out of it: the people list built a row for every person
  before choosing the page (966 ms warm, now 87), and Python's cycle collector was running all through the graph build
  (it is paused for the build). A real book is about 100 times smaller than this (the owner's is 381 records), where
  everything is a few milliseconds. The remaining cost is that any write throws the whole cache away; if a book ever
  gets this big, the next step is updating the snapshot in place instead.
- **Keychain: dropped (the owner, 2026-10-23).** The family apps are multi-platform, and a key a person enters in one family
  app (Trailmix) must already be there in the others, which `family.py` does with the shared `ai.*` settings. Earlier note: Keys sit in the 0600 database in the 0700 data folder, the same exposure as the old `.env`,
  and they are copied into every backup. Moving them to the Keychain from a Python server means either shelling out to
  `security` (the secret appears on a command line) or a Swift bridge, and the backups would then not carry the keys. It
  is a decision for the owner, not a default; it is a small chunk if wanted.
- **Cutover prepared:** the old Postgres holds 381 entities and 839 relationships, last changed 2026-09-26, exactly
  what was imported, so nothing is waiting to come across and the importer must not be run again (it would overwrite
  edits made in The Lodge). A final dump is saved at `~/Desktop/Temp/dynacrm-final-dump-20261012.sql.gz` with a README (moved there 2026-10-18; 0600, outside the repo;
  it includes the old app's settings table). The Postgres container is stopped.
- **Cut over (2026-10-18, the owner's go):** installed the current build (`aa02159`) with `scripts/install-app.sh`: checks, the
  13 app behaviour checks, a backup first, swap, and a data check ("9 tables, nothing missing"). It serves 128 people (9
  strong, 12 working, 58 light, 29 indirect, 20 not linked), 67 flagged for research, 8 backups. Docker is closed, so the
  old stack is stopped; nothing in the new app depends on it. Not yet set up in the new app: an AI key (extraction is on
  Claude, so imports wait until one is saved), Granola, a calendar address, Open at Login.
- **Closed 2026-10-23:** the owner is all in on the local app, so the week of daily use is no longer a gate. Archiving the
  `DynaCRM (OLD)` folder and removing the old Docker containers and volume are the owner's own cleanup (the dump is the way
  back). The one-off tools for that migration (`import-dynacrm.py`, the parity scripts) were removed from the repo on
  2026-10-23 so a new install carries nothing of it.
- **Tests:** 9 new (`test_backup.py` 8, `test_upgrade.py` 1); `scripts/check` is green with 183.

---

### Chunk 14 · Research flags: people who need deep research (M) — DONE

The owner's request (2026-10-12): when a person's profile has no base context, flag them so he can run **deep research** on
them in a deep-research tool and bring the result back in.

Proposed shape (change any of it):

- **What counts as "no base context":** no summary **and** no long-form research on them (a note from a document
  that's a profile, or anything over about 1,500 characters). On the real data that is about 70 of the 128 people,
  so the flag has to be easy to work through, not a wall: sort by how much the person matters (tier, meetings,
  connections), and let him snooze or dismiss one ("not worth researching").
- **Where it shows:** a "Needs research" chip on the person's profile, a filter and count on People, and a card on Home
  ("12 strong or working contacts have no research"), most important first.
- **The research brief:** one button on the profile, "Copy research brief", puts a ready-made prompt on the
  clipboard for whichever deep-research tool he uses (Claude, ChatGPT, Gemini, Perplexity): who they are as far as we
  know (name, title, organization, location, email domain, LinkedIn URL), where they came up in his meetings and
  documents, what he wants to learn (background, current role, organizations, who they know, why they matter to Cold
  Connect), and the output shape the importer reads best. Nothing is sent anywhere by the app; he pastes it himself.
- **Bringing it back:** a "Paste or add the research" button on the same profile opens the inbox with the person
  already chosen as the subject, so the existing `person_profile` path attaches the summary and facts to them, keeps
  the full text as a note, and the flag clears. A document dropped into the inbox that's about someone who's flagged
  clears the flag the same way.
- **Honest limits:** the app can't run deep research itself (those tools are in other apps), and it won't guess a
  profile from the open web. A person with only a first name can't be researched until they have a surname.

**Done when:** a person with nothing on file shows the flag; "Copy research brief" gives a prompt that names what we
know about them; pasting a research report back attaches it and clears the flag; the Home card lists the ones that
matter most.
**Depends on:** 8, 9 (the inbox and the `person_profile` path).

**Result (2026-10-12).** Built as proposed, with these particulars:
- **The flag** (`modules/crm/server/research.py`): a person other than you with no summary, no note of 1,500+
  characters, no document filed `about` them, and no earlier profile applied. A first name alone is held back
  (`name_needed`) because a search would find the wrong person. Snooze (30 days), "Not worth it" and "Bring it back"
  are stored on the person (`attributes.research`), so they survive edits and merges. On the owner's real data (a copy) 67
  of 128 people are flagged, 5 of them strong or working contacts, and 3 more wait on a surname.
- **Where it shows:** a card at the top of a person's Overview (Copy research brief · Add the research · Snooze · Not
  worth it); a "needs research" chip on People rows (a dot on phones) and a "Needs research N" filter; a Home section
  that lists the most important first and says how many close contacts have nothing.
- **The brief:** name, role, organization, location, email *domain* (never the address), LinkedIn, earlier
  organizations, tags, how you know them (meetings, documents, mutual contacts), who you are, six things to learn, the
  rules (public sources, links, no guessing, say how you told two people apart) and the output headings the importer
  reads best. One click copies it; if the webview refuses the copy it opens in a dialog with a Copy button.
- **Bringing it back:** the profile's "Add the research" takes pasted text or a file (.pdf .docx .md .txt) with the
  person attached as `subject_id`. The reader is told who it is about, the proposal is forced to a person profile with
  that person as the matched subject (never ambiguous), triage is skipped, and the item goes to review (not
  auto-applied). Applying it fills their empty summary and facts, keeps the whole report as a note, and records
  `research.status = done`, so even a short report clears the flag. Any other profile applied to a flagged person clears
  it the same way.
- **Verified:** 13 new tests (flag rules, snooze/dismiss/restore and expiry, filter and counts, Home ordering, brief
  contents and the missing email, first-name refusal, the AI and rules paths through to a cleared flag). In a browser
  on a copy of the real data: the Home section, People filter, profile card, brief, add-research dialog through to the
  review page, and the flag clearing after apply; People at 375 px. 154 tests pass.
- **Not verified:** the one-click copy inside the real Mac webview (the test browser refused it and showed the
  fallback dialog, which works); a real deep-research report read by Claude; a PDF export from a research tool.

### Chunk 15 · Find someone from Home; AI overviews and questions on profiles (M) — DONE

The owner's request (2026-10-13): a search on Home to bring up someone's profile quickly; a pre-written AI overview of each
person; and a quick chat to ask more about a person and their profile.

**Result (2026-10-13).**
- **Find someone** (`modules/crm/web/PersonFinder.tsx`): a large search box at the top of Home, ready to type into
  when Home opens (without scrolling past the picture), and "/" jumps back to it. It matches name, alias, role,
  organization, place and tags, names that start with what was typed first (`sort=match` on `/api/crm/people`), then
  the closest people. ↑ ↓ Return Escape, a role="combobox" listbox, and "All N matches" opens People filtered.
- **Overviews** (`modules/crm/server/profiles.py`, `crm_overviews`): written from what's on file (role, organizations,
  how you're connected, the profile summary, meetings with their summaries, notes newest first within a size budget,
  documents, their people). Never the email address. Written ahead of time by a sweep every 10 minutes, closest
  first, 4 a run on a local model and 25 on a cloud one, and again when the records change (a fingerprint of the text
  the model was given). Opening a profile with none, or a stale one, asks for it at once in a new **interactive** job
  lane in the host (`jobs.LANES`), so it never waits behind a batch. A failure shows with Try again and isn't retried
  on every refresh; an AI that is down parks the job until it's fixed. Redo writes it again.
- **Questions** (`crm_questions`): "Ask about <name>" under the overview, with four suggested questions. Each answer
  is worked out in the interactive lane from the same records plus the overview, the last six questions and today's
  date, and kept on the profile; Clear deletes them.
- **Which AI:** a third People job in Settings → AI, "Overviews and questions", default "Same as the app" (the local
  model unless a cloud one is chosen); there is no rules-only reading of it. "Write overviews ahead of time" turns
  the sweep off and shows how many people have one.
- **Also fixed:** the research brief failed (500) for anyone with people in common with you (`conn.mutual` holds ids).
- **Verified:** 14 new tests (what the overview is written from, once and again on change, redo, nothing on file, no
  AI, a failure not retried, a down AI parked, the sweep's order and limits, questions with follow-ups, a failed
  question retried, guards, delete cascade, the brief with mutual contacts, finder ranking). In a browser on a copy of
  the real data with the local qwen2.5:7b: the sweep wrote Erik Pruitt's overview within a minute of starting, it
  matched his records, and "What should I follow up on?" was answered in about 10 seconds; both themes. 197 tests pass.
- **Not verified:** overviews and answers from Claude or Gemini (no keys in the app).

### Chunk 16 · Profile pictures (M) — DONE

The owner asked (2026-10-13) for a picture of each person and whether LinkedIn can supply them. LinkedIn's API doesn't
hand out other people's photos, and scraping it breaks its terms, so the proposal is: (1) add a picture by hand on a
profile (drop, paste or choose a file; copying the photo from LinkedIn in the browser and pasting it works), shown
everywhere a person appears; (2) match photos from the Mac's Contacts app by email, phone and name (asks for
Contacts access once; nothing leaves the Mac); (3) optionally, Gravatar for people with an email address (a hash of
the address goes to Gravatar, so it's a setting, off by default).

**Result (2026-10-23).** The owner: build it, even if pictures have to be placed by hand.
- **By hand:** click the picture on any profile. Choose a file, drop one, or paste one (⌘V, or the Paste button). The
  page makes it a 256 px square JPEG first (about 4 KB), so the database holds a few KB per person and every backup
  carries them. Remove puts the initials back. LinkedIn photos work by copying one in the browser and pasting it.
- **Shown everywhere a person or organization appears** (lists, Home, finder, network side panel, profile cards,
  duplicates), by the record's id; nothing else needed to change.
- **Gravatar:** a setting that starts off (Settings → People: pictures). Only a SHA-256 of the email goes to
  gravatar.com, only for people with an email and no picture, from the profile ("Look up on Gravatar") or for everyone
  in the background. A person Gravatar has nothing for is skipped. (Lockdown, chunk 22d, will refuse it.)
- **Merging** gives the kept record the other's picture if it has none. Unmerging doesn't give it back.
- **Not built:** matching photos from the Mac's Contacts app. It needs a Swift bridge for the Contacts permission
  and can't be tried without a person at the Mac; the by-hand path covers the need for now.
- **Tests:** 6 (`test_pictures.py`: kept and served with a cache tag, only pictures accepted, deleted with the
  person, merge, Gravatar off until allowed and asked with a hash, the background run). Looked at in a browser on demo
  data: picture on a profile, the dialog, a resize of a 400×300 image to 4 KB.

### Chunk 17 · Shared Google Sheet (M) — DONE

The owner's request (2026-10-18): a human-readable copy of the CRM in a Google Sheet that anyone can see, correct and add
to, as a live parallel interface. A sync, not a backend, so the app stays quick; not everything belongs on it.
Decided with the owner: contact card and summary only (no ratings, notes, meetings or overviews); new rows go straight in;
connect through an Apps Script web app rather than a Google Cloud service account.

**Result (2026-10-18).**
- **The link** (`sheet_script.py`): a short Apps Script pasted into the spreadsheet (`@OnlyCurrentDoc`, so it can open
  only that spreadsheet) and deployed as a web app, Execute as Me, Who has access Anyone. Its URL is the setting
  `crm.sheet_secret`, kept like a key. The script is dumb on purpose: it adds missing tabs and headers (plain text
  columns, the Lodge ID column greyed and warning-protected), reads every row as shown, and writes what it's told.
  Each written cell names the value that was read there, and one changed since is left alone. `VERSION` makes the
  server ask for a fresh copy when the script changes.
- **The sync** (`sheet_sync.py`, job `crm/sheet_sync` in the cloud lane): every 2 minutes, or 30 seconds after a change
  in the app. People tab (Name, Organization, Title, Email, Phone, LinkedIn, Location, Tags, Summary) and
  Organizations tab (Name, Website, Location, Email, Tags, Summary), each with "Add a note" and "Lodge ID". You and
  anyone tagged `private` stay off. Three-way, per cell, against `crm_sheet_rows` (what both sides last agreed): a
  change on one side wins; a change on both keeps The Lodge's and notes the sheet's on the record. Organization edits
  end the job the sheet showed and add the new one. New rows match by email, LinkedIn or exact name, or become new
  records (source "sheet"); a second row for someone is folded in and removed; a copied row renamed is someone new.
  Deleted rows come back; deleted or private records leave. A deleted column comes back without emptying anything.
  More than 10 values (or a fifth of the rows) emptied or replaced on a tab at once hold that tab until the owner chooses
  "Put The Lodge's back" or "Copy them in" in Settings (or undoes it on the sheet).
- **Settings → People: shared sheet**: what goes on it, the setup steps with Copy and Show the script, the link,
  the last sync with an Open the sheet link, the held-tab choice, Test it and Sync now.
- **Verified:** 23 new tests that run the real script under Node against a stand-in for Google Sheets
  (`tests/sheet_harness.mjs`: strict about ranges, turns numbers in non-text cells into numbers, answers through
  Google's redirect), including a cell typed over between the read and the write. A dry run on a copy of the real data:
  128 people and 175 organizations on the first sync (one 80 KB write), and a second sync is a single read that
  changes nothing on either side. The Settings section in a browser, both states and 375 px. 225 tests pass.
- **Not verified:** a real Google Sheet and Apps Script deployment. The script was written against Apps Script's
  documented API but has only run against the stand-in, so the first real setup is the check. Edits only arrive while
  the Mac is awake and The Lodge is running.

### Chunk 18 · Bulk research import, Gemini-shaped briefs, flagged duplicates (M–L) — DONE

The owner's request (2026-10-18): bulk-import research briefs, or a messy folder of research and notes on people; make the
brief and its copy as good as they can be for Gemini Deep Research, which he'll mostly use. And, like Trailmix's
duplicate meetings: flag likely duplicate people automatically, keep everything, and leave the merge to him, because
records disappearing would change too many downstream ties.

**Result (2026-10-19).**
- **Google formats** (`documents.py`): a `.zip` (a Drive folder download, a Takeout export) is unpacked into its files,
  each keeping its folder path (`__MACOSX` and `._` files skipped; 2,000 files, 300 MB unpacked, 20 MB a file). `.html`
  (a Docs "Web page" export), `.rtf` and `.odt` are read. Drive for desktop's `.gdoc`/`.gsheet`/… shortcuts hold no
  text, so they're skipped with how to download the real file.
- **The brief** (`research.py`), shaped for Gemini Deep Research: an exact title ("‹Name› — research profile", so the
  exported Doc and its file are named after the person), a `Lodge ref: ‹first 10 of the id›` line to keep, an
  "Identity confidence: High/Medium/Low" line, a 2–3 sentence summary, Key facts, fixed sections, citations left to
  the tool, 1,500–2,500 words, today's date. Meeting titles and dates only (no meeting summaries leave the app).
- **Reports that file themselves** (`ingest.py`): a report or pasted text carrying a ref that matches exactly one
  person becomes research on them (`payload.subject_by = "ref"`), skips triage and can be applied automatically.
  "Identity confidence: Medium/Low" holds it for review with a warning. In a profile, new people and organizations
  the report only mentions (no relationship to its subject) are set to Skip, so a folder of reports doesn't fill the
  book with strangers. A profile's summary replaces the subject's existing one, and the old one is kept as a note.
- **Duplicates** (`duplicates.py`, `crm_duplicates`, job `crm/duplicates_check` every 5 minutes when the book changed,
  or "Look again"): pairs of people by email, LinkedIn, same name or alias, nickname or short form with the same
  surname, a one-letter slip (two in long words; first names of 5+ letters only), or a first name alone that shares a
  meeting or employer with the full name; a shared employer adds weight. Organizations by website, name without
  Inc/LLC/…, alias or near spelling. Compared within blocks (surname, first name and nicknames, email, …), not all
  pairs. **Nothing merges by itself.** "Not the same" sticks.
- **Merges keep everything** (`store.merge_entities`, `crm_merges`): the folded-in record's row, every edge and what
  happened to it, the notes, questions and overview that moved, and the kept record before and after. **Undo merge**
  (`store.unmerge`) brings the record back under its own id with its edges, notes and questions, takes off only what
  the merge added and is unchanged since, and marks the pair "not the same". Links to a merged record (`describe`,
  other modules' refs) lead to the record it's part of; its old page says where it went. Merged records are in the JSON
  export. The profile's existing Merge button gets all of this too.
- **Screens:** Possible duplicates page (`#/crm/duplicates`) and a Home section; on a profile, "Might be the same
  person as" with Merge… (you choose which record to keep) and Not the same, and "‹Name› was merged into this record ·
  Undo merge". Import and research dialogs name the new formats and Gemini's Export to Docs → Download.
- **Verified:** 12 new tests (formats and zips, ref filing and namesakes, identity hold, held-back mentions, summary
  kept as a note, duplicate rules, not-the-same, merge and undo end to end, you as the merged record); 235 pass. In a
  browser on a scratch database: Home section, duplicates page, merge from a profile, the old record's page, undo.
- **Not verified:** a real Gemini Deep Research report through Export to Docs and back. Whether Gemini keeps the
  `Lodge ref` line and the identity line is the thing to check first; without them, matching falls back to names.

### Chunk 19 · The Lodge runs Gemini research itself — DONE (built after the scoping below)

The owner (2026-10-18): interested in The Lodge running deep research on flagged people itself through the Gemini API,
but worried about cost even with batch pricing. **Hold off building until there are firm estimates.**

**Prices (Google's pricing page, read 2026-10-19; increases are scheduled from December 2026 / January 2027).**
Per 1M tokens, standard → batch/flex: Gemini 3.8 Flash $0.75 in / $3.75 out → $0.375 / $1.875; Gemini 3.1 Pro
(preview) $2 / $12 → $1 / $6; Gemini 4 Argon $2 / $10 → $1 / $5. Thinking tokens bill as output. **Google Search
grounding** on Gemini 3 and newer: 5,000 searches a month free (shared across models), then **$14 per 1,000
searches**, billed per search the model runs, **with no batch or flex discount**. Retrieved page text from search
isn't billed as input.

**A. Google's Deep Research agent** (`deep-research-preview-04-2026`, Interactions API, background only, preview).
Google's own estimate: **~$1–3 a task** (~80 searches, ~250k input tokens of which 50–70% cached, ~60k output).
Deep Research Max: ~$3–7. The 80 searches are ~$1.12 of that once past the free 5,000, so 62 people a month fit
in the free searches. Output format is steered only by the prompt (the brief already does this); it can be held to
Google Search alone, given URLs to read, or asked for a plan to approve first. No batch discount documented.
- The 67 flagged today: **~$65–200** once (Max: ~$200–470).

**B. Our own pipeline**, sized for one person rather than a market report (our estimate, to confirm by trial):
Flash with search grounding runs ~6 focused questions seeded by the brief (who they are, roles and dates, boards and
investments, public work, people around them, recent news), ~2 searches each; Pro checks the findings once and sends
~3 follow-ups; Pro writes the report in the brief's shape.
| Step | Tokens (in / out incl. thinking) | Searches | Standard | Flex |
| --- | --- | --- | --- | --- |
| 9 Flash search calls | ~14k / ~32k | ~18 | ~$0.13 | ~$0.07 |
| Pro check | ~15k / ~4k | 0 | ~$0.08 | ~$0.04 |
| Pro report | ~20k / ~8k | 0 | ~$0.14 | ~$0.07 |
| **Per person** | | ~18 | **~$0.35** + searches past the free 5,000 (~$0.25) | **~$0.18** + searches |
- Per person **~$0.20–0.60**; the 67 flagged **~$15–40** once. ~270 people a month fit in the free searches.
- Cheaper still with Flash writing the report (~$0.10 a person), at some cost in judgment.

**The trade:** A is Google's tuned research loop (deeper, ~80 searches a person, more likely to find obscure people)
at roughly 5× the cost and less control; B is cheap, predictable and fits The Lodge's job queue, budget and brief
exactly, but we own its quality. Either way the result is a report in the brief's shape, carrying its ref, that lands
in the Inbox like any other.

**Before building (the firm numbers):** a trial on 3 people the owner picks, both ways, with real token and search counts
read back from the API's usage data. Expected cost of the trial: under $10. Needs the owner's Gemini key on a paid tier,
and his OK to spend it.

**If built, it would have:** a monthly budget and a per-person cap set in Settings (the job stops before a call that
would cross either), a "Research these" action on flagged people that shows the estimate before it starts, a per-run
cost on each report, and Gemini named as where the research came from.

Sources: [pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Deep Research agent](https://ai.google.dev/gemini-api/docs/deep-research),
[search grounding](https://ai.google.dev/gemini-api/docs/google-search).

**Built (2026-10-19)**, after the owner asked for a trial with Flash-Lite and Batch plus an option for better models:
- **`gemini_research.py`** (job `crm/research_advance`, every minute while a run is under way): six focused questions
  with Google Search grounding, seeded by the brief's "who I mean" (never your tags, never an email address), then a
  report written to the brief's shape with its ref and identity line. It goes to the Inbox as research on that
  person and waits for review; the footer says which models, how many searches and what it cost.
- **Levels:** Quick (Gemini 3.5 Flash-Lite asks and writes), Better (Gemini 3.8 Flash), Best (Flash asks, Gemini 4
  Argon checks for gaps and contradictions, up to 3 follow-ups are searched, Argon writes). Any level can go through
  Google's Batch API: one batch per stage per model, shared by everyone started together.
- **Money:** cost from Google's own usage and search counts (`crm_research_runs`); a monthly budget (default $5)
  that start-up checks against and that stops a run before its next stage once spent; estimates in the dialog.
- **Screens:** "Research with Gemini" on a flagged profile and for the Home list (choose the level and Batch, see the
  per-person and total estimate and the budget left); the run's progress on the profile with Cancel / Try again;
  after a run, "Research more deeply"; Settings → People: research with Gemini (usual level, Batch, budget, recent
  runs). Prices are in code (`PRICES`, as of 2026-10-19; Google raises several from December 2026).

**Trial (2026-10-19)**, on a copy of the real data with the sheet, Granola, calendar and Claude switched off, the top
three on Needs research, using the Gemini key from Trailmix:

| Person | Level | Batch | Searches | Tokens in / out | Cost | Time | Report |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Billy Kemp | Quick | yes | 4 / 4 | ~2.6k / ~1.6k | $0.06 | ~6 min | ~300–400 words, thin |
| Jack Marlow | Quick | yes | 10 / 8 | ~3.4k / ~2.9k | $0.12–0.14 | ~6 min | ~650 words; named the namesakes |
| Anders Stone | Quick | yes | 1 / 3 | ~2.4k / ~0.9k | $0.02–0.04 | ~6 min | ~350 words, one source |
| Anders Stone | Better | no | 19 | ~7k / ~14k | $0.32 | 3 min | ~1,300 words, 34 links |
| Anders Stone | Best | no | 23 | ~13k / ~16k | $0.43 | 4 min | ~1,600 words, 32 links |
| Billy Kemp | Better | yes | 16 | ~5.6k / ~10.6k | $0.25 | ~6 min | ~800 words, 28 links |

(Two Quick rounds: the second after telling it to always search.) About $1.45 in all, before Google's free 5,000
searches a month, which this key may well cover.
- **Flash-Lite mostly doesn't search.** It answers most questions "Nothing found." without running a search, even
  when told to always search; that, not Batch, is why Quick is so cheap, and its reports are thin. The cheapest
  level is cheap because it does little.
- **Better is the step change.** Same person: a PhD and its dates, national-lab work, a company and its patents, a
  startup board seat, current teaching, and a sharp identity line (LinkedIn handle = university email handle).
- **Best adds judgment more than facts:** it noticed the CRM's "Chemical Angel Investor" title isn't supported in
  public records and searched for it. Its follow-ups exposed a bug (answers filed under the wrong follow-up when
  there were several), fixed with a test.
- **Searches are most of the cost** ($14 per 1,000, no Batch discount). Batch halves only the tokens: Better through
  Batch would have been ~$0.29 instead of $0.32, Best ~$0.38 instead of $0.43; it's slower (~5–6 minutes a round).
- **The 67 flagged people**, roughly: Quick ~$3–5, Better ~$20, Best ~$29, less whatever the free searches cover.
- Reports and each question's notes are in `build/research-trial/` (not in git). Nothing from the trial is in the
  real data: the reports carry their refs, so dropping them in the Inbox files them on the right people.

- **Better through Batch** (Billy Kemp, after the default changed): every question searched (16 searches), the
  studio's website, his business partner, his music project; $0.25, of which Gemini's reading and writing was ~2¢.
  For the 67 flagged, about **$17**, less what the free searches cover.

**Decided (2026-10-19):** the owner chose **Better through Batch** as the usual level (`crm.research_level = better`,
`crm.research_batch = true`); Quick and Best stay as choices in the dialog. **Open:** Gemini 4 Argon and 3.8 Flash were offered
to this key; another key might not have them, and the error says which model. Not tried: the Google Deep Research
agent (~$1–3 a person, by Google's estimate) as a fourth level.

### Chunk 20 · Network presets: focused questions, and lists the AI writes (M) — DONE

The owner (2026-10-21): the Network "still isn't doing what I need it to do". Switching groups on shows clusters, but it
doesn't answer the questions he brings to it. He picked six presets from a shortlist (he left out "strong ties gone
quiet"), and for the AI chose **rules plus picks**: a rule the app matches against the book, plus people the AI finds
in summaries, each with a reason.

- **`presets.py`**: each preset is a list of people with the reasons beside every name, worked out fresh from the
  book each time it runs (nothing is written to the graph). Built in:
  - **Who you know at…** an organization (staff, former staff, advisors, investors, anyone linked), a topic or a tag;
    the people you know best first.
  - **Who could introduce you to…** a person (people you know who know them, met them or work alongside them, ranked
    by your tie times theirs) or an organization (people you know there, then people you know who know someone there).
  - **Investors and advisors**: tags (investor, advisor, vc, angel…), invested-in and advises ties, and titles.
  - **Everyone from an event**: a meeting, meetings with the same name, and anyone tagged with its name
    (Northwest Innovation Showcase finds 22, BVC 18).
  - **In two groups at once**: the people who bridge two groups.
  - **Follow-ups waiting**: prospects, leads, thank-you notes, soft contacts and "Met at event", the ones you haven't
    met or rated first (strong ties left out).
  - **A rule**: tags, topics, organizations, events, words in titles or summaries, plus hand-picked people with reasons.
- **The AI writes rules** (job `crm/write_presets`, the "profiles" AI job, interactive lane): from a request ("everyone
  who could help with cold-chain funding") or, with none, 4–6 suggestions that don't repeat the built-in ones. It's
  given the book compactly (tags, topics, organizations, meetings with ids; each person with tier, role, tags, groups
  and a cut of their summary; about 36k characters for the real data). Ids it makes up are dropped, and an idea that
  finds nobody is left out. The last 6 asks are kept.
- **Tables** (migration step 8): `crm_presets` (saved: name, about, spec, source) and `crm_preset_asks`. Saved presets are
  in the export. API under `/api/crm/network/presets` (run, choices, saved, asks).
- **Screen:** an "Ask the network" row on the Network page: the six presets (the ones that need something open a
  small picker), "Ask for a list…" (the AI panel: write a request or "Suggest some"; each idea shows how many it finds
  and a few names, with Show and Save), and Saved presets. A preset's answer is a side panel (people, tier, reasons;
  Save preset, Pick everyone to tag them, Delete for a saved one) and is drawn on the canvas as one more group, with
  its own outline (long and short dashes) so everyone else fades. The List view shows the same people.
- 17 new tests (`test_presets.py`); `scripts/check` green with 261 tests.

**Verified in a browser on a copy of the real data:** Who could introduce you to Mercy Corps (Lena Lowell there, then
Elijah and Isaiah from the outreach call), Everyone from BVC (18), the canvas drawing a preset as a group, the AI
panel's error when no AI is ready ("Add an API key for Google Gemini in Settings"), and a sample AI answer (inserted
by hand, 23 people) shown and drawn. **Not verified:** a real AI writing a list. The copy has no Gemini key, and the
profiles job uses Gemini for the owner. The first "Suggest some" in the installed app is the check. Known rough edges: the
canvas legend covers part of a narrow canvas, and a React warning about state set during render comes from the graph
library's hover handling (it was there before this chunk).

### Chunk 21 · Lake and lantern: a colorblind-safe palette for The Lodge (S–M) — DONE

The owner (2026-10-21) asked for a palette that holds for red-green colorblind eyes (protan/deutan type: red, green and brown run together); the old colors didn't, and each family app should have its own palette while sharing the design and UX. The owner approved the
proposal from a comparison page (current against proposed, in Day and Dusk, as drawn and simulated for protan and
deutan eyes), with the lake-blue mark.

- **The audit.** Simulated with Machado 2009 at full strength and measured in CIEDE2000, the old palette's closest
  meanings were spruce (main color, done) against lingonberry (Them): 10.0 apart in deutan vision by day and 5.9 at
  dusk. Every tinted chip background was within 2–4 of the others, so "Added", "Reading", "Them" and neutral chips
  looked the same: the flatness he saw.
- **The palette** (`identity/tokens.css`, values and reasons in `identity/DESIGN.md`): lake blue for the main color,
  ember for errors, lantern yellow for "needs you", glacier (a lighter blue) for "working on it" and You, and cedar
  for Them. Every meaning sits on the blue-to-yellow axis or a step of lightness. Closest pair of dots now 19.6
  (deutan, day) and 12.6 (deutan, dusk); chips at least 6.2 at dusk. White on lake 8.2:1, white on ember 4.2:1 (up
  from 3.6), glacier 3.2:1 on the page. Token names stay the family's, so no component changed, and nothing in the
  family's shared code needed a hook: `identity/tokens.css` already holds each app's values.
- **The mark** is on a lake tile (`#3B72B8 → #1D4F8C`) in `Logo`, the favicon and the app icon (`make-icon.swift`
  run again). The menu bar icon is a template image, so it's unchanged.
- The family design guide the owner started (`~/Desktop/Lodge Family Design Guide`, `01-ui-and-ux.md` §2 and the README)
  says the project app should **reuse The Lodge's palette exactly** and set itself apart only by mark, scene and
  motif. That contradicts the owner's new direction (each app its own palette, same roles and kit). The guide isn't
  changed here; it needs updating before the project app is built.
- The simulation script, the palettes tried and the comparison page are in `build/palette/` (not in git);
  the page is also at https://claude.ai/artifact/44RUgarKdyKXYt7aWKrFuX.

**Verified in a browser on a copy of the real data**, Day and Dusk: Home (tier bars, section wells, links), the
Inbox, the network canvas with a group and a preset switched on (fills, rings, outlines, the preset panel), and the new
icon. `scripts/check` green. **Not checked by eye:** every status chip tone on a live screen (the comparison page
draws them from the same values), and the Scene artwork, whose pines and lake keep their own colors.

### Chunk 22 · On this Mac: a local-only path, recommended from the Mac's specs (L) — BUILT (family commit c6f4648)

The owner (2026-10-23): why isn't there a local-only version? Every family app could work that way. Give people the
choice, accept that some features (Gemini research) need a cloud provider, and have the app read the Mac's specs and
recommend a path, the way Trailmix's setup does.

**Where things stand.** The Lodge can already run locally: every AI job can be Ollama or "rules" (no AI), the
app-wide default provider is Ollama, local jobs run one at a time, long documents are trimmed to fit a local
context window, and network lists send a local model a smaller cut of the book. What's missing is the path *into*
that:
- `crm.extraction_provider` defaults to Claude and `crm.utility_provider` to Gemini (D9), so a new install with no
  keys can't read a note.
- Nothing reads the Mac's memory, chip or disk, and nothing installs Ollama or downloads a model for you.
- The job runner has a "waiting for memory" state, but nothing measures memory.
- There's no Lockdown. TRAILMIX.md makes it family rule 9 and notes the family host doesn't have it yet.

Trailmix has all four (`backend/resources.py`, `ollama_setup.py`, `settings.locked()`, `frontend/…/Welcome.tsx`), so
this is mostly porting them into the family host, then teaching The Lodge's CRM module to use them.

**Where it's built.** Parts a to e change the shared code in `~/Code/TrailmixFamily` (`core/`, `mac/`), which every
app pins (`family.lock`) and `scripts/check` compares. Each part is committed there first and then taken into The
Lodge with `scripts/sync-family`. Part f is The Lodge's own module. Traverse picks the family parts up when it next
syncs. One catch: each app owns its own `requirements.txt`, so the new `psutil` dependency is added to The Lodge's
(and Traverse's) by hand.

This Mac, for reference: Apple M4, 16 GB, about 20 GB of disk free, Ollama with `qwen2.5:3b` and `qwen2.5:7b`.

#### 22a · Spike: how good is a local model at The Lodge's jobs? (S)

Before choosing thresholds, measure. Run each AI job against the same inputs with `qwen2.5:3b`, `qwen2.5:7b`, a
~14B model and Claude, on a copy of the data. The inputs are a dozen real notes and meeting transcripts of
different lengths, a spreadsheet to map, and five overviews and five questions.
- **Extraction:** people, organizations, relationships and facts found, compared with Claude's as the reference.
  Missed, wrong and made-up are counted separately.
- **Utility:** triage verdicts and column mappings against the right answer.
- **Overviews and questions:** read side by side.
- **Speed and memory:** seconds per document, and peak memory against what's free.

**Done when:** a table in this chunk shows each job × model, and says which model size each job needs before it
counts as "good" and which only as "basic". That decides 22e's recommendations and 22f's basic mode.

_Result (2026-10-23, on this Mac with its everyday apps open). **Done, with two changes of method:** Claude
couldn't be run fresh, because the Claude key in the family's shared settings is 24 characters long and Claude
rejects it. So reading notes is scored against Claude Opus's readings stored with each document at the September
import, and sorting against Gemini Flash, which sorts your files today. The ~14B model wasn't run: it's a 9 GB
download onto a disk with 20 GB free, and on this 16 GB Mac, where 1–3 GB stays free, it would only measure
swapping. Scripts, raw outputs and the full side-by-side report are in `build/local-models/` (not in git: real data).
Every outward sync was switched off in the copy first._

**Reading notes and documents** (12 documents, 325 to 119,000 characters):

| Reader | People & orgs found | Relationships found | Facts | Action items | Wrong links¹ | Stuck at 30 min | Usual time per doc |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Opus (reference) | 119 | 100% | 140 | 83 | – | – | – |
| Gemini Flash | 85% | 59% | 73 | 64 | 0 | 0 of 12 | 25 s |
| `qwen2.5:7b` | 61%² | 14% | **0** | 41 | 4 | 2 of 12 | 2½ min (6 min on the longest) |
| `qwen2.5:3b` | 37%² | 15% | 1 | 0 | 1 | 7 of 12 | 20 s when it finishes |
| Rules (no AI) | 57% | 1% | 0 | 6 | 0 | – | instant |

¹ Names taken from the "already in your book" list the reader is shown, though this document never mentions them
(OPHIX, "Defence Materials Expo"). No reader made up a name from nothing; "Gregory Herbert" is a
fix of the note's own "Gregory Herbet". ² Of the documents it finished.

**The other jobs:**

| Job | Gemini Flash | `qwen2.5:7b` | `qwen2.5:3b` | Rules |
| --- | --- | --- | --- | --- |
| Sorting files (same verdict as Gemini) | reference | 92% | 83% | 92% |
| Spreadsheet columns (against the mappings you accepted, 47 columns) | 98% | 83% | 0%³ | 91% |
| Overviews (5 people) | good, ~150 words, reads 4× more of the record | good shape, mostly right; twice says how you know someone you haven't met | drops the opening, thinner | – |
| Questions (5) | right, including "no conversations on file" | good on follow-ups; once invents "your last conversation" | wordier, less exact | – |

³ It renamed the headers ("Name" → "name"), which the app treats as a wrong answer and maps by rules instead.

**Memory:** with this Mac's usual apps open, 1.0–2.7 GB stayed free. The 7B model took 4.7 GB, and 6.0 GB on long
documents (a 32k context), and macOS reported critical memory pressure during the long ones.

**What it means:**
- **No local model here reads notes well enough to be the default.** The 7B finds about as many people as the rules
  do, misses most relationships and never records facts. Reading notes is the one job where the cloud is clearly
  better, so on a 16 GB Mac "Mixed" is the recommendation, and "On this Mac" is offered as basic.
- **Basic mode (22f)** = rules for the people, and the local model for the summary and action items, with
  everything going to the Inbox for review.
- **Sorting and spreadsheet columns** don't need a local model at all: rules match the 7B (92%) or beat it (91%
  against 83%). On the local path they run as rules.
- **Overviews and questions** are fine on the 7B, and that's the job "On this Mac" can honestly offer. The prompt
  should say plainly when the records show no meeting, since the 7B filled that gap twice.
- **A local model sometimes never stops writing.** 9 of 48 local readings ran into the 30-minute limit. Run
  again with output capped at 4,096 tokens, the same two documents finished in 29 s and 3 min, far below the cap.
  So 22b also caps Ollama's output (`num_predict`) and shortens the timeout. Today one stuck reading holds up a
  whole batch for 30 minutes.
- **The 3B model is not worth recommending** for anything but overviews on Macs under 12 GB.
- **14B on 32 GB Macs is still unmeasured.** Until someone measures it on such a Mac, 22e recommends Mixed there
  too, with "On this Mac" one click away.

**Found along the way** (not part of this chunk):
- The shared Claude key is rejected, so the installed app can't read notes until it's entered again in
  Settings → AI.
- An empty `ai.gemini_model` setting (yours is `""`) makes every Gemini call a 404 instead of using the default
  model. Sorting, column mapping and overviews in the installed app fail because of it, and no overview has been
  written since 19 October. The fix belongs in the family's `ai.model_for`: an empty model means the default.

#### 22b · Family: what this Mac can do, and the memory gate (M)

- **`core/server/resources.py`**, ported from Trailmix:
  - `snapshot()`: memory total and free, swap, memory pressure, disk free and chip.
  - `check(required_gb, what)`: returns `None` to go ahead, or a plain reason to wait. It waits only when the model
    can't fit at all, the disk is too full to swap, or macOS reports critical memory pressure.
  - `device_advice()`: the same shape as Trailmix's (`verdict` local | mixed | cloud, `chip`, `ram_gb`,
    `disk_free_gb`, `notes`), so a shared Settings can show either app's.
- **The gate in `ai`:** before an Ollama call, the model's size (from Ollama's model list) goes through
  `resources.check`. If it says wait, `ai` raises a new `AIError` kind, "waiting for memory". Jobs park it as
  `waiting` with that reason, and a schedule tick puts it back in the queue when there's room. "Proceed anyway"
  forces it, as in Trailmix. Interactive asks (an overview someone is looking at) show the reason and the button
  instead of hanging.
- **Cap a local model's output** (from 22a): `num_predict` on every Ollama call (the 4,096-token answer budget
  `ai_adapters` already sizes the context with), and a timeout matched to it instead of 30 minutes, so a model
  that never stops writing costs a minute or two, not half an hour.
- `GET /api/system` returns the snapshot and the advice, for setup and Settings.
- **Tests:** fake `psutil` numbers for each verdict and each reason to wait, and a job that waits, then resumes by
  itself.

**Done when:** a local job on a Mac short of memory says why it's waiting and starts by itself once memory frees.

#### 22c · Family: Ollama from inside the app (M)

- **`core/server/ollama_setup.py`**, ported from Trailmix:
  - Is Ollama installed, running, and which models does it have.
  - Install the official Mac app. It's downloaded from ollama.com and accepted only if it carries Ollama's Developer
    ID signature (team `3MU9H2V9Y9`).
  - Start it, and pull a model with progress the page can show.
- **`recommended(job_weight)`** picks the model size from 22a's table and this Mac's memory. Trailmix's rule is the
  starting point: 7B from 16 GB, 3B below that, and from about 32 GB a ~14B for the heavy jobs if 22a shows it pays.
  `preferred_ollama_model` keeps choosing among what's installed.
- **The web component** (`core/web/components/OllamaSetup.tsx`) is shared by the setup screen and Settings → AI.
  It shows Install, then Download model (with size and progress), then Ready.

**Done when:** on a Mac without Ollama, the app installs it and downloads the recommended model without a terminal,
and a Test in Settings → AI passes.

#### 22d · Family: Lockdown (M)

Same name and meaning as Trailmix (`lockdown`, TRAILMIX.md rule 9): nothing leaves this computer.
- **`settings.locked()` and one gate in `ai.configured()`:** a provider that doesn't run on this computer is "not
  ready" with the reason "Lockdown mode is on (Settings → Privacy)". That covers every module's AI at once,
  including an Ollama on another machine and the cloud model lists.
- **A helper for modules** (`lockdown.blocked(what) -> str | None`) that every outward feature checks before it
  runs, and that its Settings section shows.
- **The Mac app:** the updater makes no automatic checks while the server reports Lockdown (`/api/app` carries it).
  "Check now" still works, because you asked for it. Ollama installs and model downloads are refused, with "Turn off
  Lockdown to download it."
- **Settings → Privacy** gets the switch, with a plain list of what it turns off.
- **Tests (like Trailmix's `tests/test_lockdown.py`):** with Lockdown on, every network call to a host other than
  this computer fails the test. Every outward path then runs: AI, model lists, Ollama install and pull, and each
  module's sync jobs.

**Done when:** with Lockdown on, the app works for everything local, and the test proves nothing else goes out.

#### 22e · Family: a guided first run that recommends a path (M–L)

The family has no setup screen yet. This adds one, in the shape of Trailmix's Welcome: one question per screen, all
skippable, and all in Settings later.
1. **Hello.**
2. **"Where should AI run?"** The Mac's line comes first ("Apple M4 · 16 GB memory · 20 GB free"), then three
   choices with the one that suits this Mac marked Recommended:
   - **On this Mac:** private and free. Shows OllamaSetup.
   - **Mixed:** most jobs here, and the heavy ones with a cloud AI and your key.
   - **A cloud AI:** best results, and text you add is sent to the provider you pick.

   With too little memory or disk, the local choice shows `device_advice` notes saying why.
3. **Privacy:** Lockdown, on or off. It comes after step 2 so downloads happen first.
4. **One step from each module, if it wants one.** `ModuleWeb.setupStep`, the same pattern as the registry's other
   hooks. The Lodge's is "Bring your people in".
5. **Done.**
- **Modules say how heavy their AI jobs are**, so the host can place them without knowing what they do. A new
  `ai_jobs` field on `Module` gives each job a label and a weight (light | heavy). "Mixed" puts heavy jobs on the
  cloud provider and light ones on Ollama. "On this Mac" puts everything on Ollama. With a small model, heavy jobs
  get the "basic" rule from 22a.
- **Existing installs don't get the whole Welcome.** They see a single card in Settings → AI ("You can now run
  everything on this Mac") that opens step 2.

**Done when:** a fresh data folder walks through setup on this Mac, and each of the three paths leaves every job
either ready or saying plainly what it needs.

#### 22f · The Lodge: local by default, and honest about what needs the cloud (M)

- **Defaults.** `crm.extraction_provider` and `crm.utility_provider` change to `auto`, so a new install follows the
  path setup chose. The jobs declare their weights: extraction heavy; utility and profiles light.
- **Keep what people have (a migration step).** A setting nobody changed follows its default (`settings.get_all`),
  so changing the defaults would quietly move the owner's install off Claude and Gemini. On upgrade, if a job's setting
  was never stored and that provider has a key, store the old default. The owner's install keeps Claude for reading notes
  and Gemini for sorting.
- **Basic and private.** If 22a shows a small model can't be trusted to read notes into the graph, extraction on
  that model runs as "rules" plus the model's people list, and everything goes to the Inbox for review. A plain note
  says a bigger model or a cloud AI reads more.
- **Long documents on a local model.** Today they're cut at about 80,000 characters. If 22a shows it's needed, read
  them in parts instead and merge the people found (Trailmix summarizes long meetings in parts first).
- **Lockdown in the CRM:**
  - Gemini research, Granola, calendar sync and the shared Sheet each stop. Their scheduled ticks enqueue nothing,
    and their Settings sections say "Off while Lockdown is on". "Copy research brief" stays, since you take it
    elsewhere yourself.
  - LinkedIn, spreadsheet and document imports, the network, presets and backups are all local, so they're
    unchanged.
- **What needs the cloud, said once:** a short list in Settings → AI and on the download page, showing which features
  work on this Mac, which need a key, and which need Lockdown off.
- **Docs:** README Features and Install, INSTALL.md, the download page ("Runs on your Mac, or with the AI you
  choose"), and TRAILMIX.md's table where Lockdown moves from "no" to "yes".
- **Ship it as a beta** (0.4.0) through the usual release path.

**Done when:** on a copy of the data, The Lodge on this Mac reads a note, maps a spreadsheet and writes an overview
with no keys at all. Turning on Lockdown leaves all of that working and switches off research, Granola, calendar and
the Sheet, each with a reason. The owner's own install still uses Claude and Gemini after the update.

**Decisions for the owner** (defaults unless he says otherwise):

| # | Question | Default |
| --- | --- | --- |
| 1 | One Lockdown switch for every family app on this Mac, or one per app? | **Shared**, like keys and preferences already are (`family.py`): turning it on in The Lodge turns it on in Traverse too. Trailmix joins when it moves onto the host |
| 2 | Memory thresholds | Trailmix's (under 12 GB: mixed; 12–20 GB: local with ~7B; over 20 GB: room for ~14B), adjusted by 22a |
| 3 | What the owner's own install uses afterwards | Unchanged (Claude reads notes, Gemini sorts, the local model writes overviews). He can choose "On this Mac" from the Settings card |
| 4 | Order | 22a first, then b, c and d (independent of each other), then e, then f |

**Depends on:** nothing outside this chunk. Each part is one commit in TrailmixFamily (a to e) or here (f), with
`scripts/check` green in both repos.

**Result (2026-10-23, b to f built in this repo).** The owner also said to build for a brand-new user (set up like Trailmix
onboards people) and to keep personal information and API keys out of the public release.
- **b · Resources and the memory gate** (`core/server/resources.py`, `psutil`): memory, disk, chip, pressure; `check()`
  says wait only when the model can't fit at all, the disk is too full to swap, or macOS reports critical pressure.
  `ai` runs it before every local call (skipped when the model is already loaded, or Ollama is on another machine) and
  raises a provider-down `AIError` that starts "Waiting for memory", so jobs park with that reason, and the scheduler
  puts them back by itself once there's room. "Proceed anyway" (`go(force)`) runs inside `resources.proceed_anyway()`.
  A local call's answer is capped at 4,096 tokens and its timeout is 15 minutes (was 30), so a model that never stops
  costs minutes. `GET /api/system`. 20 tests (and one in the CRM for a note parked on memory).
- **c · Ollama from inside the app** (`core/server/ollama_setup.py`, `OllamaSetup.tsx`): install the official app
  (accepted only with Ollama's Developer ID, team `3MU9H2V9Y9`), open it, pull the recommended model (7B from 15 GB of
  memory, else 3B) with progress. Shown in the setup and in Settings → On this Mac. 6 tests (the real download and the
  real install were **not** run: faked). 8 tests.
- **d · Lockdown** (`core/server/lockdown.py`, `core.lockdown`, shared across family apps): `ai.configured()` says
  "Lockdown mode is on" for anything not running here (including model lists and Test); Ollama installs and pulls are
  refused; the Mac updater makes no automatic checks (it asks `/api/app`), "Check for updates" still works.
  Settings → Privacy has the switch. In the CRM, Granola, calendars, the shared Sheet, Gemini research and Gravatar
  each stop, their scheduled turns queue nothing, and their Settings sections say why. "Copy research brief", imports,
  the network, overviews and backups are unaffected. Tests run every outward path with a guard that fails any request
  to another computer (host: 10; CRM: 3). **Not checked:** the Swift change compiles (the install builds it) and that
  the menu bar copy of the setting follows the server.
- **e · First run**: `core/web/views/Welcome.tsx`, one question per screen, all skippable: Hello (your name), where AI
  runs (`ChooseAi`: this Mac's line first, three choices, the one that suits the Mac marked Recommended), Privacy
  (Lockdown), each module's own step (`ModuleWeb.setupStep`; The Lodge's is "Who are you / bring people in"), Done.
  `Module.ai_jobs` gives each AI job a label and a weight; "Mixed" puts heavy jobs on the cloud provider
  (`ai.heavy_provider`) and light ones on Ollama. A new data folder gets the screens; an install that was already in
  use (it had saved settings the first time this version started) skips them and sees one card in Settings → AI,
  "You can now run everything on this Mac". Walked through in a browser on an empty data folder. 11 tests.
- **f · The Lodge**: reading notes and documents and sorting now default to "auto" (they follow setup). On a Mac with
  less memory than `localAiMinGb` in `app.json` (24 GB), a local model reads in **basic mode**: rules find the people,
  the model writes the summary, key points and action items, and the result always waits in the Inbox. Sorting and
  spreadsheet columns run as rules on the local path (22a: the rules match the 7B). An install that was in use keeps
  Claude for reading and Gemini for sorting if it has those keys (a one-time step at startup; a new install doesn't
  get it). Settings → People has a plain list of what works on this Mac, what needs a key, and what Lockdown switches
  off. README, INSTALL.md, the download page and TRAILMIX.md say the same. 8 tests. The whole suite is 397 tests, `scripts/check` green.
- **Thresholds.** 24 GB is a guess from 22a's "Mixed at 16 GB": a 14B model wasn't measured. 15 GB for the 7B is
  Trailmix's rule. The advice turns to "cloud" only under 8 GB of free disk; a fuller disk just gets a warning.
- **Not built:** reading long documents on a local model in parts (basic mode asks for the notes only, the answer cap
  and the new timeout bound a stuck one, and a failed read falls back to rules). Release 0.4.0: cut 2026-10-24 (tag `v0.4.0`; CI builds it as a pre-release and `promote.yml` makes it the full release after 3 days).
- **In TrailmixFamily (2026-10-24):** pushed as one commit, `c6f4648` (b to e together, not one commit each), and this
  app is pinned to it. Not pushed to a remote. Traverse picks it up when it next syncs, and needs `psutil` in its
  `requirements.txt`, `localAiMinGb` in its `app.json`, and `welcomeTitle`/`welcomeLead` in its `identity/copy.ts`.
- **Public repo reposted (2026-10-24).** The repo was deleted and created again with a cleaned history: every real
  contact's name, email and phone number, the owner's own name, email and machine name, and the one-off DynaCRM
  migration tools are gone from every commit, and every commit carries the GitHub identity `TheRealEminem`. The old
  PRs, releases and tags went with the old repo; the first release of the new one is 0.4.0. TrailmixFamily (private) and
  the Trailmix and Traverse repos (public) still carry the owner's name in their histories.
- **Keys.** A key typed into one family app is already shared (`ai.*`). The Anthropic key in the family file on this Mac
  is 24 characters (Anthropic keys are about 100) and was saved from Traverse on 2026-10-20, which is why Claude
  rejected it in 22a; it needs to be entered again in any family app.

## 6. Risks and spikes

| Risk | How we find out | Fallback |
| --- | --- | --- |
| Document libraries (`lxml`) don't install under the bundled Python 3.14 | Chunk 0 spike | Pin the bundled Python to the newest version with wheels (edit `PY_VERSION` / `PY_SHA256` in `build-app.sh`) |
| SQLite fuzzy matching decides differently from `pg_trgm` | Chunk 1 fixture of real name pairs | Tune the score or thresholds; the fixture is the oracle |
| Single job worker makes imports slow | Chunk 8 | Job lanes (planned) |
| Claude "Schema is too complex" returns | Chunk 7 tests | Strict flat schema (invariant 1) |
| Granola has no usable third-party access | Chunk 12 spike | Keep the manual/Claude Code pull into the meeting endpoint |
| Network canvas is slow in WebKit | Chunk 6 at 600 nodes | Lower the node cap, simplify drawing |
| Secrets sit unencrypted in the app's SQLite file | Known | Same exposure as the old `.env` today; Keychain in chunk 13 if wanted |
| Changing the bundle ID later breaks updates | Chunk 11 | Choose it before the first signed build |
| A local model misses or makes up people when reading notes | Chunk 22a, against Claude on the same notes | Basic mode: rules plus review for small models; recommend Mixed below the size that holds up |
| Lockdown misses an outward path | Chunk 22d test that fails any call off this computer | The test runs every module's sync jobs; a new outward feature must add itself to it |
| `psutil` won't install under the bundled Python | Chunk 22b, first build | Read memory with `sysctl` and `vm_stat` instead |
| Changing AI defaults moves existing installs off their providers | Chunk 22f migration test | Store the old default for any job that has a key and was never set |

## 7. Not in this plan

- **Merging with Trailmix** as a `meetings` module (`ARCHITECTURE.md` §13): the CRM would listen for a shared
  "meeting recorded" contract. The `ingest/meeting` endpoint is built to be that seam. The owner (2026-10-12): Trailmix will
  be a meeting source alongside Granola, and it imports from Granola too, so the same meeting can arrive by two routes.
  That is already covered: a meeting is matched by its origin and id, and otherwise by time and shared people, so the
  second arrival joins the first instead of making a second meeting, and each route stamps its own `source`
  ("trailmix", "granola", "calendar") so any one can be taken back. When the apps become one, the Trailmix route is
  the `meetings` module publishing the contract and Granola becomes its import, not the CRM's.
- **Other people in the owner's organization:** the same server in Docker with real accounts and a per-user "me". The
  host has one shared token and SQLite today, so this needs host work: users, per-record visibility, and
  probably a different database. Chunk 2's `me` parameter is the only preparation we make now.
- Semantic search over notes, "ask your network" Q&A, relationship-health scoring, enrichment, native extras
  (global quick-capture hotkey, Spotlight, widgets), an iPhone companion.

## 8. How to work through this

1. Read `DESIGN.md` and `ARCHITECTURE.md` (especially §3, the rules) before writing anything.
2. One chunk at a time. Stop at "done when" and let the owner look before starting the next.
3. A module never imports another module or reads its tables. Modules talk through events, contracts, links,
   search, jobs, settings and AI.
4. Port tests with the code; the old suite (1,186 lines) is how we know nothing regressed.
5. Run `scripts/check` before closing a chunk, and look at Day and Dusk, 375 px and 1440 px.
6. Tick the boxes here, and update the progress table.
7. Commit at the end of each chunk, once `scripts/check` is green (the owner's standing instruction, 2026-10-12). Never read, copy or print `.env` or `API Keys/`.
