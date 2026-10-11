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
| 7 | AI layer in the host (structured output, providers, settings) | M | ☐ |
| 8 | Ingestion pipeline (documents, notes, review, jobs) | L | ☐ |
| 9 | Inbox and review screens | L | ☐ |
| 10 | Importers: spreadsheets, LinkedIn, recorded meetings | M | ☐ |
| 11 | Mac polish: mark, menu, signing, disk image | M | ☐ |
| 12 | Capture automation: Granola and calendars | M | ☐ |
| 13 | Cutover and hardening | S–M | ☐ |

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
| D3 | Bundle ID | `local.family.lodge` while developing. **Pick a real reverse-DNS ID before the first signed release**: changing it later breaks updates and granted permissions | Chunk 11 |
| D4 | Modules in `app.json` | `["crm", "tasks"]`. `notes` stays in the repo as the reference module but is switched off | Chunk 4 |
| D5 | One module or several | One `crm` module (graph, tiers, inbox, importers). Splitting ingestion out would make it write another module's tables, which rule 1 forbids | When Trailmix merges in as `meetings` |
| D6 | Meetings and documents | Stay CRM-owned *interaction records* (they are the evidence behind relationships). A future `meetings` module publishes an event and the CRM links to it | Merge with Trailmix |
| D7 | Database | SQLite (WAL) + FTS5; fuzzy name matching in Python over an in-memory index | Chunk 1 (if matching quality regresses) |
| D8 | API keys | Entered by the owner in Settings → AI (write-only in the UI; stored in the app's SQLite file under `~/Library/Application Support/The Lodge/`). Env presets still work. Agents never read or copy the old `.env` or `API Keys/` | Chunk 13 (Keychain option) |
| D9 | AI roles | Extraction = Claude Opus 5.5, utility (column mapping, triage) = Gemini Flash, as chosen earlier. Local Ollama and others selectable | Chunk 7 |
| D10 | Signing | Ad-hoc until teammates exist. Ad-hoc means Gatekeeper's first-launch dance and permissions asked again after each update. Developer ID + notarization needs a paid Apple Developer account | Chunk 11 |
| D11 | Updates | The starter's updater reads **public** GitHub releases without credentials. Fine for later; private distribution needs a change or a manual DMG | Chunk 11 |
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

- [ ] `ai.structured(prompt, system, schema, choice)`: adapters ported from DynaCRM: Claude (strict flat schema,
  streaming, fallback beta; invariant 1), Ollama native (`format`, `num_ctx`), OpenAI-compatible (json_schema →
  json_object → plain, one repair retry). `AIError.provider_down` (invariant 2).
- [ ] Module settings `crm.extraction_provider` and `crm.utility_provider` (auto or a provider id), a Settings
  section that shows which model does which job, a "Test" per provider.
- [ ] Keys via Settings (D8). `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` env presets still work.
- [ ] Host tests with fake transports: stream fakes, error classification (credit, auth, rate, too long, refusal,
  max_tokens), the repair retry.

**Done when:** "Test" passes for each provider the owner configures, and a structured call round-trips a sample schema.
**Depends on:** 0 (can run in parallel with 4–6).

### Chunk 8 · Ingestion pipeline (L)

- [ ] `crm_inbox` lifecycle (pending → review → applied / discarded / failed / skipped) with host jobs
  `crm/extract`.
- [ ] **Job lanes** (small host change): cloud providers run 4 at a time, a local model runs 1. The host's single
  worker would turn DynaCRM's 3½-minute import into about an hour.
- [ ] Port `documents.py` (docx incl. tables, pdf, pptx incl. notes, txt, md), triage, extraction schema and
  prompts, the proposal builder, `apply` (global lock, exact-match recheck), `needs_review`, content-hash dedupe
  (invariants 3–6), and the rules-based fallback.
- [ ] Provider-down raises `jobs.Wait("Anthropic is out of credit…")`: the batch parks with a reason and resumes
  on **Go** after the owner tops up, instead of failing everything.
- [ ] Publish `actions.found` for a meeting's action items, so the existing `tasks` module creates follow-ups
  linked back to the meeting.
- [ ] Port `test_ingest.py`, `test_llm.py` and the file-batch tests.

**Done when:** tests are green with a fake AI; one real canary document (the owner's key, one FirstData file) yields
the same shape of proposal as DynaCRM did; killing the server mid-batch and restarting resumes with no duplicates.
**Depends on:** 2, 7.

### Chunk 9 · Inbox and review screens (L)

- [ ] Drop zone and folder picker (the Swift window already supports folders), paste notes ("Sort & review"), the
  queue with progress, filters and "Approve all ready", per-job review (match editing, relationships on/off,
  warnings), retry and discard, spreadsheet mapping view, "Needs you" chips via `JobStatus`.
- [ ] Sidebar Inbox badge counts what needs the owner.

**Done when:** a small folder imports end to end through the UI (fake AI, then one real run).
**Depends on:** 8.

### Chunk 10 · Importers: spreadsheets, LinkedIn, recorded meetings (M)

- [ ] Spreadsheet import (invariant 8): AI column mapping with a synonym fallback, org-row detection, `met_with` →
  `knows` from teammates, relationship strength.
- [ ] LinkedIn `Connections.csv` (official export only; idempotent; dated by "Connected On").
- [ ] `POST /api/crm/ingest/meeting` (title, start, attendees with emails, notes, transcript): matches invitees by
  email, dedupes by `external_id` and content, attaches to an existing same-day meeting (`find_existing_meeting`).
- [ ] The webhook endpoint (D15).

**Done when:** the five FirstData spreadsheets import into a scratch database with the old app's counts (using
recorded column mappings, since the AI step isn't deterministic); a replayed meeting does not duplicate.
**Depends on:** 8. **Milestone D** after 9 and 10.

### Chunk 11 · Mac polish (M)

- [ ] Menu-bar template icon (`mac/Sources/AppHost/Mark.swift`, line art of the same mark, 18×18) and
  `mac/AppIcon.icns`.
- [ ] Menu items, window size, Open at Login, data folder permissions.
- [ ] Decide D3, D10, D11. Build with `scripts/build-app.sh --dmg`.
- [ ] This Mac has the Command Line Tools only (no Xcode): don't use `@State`, `@Entry` or `#Preview` in Swift.
- [ ] Behaviour checks: kill the server → it restarts (up to 3 times in 2 minutes) then explains; quit leaves no
  stray process; two copies of the app don't fight over the port.

**Done when:** the `.dmg` installs into `/Applications` on this Mac, the first-launch steps are written down, and
CI builds it on a version tag.
**Depends on:** 4 (earlier is fine).

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

### Chunk 13 · Cutover and hardening (S–M)

- [ ] Nightly backup and restore (Settings), JSON export, an upgrade test (an old database file plus a newer
  migration), performance on synthetic 50,000 entities / 250,000 edges (the snapshot cache), keys-at-rest option
  (Keychain) if wanted.
- [ ] The owner uses The Lodge daily. Stop the Docker stack, archive `DynaCRM (OLD)`, keep the Postgres dump.

**Done when:** a week of daily use without opening the old app, and a restore from backup has been tried.
**Depends on:** everything. **Milestone E.**

---

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
  "meeting recorded" contract. The `ingest/meeting` endpoint is built to be that seam.
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
7. Don't commit unless the owner asks. Never read, copy or print `.env` or `API Keys/`.
