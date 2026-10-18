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
| 13 | Cutover and hardening | S–M | ◐ built 2026-10-12; cut over 2026-10-18; old stack to be removed after a week |
| 14 | **Research flags: people who need deep research** (asked for 2026-10-12) | M | ☑ 2026-10-12 |
| 15 | **Find someone from Home; AI overviews and questions on profiles** (asked for 2026-10-13) | M | ☑ 2026-10-13 |
| 16 | **Profile pictures** (asked for 2026-10-13) | M | ☐ proposed; waiting on the owner's choice of sources |

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
| D9 | AI roles | Extraction = Claude Opus 5.5, utility (column mapping, triage) = Gemini Flash, as chosen earlier. Local Ollama and others selectable | Chunk 7 |
| D10 | Signing | **Ad-hoc, chosen 2026-10-12**, until teammates exist. Ad-hoc means Gatekeeper's first-launch dance and permissions asked again after each update. Developer ID + notarization needs a paid Apple Developer account | Chunk 11 |
| D11 | Updates | **Manual disk image** (chosen 2026-10-12): `updateRepo` stays empty, because the starter's updater reads **public** GitHub releases and this repo is private | If the repo is ever made public |
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

**Done when:** the ported tests pass, and a fixture of 30+ name pairs from the real data (Stacey Hollis/Hoshimiya,
Oak/PGX Foundation, Michael/Mickey Fairweather, OEN/Northwest Entrepreneurship Network, "Contact 230"/Dan Rowe…)
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
- **Keychain: not built.** Keys sit in the 0600 database in the 0700 data folder, the same exposure as the old `.env`,
  and they are copied into every backup. Moving them to the Keychain from a Python server means either shelling out to
  `security` (the secret appears on a command line) or a Swift bridge, and the backups would then not carry the keys. It
  is a decision for the owner, not a default; it is a small chunk if wanted.
- **Cutover prepared:** the old Postgres holds 381 entities and 839 relationships, last changed 2026-09-26, exactly
  what was imported, so nothing is waiting to come across and the importer must not be run again (it would overwrite
  edits made in The Lodge). A final dump is saved at `_reference/dynacrm-final-dump-20261012.sql.gz` (0600, git-ignored;
  it includes the old app's settings table). The Postgres container is stopped.
- **Cut over (2026-10-18, the owner's go):** installed the current build (`aa02159`) with `scripts/install-app.sh`: checks, the
  13 app behaviour checks, a backup first, swap, and a data check ("9 tables, nothing missing"). It serves 128 people (9
  strong, 12 working, 58 light, 29 indirect, 20 not linked), 67 flagged for research, 8 backups. Docker is closed, so the
  old stack is stopped; nothing in the new app depends on it. Not yet set up in the new app: an AI key (extraction is on
  Claude, so imports wait until one is saved), Granola, a calendar address, Open at Login.
- **Still the owner's:** use The Lodge daily for a week, then archive the `DynaCRM (OLD)` folder and remove the old Docker
  containers and volume (the dump is the way back). Install the current build first (`scripts/build-app.sh`, then the
  disk image); the copy in `/Applications` is from chunk 11.
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

### Chunk 16 · Profile pictures (M) — PROPOSED

The owner asked (2026-10-13) for a picture of each person and whether LinkedIn can supply them. LinkedIn's API doesn't
hand out other people's photos, and scraping it breaks its terms, so the proposal is: (1) add a picture by hand on a
profile (drop, paste or choose a file; copying the photo from LinkedIn in the browser and pasting it works), shown
everywhere a person appears; (2) match photos from the Mac's Contacts app by email, phone and name (asks for
Contacts access once; nothing leaves the Mac); (3) optionally, Gravatar for people with an email address (a hash of
the address goes to Gravatar, so it's a setting, off by default). Waiting on the owner's choice.

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
