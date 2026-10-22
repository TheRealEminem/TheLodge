# Family architecture

How apps in the Trailmix family are built, so that each new app can start from this folder and, later, all
of them can become **one app with each of them as an add-on module**.

**If you are an agent:** read this file and `DESIGN.md` before changing anything. Then read
`core/server/module.py` and `core/web/registry.ts`, which define the module contract. Then read `modules/notes`,
the reference module that uses every part of the contract. Build new features the way notes does. The rules
in [§3](#3-the-rules) keep modules combinable later, so don't trade them for a shortcut.

---

## 1. The idea: one host, many modules

```
              ┌──────────────── one app (app.json) ─────────────────┐
              │  host (core/)            modules (modules/<id>/)     │
              │  ─────────────           ────────────────────────    │
  Mac app ──► │  server: db, settings,   notes:  tables, API, jobs,  │
  (mac/)      │  jobs, AI, events,       pages, Home card, settings  │
              │  links, search, auth     tasks:  …                   │
              │  web: shell, sidebar,    meetings (Trailmix, later)  │
              │  Home, Settings, kit     your next app …             │
              └──────────────────────────────────────────────────────┘
```

- The **host** (`core/`) is everything apps share: the server, the database, settings, background jobs, AI
  providers, sign-in, search, the web shell, the design kit and the Mac app.
- A **module** (`modules/<id>/`) is one feature area: its own tables, API, background work, pages, Home card
  and settings section. It's one folder with a server half, a web half and tests.
- **`app.json`** says who the app is and which modules it's made of.

So a **standalone family app** is the host plus one module (or a few), with its own name in `app.json`, and the
**unified app** is the same host with every module turned on. Nothing gets rewritten when apps merge, because
each module was always a module.

This starter is an app called "Starter" with two modules. **Notes** is the reference module: write a note, an
AI summary is made in the background, and its action items are announced. **Tasks** picks up action items from
any module and links each one back to where it came from. The two never import each other; they cooperate
through the host. That's the pattern every family module follows.

## 2. How it runs

```
Starter.app (Swift, menu bar)                 Docker on a server
 ├─ starts and supervises ─┐                   └─ runs the same server ─┐
 └─ window (WebKit) ───────┤                                            │
                           ▼                                            ▼
            Python server (FastAPI, uvicorn) on 127.0.0.1:<port>
              ├─ /api/…            the host's API + /api/<module>/… for each module
              ├─ /                 the built web app (React)
              └─ SQLite + files    ~/Library/Application Support/<Name>/ (or /data in Docker)
```

- **One process is the whole app.** The server serves both the API and the web app on one port.
- **The Mac app is a thin host.** It ships its own Python, the server and the web app inside the `.app`, so
  nothing needs installing. It starts the server, restarts it if it crashes, and shows the web app in its own
  window. The window bridge (`window.webkit.messageHandlers.app`) lets the page ask it to quit or show a file
  in Finder. The Dock icon is there only while the window is open; otherwise the app lives in the menu bar.
- **The server stops itself if the Mac app dies.** It watches its parent process, so it never lingers on the port.
- **The same server runs in Docker** for self-hosting. There, sign-in turns on when `APP_ACCESS_TOKEN` is set.
- **Development:** `scripts/dev` runs the server with auto-reload, plus Vite on :5173 with hot reload.

## 3. The rules

These keep modules combinable. Breaking one now means a rewrite when the apps merge.

1. **A module never imports another module** and never reads or writes another module's tables. It reaches
   the rest of the app only through the host: events and contracts, links, search, jobs, settings and AI.
2. **A module owns everything named after its id:** tables `<id>_*`, settings `<id>.*`, API `/api/<id>/…`,
   pages `#/<id>/…`, events `<id>.*`, and files in `DATA_DIR/<id>/`.
3. **Every row gets a random text id** (`db.new_id()`), never an autoincrement number, so databases from
   separate apps can be merged without collisions. Things are referred to across modules as refs, `"<module>:<id>"`.
4. **Schema changes are append-only.** Add a new step to the module's `MIGRATIONS` list; never edit or
   reorder a step that has shipped.
5. **Slow work is a job** (`jobs.enqueue`), never done inside a request or an event handler. Jobs must be safe to
   run twice, because they're re-run after a restart.
6. **State lives in the database.** If the server restarts at any moment, nothing is lost and everything picks
   up where it left off.
7. **Nothing is written inside the app bundle at runtime.** That would break its signature. All data goes in `DATA_DIR`.
8. **Works offline and locally by default.** Cloud services are optional and chosen in Settings, and local AI
   models are unloaded after use.
9. **Shared code has one copy: the family's, and each app pins a version of it.** `core/`, `mac/`, the shared
   scripts, the shared modules (`tasks`, `notes`) and the build setup live in `~/Code/TrailmixFamily`.
   `scripts/sync-family` copies a family commit into the app and records it in `family.lock`, so every app is
   developed and released on its own and takes family updates when it chooses, like a pinned dependency.
   `scripts/check` warns (it doesn't fail) when the app's copy differs from its pinned version; send a deliberate
   change back with `scripts/sync-family --push`. An app's own parts are `app.json`, `family.lock`, `identity/`
   and its own modules. A shared module's schema grows only in the family: `core_migrations` counts steps per
   module, so two apps that each added a different "step 2" could never share data or merge.

## 4. Folder map

```
app.json                  who the app is and which modules it's made of
family.lock               the TrailmixFamily commit this app's shared code comes from (written by scripts/sync-family)
VERSION                   the version number (a release tag must match it)
core/
  server/                 the host's server (Python package "core.server")
    app.py                creates the FastAPI app, loads modules, the host's own API
    config.py             app.json + environment, DATA_DIR, UI_DIR
    module.py             ★ the module contract (server half)
    db.py                 SQLite, migrations per module, new_id(), now()
    settings.py           namespaced settings, secrets never sent back
    jobs.py               resumable background jobs, approval and "wait" gates
    ai.py                 AI providers (Ollama, Claude, OpenAI, Gemini, DeepSeek, OpenAI-compatible)
    events.py             publish/subscribe between modules, plus the change counter
    contracts.py          ★ shared events any module can publish or listen to
    links.py              links between things in different modules
    search.py             one search across every module
    auth.py               optional token sign-in for server installs
  web/                    the host's web app (React + Tailwind 3, built by Vite)
    registry.ts           ★ the module contract (web half)
    App.tsx, Sidebar.tsx  the shell: sidebar, narrow-window drawer, routing
    router.ts             hash routes (#/notes/<id>), no router library
    live.ts               useLive(): data that refreshes when anything changes
    shell.tsx             useShell() (toast, confirm, theme, app info), useSettings()
    api.ts                request(), json(), the host's API, the Mac bridge
    components/           the design kit (ui, icons; illustrations re-exports the identity's art) + blocks
                          (Section, JobStatus, LinkedList, Avatar, Tags, Empty…)
    format.ts             dates and names: relativeTime, formatDate, initials
    views/                Home, Settings, Login, NotFound
  tests/                  the host's tests (they use a stand-in module, not the real ones)
identity/                 the app's own look, the only part of the shell that differs between family apps:
  tokens.css              colors, shadows and atmosphere for Day and Dusk (imported before core's index.css)
  art.tsx                 Logo, Scene, Ambient, Badge
  copy.ts                 the host screens' brand copy (sign-in title, Your data wording)
  public/favicon.svg      the mark, for the browser
  mac/                    Mark.swift (menu bar icon), AppIcon.icns, and the script that draws the icon
  DESIGN.md               the app's own design notes
modules/
  notes/                  the reference module: server/, web/, tests/
  tasks/                  a second module that cooperates with notes through a contract
mac/                      the Mac app (Swift): menu bar, server supervisor, window, updater
scripts/
  dev                     run for development
  check                   everything CI checks (tests, types, build, style rules)
  build-app.sh            build the Mac app (and the disk image with --dmg)
  install-app.sh          check, build, back up, and swap the new app into /Applications, with a rollback
  smoke-test.sh           try a built app's updater end to end: update, go back, beta updates, busy, skip
  promote-beta.sh         make the newest beta the release everyone gets, once it's been tried
  new-module              start a module from scripts/module-template
  sync-family             take a family version and pin it (--check: warn about drift; --push: send a change back)
conftest.py, pytest.ini   test setup: throwaway data, fake AI, skips tests of modules that are off
Dockerfile                the server for Linux
.github/workflows/        tests on every push; a beta of the Mac app on a version tag, promoted after a few days
```

## 5. Identity: app.json

```json
{
  "name": "Starter",               // shown everywhere; also the .app's name and its data folder
  "id": "starter",                 // lowercase; the database file, storage keys, cookie name
  "tagline": "a new trail",        // lowercase, under the wordmark
  "bundleId": "local.family.starter",
  "envPrefix": "STARTER",          // environment overrides: STARTER_DATA_DIR, STARTER_AI_PROVIDER…
  "port": 8790,                    // must differ between family apps that might run at the same time
  "updateRepo": "",                // "owner/repo" on GitHub for self-updates; empty = no updates
  "modules": ["notes", "tasks"]    // in sidebar order
}
```

`build-app.sh`, the server, the web app and the Mac app all read this file. **Renaming an app means editing
this one file** (plus its mark, below). Nothing else has the name hard-coded.

**Ports:** Trailmix uses 8765 (and 8770 for its transcription worker). Give each family app its own port in
the 8780–8799 range, and keep a list here:

| App | Port |
| --- | --- |
| Trailmix | 8765 |
| Starter (this template) | 8790 |
| The Lodge | 8791 |
| (a local preview config in The Lodge) | 8792 |
| Traverse | 8793 |

## 6. The module contract

### Server half: `modules/<id>/server/__init__.py` exposes `MODULE = Module(...)`

| Field | What the host does with it |
| --- | --- |
| `id`, `name` | `id` must equal the folder name. `name` is shown in the app. |
| `router` | A FastAPI `APIRouter`, mounted at `/api/<id>`. |
| `migrations` | Append-only SQL steps for the `<id>_*` tables, applied once each on startup. |
| `settings`, `choices` | Defaults stored as `<id>.<name>`, with allowed values. Edited on the Settings page. |
| `jobs` | `{kind: handler(job)}`: background work this module knows how to do. `lanes` (optional): `{kind: "cloud" or a function of the target}` to let a kind run four at a time when it only waits on a web API. |
| `recurring` | `{kind: seconds}` (or a function returning seconds, `0` = paused): the host queues that job on a schedule (`core/server/schedule.py`), so it runs on the job runner like any other. The target is always `"scheduled"`; finished rows are cleared as the next is queued. Handlers must be safe to run twice. |
| `export` | `() -> {name: [records…]}`: what the module holds as plain data. The host's Settings, Your data, Export writes every module's into one JSON file in the data folder's `exports/` (no settings, so no keys). |
| `subscribe` | `{event or "prefix.*": handler(payload)}`: what it listens to. |
| `search` | `(q, limit) -> [{id, title, snippet}]`: its part of the sidebar search. |
| `describe` | `id -> {title, href}`: how its things appear in other modules' links and in search. |
| `startup` | Runs once after every module is loaded. |
| `count` | `(a database) -> {"people": 381}`: what it holds, read from any copy of the database, to label backups in Settings, Your data. |
| `offers` | `{"people.search": handler(args)}`: questions other family apps on this Mac may ask it (§8, the family link). A handler gets a dict and returns plain data. |
| `people` | `(q, limit) -> [{id, name, email?, detail?, is_self?}]`: its part of the people directory (`core/server/people.py`, `GET /api/people`, `PersonPicker`). Refs come back as `<id>:<person id>`; `is_self` comes back as `core:me`. |

### Web half: `modules/<id>/web/index.tsx` default-exports a `ModuleWeb`

| Field | What the host does with it |
| --- | --- |
| `id`, `name` | Must match the server half. |
| `nav` | Sidebar entries `{label, icon, path, badge?}`. A badge is a component that renders a count. |
| `routes` | `{path: "notes/:id", view}`. Paths start with the module's id. |
| `primary` | The sidebar's big button `{label, icon, run}`. The first enabled module with one gets it. |
| `home` | A card on Home. In the unified app, Home is where every module shows what's new. |
| `settings` | A section on the Settings page (use `Section` and `useSettings()`). |

Modules import the host's web code as `@core/...` (`@core/components/ui`, `@core/live`, `@core/shell`…), never
another module's.

## 7. What the host gives modules

| Need | Use | Notes |
| --- | --- | --- |
| Store data | `db.query/one/execute/connect`, `db.new_id()`, `db.now()` | One SQLite file; WAL; short connections. Use JSON text columns for nested data and FTS5 for search. |
| Files | `config.DATA_DIR / "<id>"` | Never inside the app bundle. |
| A setting | `Module.settings` + `settings.section("<id>")` | Secrets end in `_api_key`/`_token`; they're write-only and preset from `<PREFIX>_<ID>_<NAME>`. |
| Slow work | `jobs.enqueue(id, kind, target, approve=…)` | One worker by default (a "cloud" lane runs four side by side), resumable. `approve=True` parks it as "Needs you". A handler can `raise jobs.Wait("reason")` to park itself (low memory…), and the user can force past that. `job.stage("…")` shows progress. |
| AI | `ai.complete(prompt, system)` → `(text, provider)` | Uses the app-wide provider and fallback from Settings → AI. Raises `ai.AIError` with readable reasons. `ai.local_first()` tells you whether it would run on this Mac. |
| Tell others | `events.publish("<id>.thing.happened", {...})` | Handlers run immediately and must be quick. Every publish also refreshes open screens. |
| A shared meaning | `contracts.py` (`ACTIONS_FOUND`, `ITEM_DELETED`, the `WORK_*` ones for work kept elsewhere too) | Add a contract when a second module cares about the same kind of thing. |
| Point at something elsewhere | `links.add(from_ref, to_ref, kind)`, `links.linked(ref)` | The host stores the pair; each side's module describes its own things. |
| Be searchable | `Module.search` | Results are merged into the sidebar search. |
| Fresh screens | `useLive(load, deps)` | Refetches whenever anything changes on the server: every 2s while visible, and at once after the app's own changes. |
| Feedback | `useShell().toast / confirm`, `JobStatus`, `JobChip`, `LinkedList`, `Section` | See `DESIGN.md` for the visual rules. |
| Ask another family app | `family.call("people.search", q="ana")` | Its own modules first, then a running family app that offers it. Raises `family.Unavailable` with a sentence for the screen ("Open The Lodge to see this here"). Only from server code, and never as a substitute for events between modules in one app. |

Backups (`core/server/backup.py`) are the host's: a daily SQLite online backup in `<data folder>/backups/` (kept 14),
"Back up now", and restore, which makes a backup of what it replaces, copies the chosen one over the live database,
brings an older one up to date with the current migrations and publishes `core.restored` (a module that caches
anything built from its tables listens and drops it; the CRM does).

## 8. How modules work together: a walkthrough

What happens when you summarize a note:

1. **notes** saves the note (`PATCH /api/notes/<id>`) and enqueues `summarize`. Because "Summarize automatically"
   is off, the job parks as **Needs you**, and the note shows a yellow chip with a Summarize button.
2. You press Summarize, which calls the host's `POST /api/jobs/<id>/go`. The single worker runs notes' handler,
   which calls `ai.complete()` (your Ollama model, or your cloud provider).
3. notes stores the summary and publishes the shared contract
   `actions.found {source_ref: "notes:<id>", items: [...]}`. notes doesn't know or care who's listening.
4. **tasks** listens for `actions.found`. It creates one task per item and adds a link `notes:<id> → tasks:<id>`.
   tasks doesn't know what a note is.
5. Every publish moves the change counter. Open screens refetch, so the note shows its summary and a "Linked"
   list of the tasks (titles supplied by tasks' `describe`), and the sidebar's Tasks badge goes up.
6. Delete the note and notes publishes `item.deleted`. tasks keeps the tasks but drops their source.

**Which mechanism to use:**

- **Event:** "this happened", for anyone who cares. Name it after your module (`notes.note.saved`).
- **Contract:** an event with a shared meaning that more than one module publishes or consumes
  (`actions.found`). Its shape is written down in `contracts.py`.
- **Link:** a lasting relationship between two things, shown on both sides.
- **Search/describe:** making your things findable and nameable elsewhere.
- **Offer:** a question another family *app* on the same Mac may ask (`Module.offers`, answered over localhost
  with the family token). Use it for data that lives in another app, such as The Lodge's people seen from Traverse.
- **Never:** importing another module, querying its tables, or calling its HTTP API from the server.

**The family link** (`core/server/family.py`). Family apps installed on one Mac share some settings and ask each
other for data, while each stays its own app:

- *Shared settings:* the AI settings, your name and the appearance live in `family.db` in the family folder
  (`~/Library/Application Support/Trailmix Family/`), which every family app opens directly, so they're there even
  while the other apps are closed. Each app also keeps its own copy, and Settings → Your family apps → "Share keys
  and preferences" turns sharing off for one app. An app joining fills in what the family lacks, and never
  replaces what it holds.
- *Registry:* each running app records its port and its modules' offers in `family_apps`, with a heartbeat each
  minute. `GET /api/family` lists the installed apps and which are open.
- *Calls:* `POST /api/family/call/<offer>` answers another family app, only with the family token (`X-Family-Token`,
  kept in `family.db`), so a web page can't reach an app's data through localhost. Data never leaves the Mac, and
  no app copies another's tables.
- The Mac app joins by default. A development copy (data in `./data`) or a server install joins only when
  `TRAILMIX_FAMILY_DIR` names a folder (`off` turns it off); tests use a throwaway one. A development copy beside
  the installed app sets `<PREFIX>_PORT` so it registers its own port.

## 9. Screens and navigation

- **Routes** are the URL hash (`#/notes/<id>`), so a link anywhere (including from the Mac app's menu) can open any page.
  `#/` is Home and `#/settings` is Settings. An app with one module and no Home card opens straight into that module.
- **Sidebar:** the mark and name, the primary button, search across everything (⌘K), Home (when there's more
  than one module), each module's nav items with badges, and Settings at the bottom. Below 1024px it becomes a
  drawer behind a frosted top bar.
- **Settings:** Appearance (Day/Dusk/System), your name, AI (provider, fallback, key, model picker, a connection
  test), then one section per module, then Quit.
- **Look and copy** follow `DESIGN.md`. `scripts/check` enforces the mechanical rules.

## 10. The Mac app (`mac/`)

- `HostApp.swift`: the menu bar item (Open, updates, Open at login, Quit). It starts the server, then opens the window.
- `BundledServer.swift`: runs `python -m uvicorn core.server.app:app` from `Resources/app` with `<PREFIX>_DATA_DIR`,
  `_UI_DIR` and `_PARENT_PID` set, restarts it up to three times in two minutes, then explains the failure in the menu.
- `MainWindow.swift`: the WebKit window, the `app` bridge, the Edit/View/Window menus, and external links opening in the browser.
- `Updater.swift`: GitHub releases → checksum check → same bundle ID and valid signature → swap in place, keeping
  the old version for Go back → relaunch; beta updates and skipping a version. Its decisions are in `UpdateRules/` (§11).
- `Mark.swift`: the menu bar icon. Each app draws its own motif there.
- **Native features a module needs** (global hotkeys, recording audio, notifications) live in `mac/`. They talk to
  the module through the server: the native side calls the module's API (Trailmix's recorder checks in once a second
  at `/api/recorder/check-in` and picks up commands), and the page talks to the native side through the bridge.
  Keep the module usable without them, from a browser or a server install.
- It builds with the Command Line Tools alone (no Xcode). See Gotchas.

## 11. Running, testing, shipping

| | |
| --- | --- |
| Develop | `scripts/dev`, then open http://localhost:5173 |
| Check everything | `scripts/check` (pytest, `tsc`, Vite build, style rules) |
| New module | `scripts/new-module journal "Journal"` |
| Build the Mac app | `scripts/build-app.sh` → `dist-app/<Name>.app`; add `--dmg` for the disk image and checksum |
| Update the installed app | `scripts/install-app.sh` (checks, builds, backs up, swaps, verifies; all on this Mac) |
| Release | bump `VERSION` and commit, then `git tag v0.2.0 && git push origin v0.2.0`. CI publishes a beta, which reaches everyone a few days later (below). |
| Check the updater's rules | `swift run --package-path mac UpdateChecks` (`build-app.sh` runs them too) |
| Try the updater end to end | `scripts/smoke-test.sh dist-app/<Name>.app dist-app/<Name>-<version>-arm64.dmg` (CI runs it before publishing) |
| Server install | `docker build -t app . && docker run -p 8790:8790 -v app-data:/data -e APP_ACCESS_TOKEN=… app` |
| Try the built app without touching real data | `env -i HOME=$HOME PATH=/usr/bin:/bin STARTER_DATA_DIR=/tmp/x STARTER_NO_OPEN=1 dist-app/Starter.app/Contents/MacOS/Starter` (prints "Would open …"; the server answers on the port) |

**Releases: a beta first, then everyone.**
1. **Tag.** Bump `VERSION`, commit, and push the tag `v<VERSION>`. `release.yml`, on a Mac builder, refuses a tag that
   doesn't match `VERSION`, builds with `scripts/build-app.sh --dmg` (which runs the updater's checks), runs
   `scripts/smoke-test.sh`, and publishes `<Name>-<version>-arm64.dmg` and its `.sha256` as a **pre-release** in
   app.json's `updateRepo`. With no `updateRepo`, nothing is published and the build stays an artifact of the run.
   A repo other than the app's own (a public one, for private code) needs a `RELEASE_TOKEN` secret that can write to it.
2. **Beta.** Installed apps with Beta updates on are offered it; everyone else isn't.
3. **Promote.** `promote.yml` runs `scripts/promote-beta.sh` every day. Once the newest pre-release has been out
   3 days (`BETA_DAYS`) with no open issue labelled `blocks release` (`BLOCKING_LABEL`), it becomes the full, latest
   release, and every installed app is offered it. Run the workflow by hand to check now: "dry run" only says what
   it would do, and a tag promotes that pre-release however long it's been out. `DRY_RUN=1 scripts/promote-beta.sh`
   does the same from this Mac.
4. **Hold it back** by labelling an issue `blocks release`; close it or take the label off to let the beta through.
   The label needs creating only the first time someone uses it.

**Updates in the app** (`mac/Sources/AppHost/Updater.swift`; the decisions are in `mac/Sources/UpdateRules/`, checked
by `mac/Checks/UpdateChecks` with the Command Line Tools alone):
- It looks at the repo's recent releases at launch and every six hours, and offers the newest version that's newer
  than itself: full releases, plus pre-releases with **Beta updates** on (the Updates submenu; off unless you turn it
  on). Never a skipped version.
- **Install version X…** downloads the disk image, checks it against the published SHA-256, checks that the app inside
  has the same bundle ID and a valid signature, swaps it in place and restarts. The version it replaced is kept in
  the data folder, at `updates.noindex/previous/<Name>.app` (one copy, the size of the app).
- **Skip this version** stops it being offered; a newer version still is. **Offer X again** undoes that.
- **Go back to X…** (Updates submenu, once an update has kept a version) asks first, then returns to the kept
  version, checked the same way with no download, and skips the version you left. Your data stays: migrations only
  add (rule 4), so the older version ignores steps it doesn't know, and starting a different version keeps a
  "before-update" backup first. A fresh install has nothing to go back to.
- **Not while busy:** before starting, and again just before swapping (waiting up to a minute), it asks the server,
  `GET /api/jobs/busy` (background jobs queued or running). While the app is busy it says so and offers Try again.
- Your choices are in `updates.noindex/choices.json` in the data folder, so `<PREFIX>_DATA_DIR` keeps a test apart
  from the real app. For tests: `<PREFIX>_UPDATE_URL` (a stand-in release list), `_UPDATE_DELAY`,
  `_UPDATE_NO_RELAUNCH`, and `_UPDATE_TEST=install` or `go-back` (does that after the first check, and writes each
  state to stderr).

Tests: `conftest.py` gives every test a throwaway data folder, the whole app (`client`), a fake AI (`fake_ai`)
and `jobs.drain()` to wait for background work. The host's tests use a stand-in "probe" module, so they pass
whatever modules an app has. Tests of modules that `app.json` turns off are skipped.

## 12. Recipes

**Start a new family app**

1. Make a folder, `git init`, and copy `scripts/sync-family` in from the family (`~/Code/TrailmixFamily`). Run it:
   it copies the shared code in and pins the version in `family.lock`.
2. Write `app.json`: name, id, tagline, bundleId, envPrefix, a free port, updateRepo, and modules. Add a
   `package.json` and `requirements.txt` (start from another family app's).
3. Make `identity/` (start from another family app's): the palette in `tokens.css`, the mark and scene in
   `art.tsx` and `public/favicon.svg`, `copy.ts`, and `mac/Mark.swift` and `mac/AppIcon.icns`. See `DESIGN.md` §2
   and §17.
4. Run `scripts/new-module <id> "<Name>"` for the app's main feature, and remove notes and tasks from
   `app.json` if they don't belong. Keep their folders: they're the reference.
5. Run `scripts/dev`, build the feature, then `scripts/check`.

**Add a page:** add a view component, then a route `{path: "<id>/something", view}` in the module's
`index.tsx`, plus a `nav` item if it belongs in the sidebar.

**Add a setting:** add the default to `Module.settings` (and `choices` if it's a fixed list). Read it with
`settings.section("<id>")`. Show it in the module's `settings` component with `useSettings()`, and write the
hint as the consequence ("Off: …").

**Add background work:** write `def handler(job)` that is safe to run twice, and register it in
`Module.jobs`. Enqueue it with `approve=True` when the user should press a button first. `raise jobs.Wait("…")`
for conditions they can override, `job.stage("…")` for progress, and `<JobStatus job={…} />` in the page.

**React to another module:** if what you need is a shared idea, add or reuse a contract in `contracts.py` and
subscribe to it in `Module.subscribe`. If it's specific, subscribe to that module's own event, knowing that it
silently does nothing when that module is off.

**Use AI:** `text, provider = ai.complete(prompt, system=...)` inside a job (never in a request). Show who
wrote it (`provider`) next to the result.

**Make a module work as its own app:** set `"modules": ["<id>"]` in `app.json`. If it has no `home` card, the
app opens straight into it, and Home disappears from the sidebar.

## 13. From separate apps to one app

The plan, and how far this template gets you:

1. **Now: build each new app on this template, as modules.** Each ships as its own app (its own `app.json`)
   while staying a module.
2. **Port Trailmix into a `meetings` module.** Trailmix predates this template, so here's how its parts map over:
   - **Data:** the `meetings` table becomes `meetings_items`, keyed by the existing `uid` column (Trailmix already
     gives every meeting one) instead of the integer id. Audio goes in `DATA_DIR/meetings/`.
   - **Settings:** Trailmix's `summary_provider`, keys and models move to the shared `ai.*`; the rest become `meetings.*`.
   - **Pipeline:** its stages become jobs. Transcribe and summarize use `approve=` for the two-step approval, and
     `jobs.Wait` replaces the RAM gate (`waiting_confirm`).
   - **Action items:** published as `actions.found`, so the tasks module takes over Trailmix's Tasks page.
   - **Native recorder:** moves into `mac/`, unchanged (it already talks to the server over HTTP).
   - **Pages and search:** routes `#meeting-12` become `#/meetings/<uid>`, and search moves to `Module.search`.
3. **One app.** List every module in one `app.json`. To bring each user's existing data across, a merge script
   copies each standalone app's `<id>_*` tables, `core_links` and `core_settings` into the unified database.
   This works because tables are prefixed and ids are random text. *Not written yet.*
4. **Later: switching modules on and off in Settings** instead of `app.json`. The registry already loads
   modules by id; what's missing is storing the choice and restarting the server. *Not built yet.*

Things a unified app will probably want, best added to the host when a second module needs them:

- **Ask across modules:** each module gives the AI context for a question, the way `search` gives results.
- **A shared people list:** Trailmix's speaker names and "You", plus mentions in notes.
- **A shared activity feed on Home.**

## 14. Why it's built this way

- **Python server + web UI in a WebKit window:** one codebase for the Mac app, a browser and a server install.
  Python is where the local AI and audio tooling is.
- **SQLite, no ORM:** one file, easy to back up, merge and inspect, and plain SQL is easy for people and agents to read.
- **One background worker:** heavy local models never compete for memory. Order is predictable.
- **Polling a change counter instead of websockets:** survives restarts and sleep, works through any proxy, costs
  almost nothing locally, and lets any module's change refresh any screen.
- **Hash routes, no router or state library:** less to learn and nothing to upgrade. A page is a component and
  its data is `useLive()`.
- **Random text ids and prefixed tables:** separate apps can merge without collisions.
- **No new dependency without a reason.** Each one is something every family app carries forever.

## 15. Gotchas

- **Swift:** build with the Command Line Tools only, so don't use `@State`, `@Entry` or `#Preview` (they're
  macros whose plugin ships only with Xcode). Use an `ObservableObject` with `@StateObject` instead.
- **CI's Swift is older than your Mac's:** avoid `BitwiseCopyable`, `AVCaptureDevice.wasDisconnectedNotification`,
  and `[weak self]` captured inside `Task {}`.
- **Signing:** builds are ad-hoc signed, so macOS asks again for any permissions (microphone…) after each update.
  A Developer ID (`SIGN_IDENTITY`) fixes that. Dangling symlinks in the bundle make `codesign --verify` fail.
- **Never write into the bundle:** `PYTHONDONTWRITEBYTECODE=1` is set and `.pyc` files are precompiled with
  unchecked hashes for this reason.
- **Tailwind:** editing `tailwind.config.js` needs a dev-server restart.
- **A heavy Python package with unused dependencies** (Trailmix's `mlx-whisper` pulls in 600 MB of torch) can be
  installed with `--no-deps` in a `scripts/bundle-<module>.sh`, listing what it really needs.
- **Two family apps on one port:** the Mac app checks that the server answering is its own (`/api/app` id)
  before using it, but give each app its own port anyway.
