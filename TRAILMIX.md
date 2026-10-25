# Trailmix: a reference for the family apps

What Trailmix does, how it's built, and which of its conventions every Trailmix-family app should match, so that
The Lodge, Traverse and the apps after them stay compatible with Trailmix and with each other, and can share data
or become one app later.

Taken from Trailmix's code on 22 October 2026: version **0.16.0**, branch `gemini-transcription`, commit `c875507`.
The family's shared code (`~/Code/TrailmixFamily`) was at `ca89799`, which The Lodge and Traverse both pin.
Anything not built yet is marked **Proposed**.

**How this fits with the other guides.** `ARCHITECTURE.md` (the host and module contract) and `DESIGN.md` (the
look), beside this file, are the rules for family apps, and they win where this file and they disagree.
This file is the Trailmix side: what Trailmix has, where it already matches the family, where it doesn't yet, and what
an app has to keep the same so Trailmix can join it later. Traverse's `TRAILMIX-COMPARISON.md` (18 October) is an
older, line-by-line comparison; this one is newer and covers 0.15.1 to 0.16.0 too.

---

## 1. The compatibility contract, in fourteen rules

If a family app keeps these, Trailmix can talk to it now and merge with it later.

1. **Build on the family host.** New apps start from `TrailmixFamily` with `scripts/sync-family`, never from a copy
   of Trailmix's code. Trailmix is the odd one out (it predates the host) and will move onto it as a `meetings`
   module (§14).
2. **One process is the whole app:** a Python FastAPI server on `127.0.0.1:<port>` serves the API (`/api/…`) and
   the built web app (`/`). The Mac app only starts it, supervises it and shows it in a WebKit window.
3. **Your own port.** Trailmix has **8765** (and **8770** for its transcription worker). Family apps take one in
   8780–8799 and add it to the table in `ARCHITECTURE.md` §5. Never reuse one.
4. **Your own identity:** name, `id`, bundle ID, env prefix and data folder all come from `app.json`. Trailmix's
   are `Trailmix`, `local.trailmix.app`, `TRAILMIX_` and `~/Library/Application Support/Trailmix`. Don't pick
   anything starting with `TRAILMIX_` for your own env prefix; the family's own variables (`TRAILMIX_FAMILY`,
   `TRAILMIX_FAMILY_DIR`) already live there.
5. **SQLite, one file, plain SQL, no ORM.** Random text ids (`db.new_id()`), tables prefixed with the module id,
   things in other modules named by refs (`"<module>:<id>"`). Trailmix's meetings already carry a permanent `uid`
   for this.
6. **Schema changes only add.** Never edit or reorder a migration that shipped. "Go back" to an older version
   depends on it in both Trailmix and the family.
7. **The same AI settings, with the same names** (§6): one provider and one fallback for the whole app, chosen
   from `ollama | anthropic | openai | gemini | deepseek | custom`, with the same `<provider>_model` and
   `<provider>_api_key` names. Keys are write-only: never sent back to the page, only a hint (`…1234`).
8. **Local first.** It works offline. Cloud services are optional and chosen in Settings. Local models unload after
   use (`OLLAMA_KEEP_ALIVE=0`), and heavy local work waits until there's memory for it.
9. **Lockdown** (§8) means nothing leaves the computer: no stats, no update checks, no downloads, only AI that
   runs here. Every app has it (`core/server/lockdown.py`) and honours it in the same places: `ai.configured()`, the
   updater, Ollama downloads, and each module's own outward features, which ask `lockdown.blocked(what)` first.
10. **Money is never a surprise, and never in the way.** Every AI call is tallied (tokens as the provider reported them,
    dollars estimated at list price) and the running count sits a few clicks into Settings → AI → Usage. Nothing
    nags: only a job estimated over the owner's limit (`ai.warn_over`, $1 by default) shows its cost first, such as
    a big batch of research or redoing every meeting. Bulk runs still go a few items at a time.
11. **State lives in the database, and slow work is resumable.** A restart at any moment loses nothing, and the
    work picks up where it was.
12. **Nothing is written inside the app bundle at runtime** (it breaks the signature). Everything goes in the data folder.
13. **The same look:** Trailmix's tokens, fonts, Day and Dusk themes and components, which the family kit was
    taken from (`DESIGN.md`). Each app changes only its name, mark, scene and copy.
14. **The same release path:** a version tag builds the Mac app, a smoke test runs, it goes out as a beta
    (pre-release), and it reaches everyone after 3 days unless someone reports a blocker. The updater offers beta
    updates, Skip this version and Go back.
15. **Backups roll over.** A copy each hour if something changed, thinned like Time Machine's to the newest in each of
    the last 3 hours, 9 days and 4 weeks; a copy before an update and before a restore that survive roll-over; never two
    copies of the same data; at most 20 files; and a simple menu of four choices (the newest, an hour ago, yesterday,
    last week) with Advanced collapsed. The full rule is in `ARCHITECTURE.md` §7. A backup list that grows is a bug.

---

## 2. What Trailmix is

A local-first meeting recorder, transcriber and note-taker for Apple silicon Macs (macOS 14.2+). The menu bar app
records your microphone and the call app's audio as separate tracks, so the transcript knows **You** from **Them**.
A Whisper model transcribes while you talk, and within about a minute of stopping the notes follow: a summary,
decisions, action items, a title, tags and a workspace, written by a local model through Ollama or by a cloud AI you
choose. Meetings stay on your Mac unless you send them somewhere. Licence: AGPL-3.0.

**The family today**

| App | Folder | What it is | Port | Bundle ID | Env prefix | Releases |
| --- | --- | --- | --- | --- | --- | --- |
| Trailmix | `~/Code/Trailmix` | meetings (its own architecture) | 8765 (+8770 worker) | `local.trailmix.app` | `TRAILMIX_` | `TheRealEminem/trailmix` (public) |
| The Lodge | `~/Code/TheLodge` | people (`crm`) + `tasks` | 8791 | `com.thelodge.app` | `LODGE_` | `TheRealEminem/TheLodge` |
| Traverse | `~/Code/Traverse` | work (`muster`, `tasks`, `plane`, `inbox`) | 8793 | `com.traverse.app` | `TRAVERSE_` | none yet |
| Starter | `TrailmixFamily` template | `notes` + `tasks` reference modules | 8790 | `local.family.starter` | `STARTER_` | — |

---

## 3. Frameworks and tools

| Layer | Trailmix uses | Family host uses | Notes |
| --- | --- | --- | --- |
| Server | Python 3.11+ (3.14 bundled in the app), **FastAPI + uvicorn**, pydantic, httpx, psutil | the same | One process, one port. |
| Database | **SQLite** via the standard `sqlite3` module, short connection per operation, FTS5 for search | the same, plus WAL and per-module migrations | No ORM anywhere. |
| Speech | **mlx-whisper** (`whisper-large-v3-turbo`, `whisper-base` for drafts) on Apple silicon; any OpenAI-compatible endpoint; Google Gemini (`gemini-3.5-transcribe`) | none (Trailmix-only) | Silero VAD (weights in `backend/assets`). mlx-whisper is installed `--no-deps` (it lists 600 MB of torch it never uses). |
| Audio | ffmpeg (static build bundled), Opus 48 kbps files | none | Trailmix-only. |
| AI text | Ollama, Claude, OpenAI, Gemini (native, streaming, Batch API), DeepSeek, any OpenAI-compatible | the same providers (Gemini through the OpenAI-compatible route), plus structured output | §6. |
| Web | **React 18 + TypeScript 5 + Vite 5 + Tailwind 3.4**, `lucide-react` icons, `react-markdown` + `remark-gfm`, fonts from `@fontsource-variable` (Geist, Fraunces, Geist Mono) | the same | No router or state library: hash routes and plain hooks. |
| Mac app | **Swift package** built with the **Command Line Tools only** (no Xcode): AppKit + SwiftUI menu bar app, `WKWebView` window, Core Audio process taps for the call's audio | the same approach (`mac/`) | No `@State`, `@Entry` or `#Preview` (§12). |
| Server install | Docker (`python:3.12-slim` + a `node:22-alpine` web build) | the same | Sign-in turns on with an access token. |
| CI | GitHub Actions: tests on push, `macos-15` build on tag, smoke test, beta publish, daily auto-promote | the same shape | §13. |
| Stats | PostHog (anonymous, opt-out) | none | §8. |

**Rule for new dependencies (family-wide):** none without a reason. Each one is something every family app carries forever.

---

## 4. How it runs

```
Trailmix.app (Swift, menu bar: recorder, hotkeys, updater)
  ├─ starts and supervises ─┐   TRAILMIX_DATA_DIR, TRAILMIX_UI_DIR, TRAILMIX_PARENT_PID
  ├─ window (WKWebView) ────┤   bridge: window.webkit.messageHandlers.trailmix
  └─ checks in every ~1 s ──┤   POST /api/recorder/check-in → {commands: [...]}
                            ▼
        uvicorn main:app on 127.0.0.1:8765
          ├─ /api/…             116 routes in backend/main.py, plus one audio WebSocket
          ├─ /                  the built web app (frontend/dist)
          └─ data folder        ~/Library/Application Support/Trailmix (or backend/data from source, /data in Docker)
```

- **The server stops when the app dies.** It watches `TRAILMIX_PARENT_PID` and exits if its parent goes, so it never
  lingers on the port. If a server is already answering on 8765 (a source install), the app uses that one.
- **From source:** `./trailmix` (start and open), `stop | restart | status | logs`, `autostart on`, `dev` (backend
  with reload + Vite on :5173), `worker` (transcription worker for a server install, port 8770), `app` (builds
  "Trailmix Dev.app" with a DEV badge), `helper` (builds the menu bar recorder on its own).
- **Server install:** `docker compose up -d` with `TRAILMIX_ACCESS_TOKEN` set; the port is bound to localhost on
  purpose, with Tailscale or an HTTPS proxy in front. Transcription then goes to a Mac running `./trailmix worker`
  or a cloud API (`docs/self-hosting.md`).
- **Background loops** run in the server (the family host does the same work as scheduled jobs):

| Loop | Every | What it does | Switch |
| --- | --- | --- | --- |
| sweep | 6 h | deletes expired audio; refreshes model ranks and recording laws from the Trailmix site | — |
| stats | 1 h | sends the once-a-day anonymous summary | Lockdown, Settings |
| warm | 15 s | keeps the live speech model loaded when there's memory (or a call app opens audio) | `TRAILMIX_WARM=0` |
| live notes | 10 s | notes during a recording, every ten new minutes of transcript | `live_notes` |
| batch | 60 s | checks Google Batch jobs and puts finished answers in | — |
| sources | 15 min | new meetings from Granola, Fathom, Fireflies | `TRAILMIX_SYNC=0` |
| folders | 60 s | new recordings and transcripts in watched folders | `TRAILMIX_SYNC=0` |

**Testing on a copy of real data:** turn off everything that reaches outside the copy first: `auto_export` off,
`exported_paths` cleared, `TRAILMIX_POSTHOG_HOST` pointed at a dead address, `TRAILMIX_WARM=0`, `TRAILMIX_SYNC=0`. The
same applies to any family app with side effects (exports, syncs, stats).

---

## 5. Data and storage

**The data folder** (`TRAILMIX_DATA_DIR`):

```
trailmix.db                 SQLite: meetings, tasks, workspaces, settings, history, versions, usage…
audio/<meeting id>/         mic.pcm + system.pcm while recording (raw 16 kHz int16, flushed every ~250 ms)
                            → mic.ogg + system.ogg (Opus 48 kbps) once stopped; .pcm deleted only after the .ogg is verified
backups/                    trailmix-<old>-before-<new>.db, made the first time a new version starts (newest 3 kept)
last-version                which version last ran, for that backup
logs/server.log
```

Exports go to `~/Documents/Trailmix` by default, one folder per meeting. Speech models (about 1.7 GB) are downloaded
on first run with progress, never bundled.

**Tables** (`backend/database.py`):

| Table | Holds | Notes |
| --- | --- | --- |
| `meetings` | one row per meeting: title, times, status, transcript, summary, and ~40 more columns | `id` INTEGER autoincrement, plus a permanent random `uid` (kept in exports, so re-imports are recognised). Nested data is JSON in `*_json` text columns. |
| `action_items` | tasks: `meeting_id`, `position`, `text`, `done` | Cascade-deleted with the meeting. |
| `workspaces` | `name` (unique, case-insensitive), `color` (`forest`, `sky`, `sun`, `trail`, `ink`), `about`, `position` | A meeting has one or none (`meetings.workspace_id`). |
| `settings` | `key` → JSON `value` | Flat keys (§6). |
| `history` | every change to a meeting: `field`, `old_value`, `new_value`, `why`, `at` | Written in the same transaction as the change. Deleted with the meeting (privacy). |
| `transcript_versions` | every transcript ever made of a meeting, with engine, model, timing, and which one is applied | For comparing and switching. |
| `usage` | what paid engines were asked to do and the estimated cost | Kept after a meeting is deleted (no meeting content in it). |
| `batch_jobs` | work sent to Google's Batch API until its answers are used | |
| `source_sync`, `watched_files` | where each connection's sync stands; files seen in watched folders | |
| `meetings_fts` | FTS5 over title, transcript, summary, tags (`porter unicode61`) | Kept in sync by `update_meeting`. |

**Migrations:** new columns are listed in `_ADDED_COLUMNS` and added on startup; tables use `CREATE TABLE IF NOT
EXISTS`. Additive only, but not counted per module the way the family's are.

**Meeting status** (one state machine per row):
`recording → queued → [ready_transcribe] → [waiting_confirm] → transcribing → [ready_summarize] → [waiting_confirm] → summarizing → done | error`.
`ready_*` waits for you to press the button (auto mode off, or an import that asks which AI to use); `waiting_confirm`
is the memory gate, with "Proceed anyway".

**The export format** (`backend/archive.py`), `meeting.json` in each export folder. Importing it rebuilds the meeting
exactly, so it is also the format for moving a meeting between apps:

```json
{"format": "trailmix-meeting", "version": 1, "uid": "…", "title": "…", "title_auto": false,
 "created_at": "2026-10-20T15:00:00.000Z", "duration_sec": 1830, "source": "trailmix", "has_system": true,
 "speakers": {"You": "Sam", "Them": "Dana"}, "summary": "## Overview…", "summary_provider": "…", "summary_model": "…",
 "transcribed_with": "whisper-large-v3-turbo, while recording",
 "tasks": [{"text": "Dana: send the deck (Friday)", "done": false}],
 "bookmarks": [{"t": 312.5, "note": "…"}], "my_notes": [{"t": null, "text": "…"}], "qa": [{"q": "…", "a": "…"}],
 "transcript": [{"start": 0.0, "end": 4.2, "speaker": "You", "text": "…"}],
 "audio": {"recording": "Recording.ogg", "tracks": {"mic": "Tracks/You.ogg", "system": "Tracks/Them.ogg"}},
 "app_version": "0.16.0"}
```

Times are ISO 8601 UTC with milliseconds and a `Z`. Notes are Markdown with `##` sections. Action items in notes
are written `- [ ] <person>: <task> (<due date, if one was said>)`, with `Unassigned` when nobody took it on.

---

## 6. Settings

`backend/settings.py`: one `DEFAULTS` dict, stored as JSON in the `settings` table.

- **Preset from the environment** as `TRAILMIX_<KEY>` (`TRAILMIX_TRANSCRIBE_ENGINE=remote`). Provider keys also come
  from `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`. A value saved in the app wins.
- **Validated on save:** the type must match the default's, and `CHOICES` lists the allowed values. URLs must start
  with `http://` or `https://` and lose their trailing slash.
- **Secrets** are the keys ending in `_api_key`. The page gets `""` plus `secret_hints` (`…1234` or `set`).

| Group | Settings |
| --- | --- |
| Flow | `auto_transcribe`, `auto_summarize`, `ask_before_ai`, `auto_title`, `auto_workspace`, `ask_questions`, `duplicates` (`merge`, `ask`, `keep`) |
| You | `your_name`, `vocabulary` (names and terms you confirmed), `current_workspace` |
| Notes | `summary_provider`, `summary_fallback`, `summary_template`, `custom_template` |
| AI providers | `ollama_url`, `ollama_model`, `anthropic_model`, `anthropic_api_key`, `openai_model`, `openai_api_key`, `gemini_model`, `gemini_api_key`, `deepseek_model`, `deepseek_api_key`, `custom_name`, `custom_base_url`, `custom_model`, `custom_api_key` |
| Transcription | `transcribe_engine` (`local`, `remote`, `gemini`), `transcribe_url`, `transcribe_api_key`, `transcribe_model`, `transcribe_live_model`, `gemini_transcribe_model`, `gemini_mix_tracks`, `live_final`, `live_notes` (`auto`, `on`, `off`) |
| Recordings | `audio_retention_days` (30; `0` = once transcribed, `-1` = forever), `legal_region`, `legal_seen` |
| Privacy | `lockdown`, `share_stats`, `stats_notice_seen`, `install_id`, `stats_last_daily` |
| Import | `granola_api_key`, `fathom_api_key`, `fireflies_api_key`, `auto_import`, `auto_import_keep_notes`, `watch_folders` |
| Export | `auto_export`, `export_dir`, `export_formats` (`pdf`, `docx`, `odt`, `md`, `txt`), `export_summary`, `export_transcript`, `export_separate_files`, `export_audio` |
| App | `whats_new_seen` |

**How these line up with the family host.** The family namespaces its settings (`ai.*`, `core.*`, `<module>.*`) and
shares `ai.*`, `core.your_name` and `core.appearance` between family apps through `family.db`. Trailmix's AI names
were the source for the family's, so the mapping is nearly one to one:

| Trailmix | Family | |
| --- | --- | --- |
| `summary_provider` | `ai.provider` | renamed |
| `summary_fallback` | `ai.fallback` | renamed |
| `ollama_url`, `ollama_model`, `<provider>_model`, `<provider>_api_key`, `custom_*` | `ai.<same name>` | same names, same defaults (`claude-opus-5-5`, `gpt-5-mini`, `gemini-flash-latest`, `deepseek-chat`) |
| `your_name` | `core.your_name` | |
| theme in the browser's `localStorage` (`trailmix.theme` = `system`, `light`, `dusk`) | `core.appearance` | Trailmix keeps it per browser, not as a setting |
| everything else | `meetings.<name>` | **Proposed**, for the port |
| `lockdown` | `core.lockdown` | shared by the family apps on a Mac, like the AI settings |

**Keep these names.** If a family app adds a provider, a model setting or a key, use the same pattern
(`<provider>_model`, `<provider>_api_key`) so both sides can read it.

---

## 7. AI

**Providers** (`backend/llm_engine.py`), one call for all of them: `generate(provider, cfg, prompt, system) -> text`.

| id | Label | Kind | Notes |
| --- | --- | --- | --- |
| `ollama` | Ollama | local | `keep_alive` 0 (unload right after), `num_ctx` 16384; installable from setup (`/api/ollama/install`, `/pull`) |
| `anthropic` | Claude (Anthropic) | cloud | streaming; server-side refusal fallback on the newest Claude models |
| `openai` | OpenAI | cloud | |
| `gemini` | Google Gemini | cloud | native API with streaming and token counts; half-price Batch API for bulk notes |
| `deepseek` | DeepSeek | cloud | OpenAI-compatible |
| `custom` | your name for it | custom | any OpenAI-compatible server; counts as local when its address is this computer |

How it's used:

- **A chain:** the chosen provider, then the fallback. Errors are plain sentences (`LLMError`) for the screen.
- **Who wrote it is shown and stored** with the result (`summary_provider`, `summary_model`, `tags_model`…). That is
  what makes "Better models" possible.
- **Context sizing:** each provider has a token budget (Ollama 16k, unknown OpenAI-compatible 16k, DeepSeek 60k,
  others 120k), at about 3 characters a token. Long meetings are summarized in parts first.
- **The memory gate** (`backend/resources.py`): a model that runs on this Mac waits until there's free memory for it
  plus 2 GB, or macOS can swap without it being dire. Nothing heavy runs locally during a recording.
- **Model ranks** (`backend/model_ranks.py`): every notes and speech model scored 0–100, shipped in
  `backend/assets/model-ranks.json` and refreshed daily from `https://therealeminem.github.io/trailmix/model-ranks.json`.
  An unlisted local model is judged by its size. A model must be 5 points better before Trailmix offers to redo work.
- **Pricing** (`backend/pricing.py`, as of 2026-10-12): published per-minute rates, a `usage` table, and an estimate
  on every paid button. A two-track meeting costs twice its length unless the tracks are mixed (`gemini_mix_tracks`).
- **Small local models are "Basic and private".** About 3B models get the simple jobs (summarize, explain, direct
  questions). Judgement-heavy ones (what was decided, classifying a whole meeting) are switched off with a plain note
  saying they need a cloud AI or a bigger model.
- **Templates** (`backend/templates.py`): General, 1:1, Standup, Interview, Sales call, or your own. Each ends with
  the `## Action Items` section in the format in §5.

The family host has the same providers and fallback (`core/server/ai.py`), plus structured output, which Trailmix
lacks (it parses Markdown). It doesn't have Trailmix's native Gemini route, Batch API, pricing, ranks or the
pre-flight "choose which AI" sheet yet.

---

## 8. Privacy and trust: the parts every app should share

| Feature | What it does in Trailmix | Where |
| --- | --- | --- |
| **Lockdown** | Nothing leaves the computer: no stats, no automatic update checks, no model downloads or rank updates, no syncing from Granola, Fathom or Fireflies, and only AI and transcription that run here. The menu bar app gets its copy through the check-in. | `settings.locked()`, `tests/test_lockdown.py` |
| **Write-only secrets** | Keys are never sent back to the page or written to logs; problem reports strip them. | `settings.public()` |
| **Anonymous stats** | PostHog, US region, IP addresses discarded, a random install ID (a new one each time stats are turned back on). Nothing is sent until you've seen the notice. Sent: version, computer (rounded), which features are on, meeting length and processing time, error types (never messages). Never: anything from a meeting, names, paths. Settings → Privacy shows the latest events as they went out. | `backend/telemetry.py`, `docs/privacy.html` |
| **Report a problem** | From any screen, as a GitHub issue you check and send yourself. Personal details are removed in five layers: the page sends placeholders for its private parts, then patterns (keys, emails, phones, addresses, links, IPs, the macOS user name), then names Trailmix knows, then your **local** AI rewrites free text, then the patterns and names again. | `backend/feedback.py`, `ReportButton.tsx` |
| **Recording laws** | A short entry per US state and country in setup and Settings → Privacy. Information only: an entry can suggest a shorter retention, and you choose whether to apply it. Shipped in `assets/`, refreshed daily from the Trailmix site. | `backend/recording_laws.py` |
| **Audio retention** | 30 days by default (7, until transcribed, or forever), "Keep forever" per meeting, "Delete audio now". | `backend/audio_store.py` |
| **A receipt for every change** | `history` records what changed, from what, to what, when and why. | `backend/database.py` |
| **Usage, not nagging** | Every paid call is tallied (Settings → AI → Usage); only a job estimated over a limit (default $1) shows its cost first; bulk runs go a few at a time (3 by default). | `backend/pricing.py` |
| **Sign-in for server installs** | Off locally. With `TRAILMIX_ACCESS_TOKEN` set, every API call (except `/api/auth`, `/api/login`, `/api/logout`), the WebSocket and audio playback need it: an HttpOnly `trailmix_session` cookie (HMAC of the token, 30 days, `SameSite=Strict`), or `Authorization: Bearer <token>`. Wrong guesses wait 0.6 s. | `backend/auth.py` |

**For a family app:** don't reuse Trailmix's PostHog key or privacy page; each app that sends stats needs its own
project and its own policy. The "built-in copy, refreshed daily from the site, blocked by Lockdown" pattern
(model ranks, recording laws) is the one to copy for any data that changes faster than releases.

---

## 9. Features, by area

**Recording.** Both sides of a call as separate tracks (mic, and the call app's audio through Core Audio process
taps: Zoom, Teams, Slack, FaceTime, iPhone calls on the Mac), with no screen-share picker or virtual audio device.
Global hotkeys ⌃⌥⌘R (start/stop) and ⌃⌥⌘M (flag a moment), changeable. Mic picker, one app or all apps or none
(in person), input levels for You and Them, a sound check that walks through the macOS permissions, call reminders.
Audio is written to disk as it arrives (a crash loses nothing) and interrupted meetings are finished on the next start.
In a browser it falls back to `getDisplayMedia` (tab audio only).

**Transcription.** Local Whisper on MLX: with 16 GB or more the accurate model transcribes *while* recording, in
chunks of at most 5 s cut at pauses, each given the previous words and your vocabulary, so the transcript is ready
about a second after Stop; with less, a small model drafts live and the accurate one runs after. Silero VAD,
hallucination and echo clean-up. Or an OpenAI-compatible endpoint, or Google Gemini with speaker labels (Speaker 1,
2… on their side; your mic stays You) and live captions. Economy quality (Flash-Lite) and half-price Batch.
**Versions:** every transcript is kept; re-transcribe with any engine, compare word by word, switch with one click.

**Notes.** Templates, long meetings in parts, an automatic title, action items collected in **Tasks**, flagged
moments in their own section, your own typed notes kept in. **Notes during the meeting** (every ten minutes) and
**Catch me up** while recording: "What did I miss?", "Explain that", "What's been decided?" or your own question,
with the cost on the button.

**Organizing.** **Workspaces** (a job, a committee, personal; ⌃1…⌃9 to switch): meetings, tasks, search and Ask
follow the one you're in. New meetings are tagged by topic and sorted into a workspace from their notes (a workspace
named in the title wins; the AI must call the fit good; meetings you placed by hand are its examples and are never
moved). **Quick questions** when the AI isn't sure (who was on the call, a name one letter off, a likely
mishearing); answers fix the meeting and join the **vocabulary**. **Better models** offers to redo work a clearly
better model would do better.

**Finding things.** Full-text search; **Ask** one meeting, all of them or one workspace, with answers linking to
their sources; click a transcript line to play from there.

**Import and connections.** One Import page: **Connected** (one list of automatic sources plus a Connect picker:
Granola, Fathom, Fireflies, watched folders) and **Import once** (one drop zone for recordings, transcript files
such as WebVTT, SRT, Otter TXT and DOCX, pasted text and Trailmix exports). **Duplicates:** the same meeting from
Trailmix and from another note taker merges into one, keeping Trailmix's recording and preferring the other's
transcript and notes (can be undone; or `ask`, or `keep` both).

**Export.** A folder per meeting: notes and transcript as PDF, Word, OpenDocument, Markdown or text,
`meeting.json`, and optionally the recording (hard-linked, no extra space). Automatic or by hand; kept current when
the meeting changes.

**The app.** Auto-updates with beta updates, Skip and Go back (§12). What's new after an update. Day and Dusk
themes. macOS spell checking in text fields. A first-run checklist: your Mac, your name, recording laws, a sound
check, the transcription engine, speech models, summaries, workspaces, and your first meeting.

---

## 10. The API, for an app that wants Trailmix's data today

Local installs need no sign-in. Base URL `http://127.0.0.1:8765/api`. All JSON. Errors are
`{"detail": "<a sentence for the screen>"}` with a proper status code.

| What | Route | Notes |
| --- | --- | --- |
| Is it Trailmix, what version, what's set up | `GET /health` | `version`, `build` (`app` or `source`), providers and whether each is ready, transcription engine, `recording`, `auth` |
| All meetings | `GET /meetings` | `id, title, created_at, duration_sec, status, workspace_id, ask_first`. **No `uid` yet.** |
| One meeting | `GET /meetings/{id}` | everything, including `uid`, `summary`, `segments`, `tasks`, `tags`, `speaker_names`, `bookmarks`, `workspace_id` |
| Search | `GET /search?q=` | FTS over titles, transcripts, notes and tags |
| Tasks | `GET /tasks`, `PATCH /tasks/{id}` | `id, text, done, meeting_id, meeting_title, meeting_created_at, workspace_id`; tick with `{"done": true}` |
| Workspaces | `GET /workspaces` | `id, name, color, about, position, meetings, template` |
| Ask across meetings | `POST /ask` | answers with sources |
| Export everything | `POST /export/all`, `GET /export/all` | writes the export folders |
| Import a Trailmix export | `POST /import/trailmix` | a `meeting.json` (and audio) |
| Import a transcript | `POST /import/text` | `{"text", "title", "date"}` |
| Settings | `GET /settings`, `PUT /settings` | secrets blanked; a `PUT` takes only the keys you change |

**To read Trailmix's meetings from another app:** list `/meetings`, fetch `/meetings/{id}` for each one that's
`done`, and dedupe on `uid`, never on `id` (ids are per database). Adding `uid` to the list query is a one-line change
in `database.list_meetings` that would save the extra fetch (**Proposed**). Don't write to Trailmix's database
directly; go through the API or `meeting.json`.

**The native recorder's protocol** (any app with a native side can copy it): the Mac app posts
`/api/recorder/check-in` about once a second with what it would record (mic, source, permissions, shortcuts, update
state, `call_app`, its copy of `lockdown`) and gets back `{"commands": [...]}` (`start`, `lockdown`, `no-lockdown`…).
The page asks for a recording with `POST /api/recorder/start`; the recorder streams audio to
`WS /api/meetings/{id}/stream`. Nothing is pushed from the server to the native side.

---

## 11. Screens and the web app

- **Look:** the tokens are CSS variables in `frontend/src/index.css` (`--bg`, `--surface`, `--text-primary`,
  `--forest`, `--trail-orange`, `--yellow`, `--sky`, `--berry`, `--fs-*`, `--radius-*`, `--shadow-*`), exposed to
  Tailwind in `tailwind.config.js`. Components never contain hex values. `DESIGN.md` has them
  all, with what each colour means: forest for the main action, trail orange for the one live thing (recording), sun
  yellow for "this needs you", sky and berry for You and Them.
- **Themes:** Day and Dusk, following macOS unless you pick one.
- **Routes:** the URL hash. Trailmix uses `#meeting-12` and `#<page>`; the family uses `#/<module>/<id>`. Trailmix
  moves to the family form in the port.
- **Fresh screens by polling**, not websockets (the audio stream is the one WebSocket). The family's `useLive()`
  polls a change counter every 2 s; Trailmix polls per screen (`/api/live`, the import page, catch-up).
- **The Mac window bridge:** Trailmix's handler is `window.webkit.messageHandlers.trailmix`, taking `quit` and
  `reveal:<path>`. The family's is `…messageHandlers.app`. A page must work without either (a browser or a server
  install), so check that the bridge exists before using it.
- **One general shape, not a panel per integration.** When a page grows a section per method (Granola, folders,
  files…), make it one list plus a picker instead. Trailmix's Import page is the example.
- **Voice:** plain, warm, short. Hints say the consequence ("Off: …"). Errors say what to do next.

---

## 12. The Mac app

- **Bundle:** `Trailmix.app` with the Swift menu bar app as the main executable, and in `Resources/`: `python`
  (python-build-standalone, checksum-pinned), `backend`, `ui` (the Vite build) and `bin/ffmpeg`. Minimum macOS 14.2.
  `NSMicrophoneUsageDescription` and `NSAudioCaptureUsageDescription` are set. `.pyc` files are precompiled with
  unchecked hashes and `PYTHONDONTWRITEBYTECODE` is set, because nothing may be written into the bundle.
- **Disk image:** `Trailmix-<version>-arm64.dmg` plus `Trailmix-<version>-arm64.dmg.sha256`. The family uses the
  same naming (`<Name>-<version>-arm64.dmg`).
- **Signing:** ad-hoc for now, so macOS asks again for microphone and audio permission after each update.
  `TRAILMIX_SIGN_IDENTITY` switches to a Developer ID and the hardened runtime (untested).
- **Updater** (`helper/Sources/TrailmixHelper/Updater.swift`): reads GitHub releases at launch and every few hours;
  **Beta updates** also offer pre-releases; **Skip this version**; **Go back** to the version before; checks the
  SHA-256 and that the new app has the same bundle ID and a valid signature; **never mid-recording**; no automatic
  checks in Lockdown. Tests point it elsewhere with `TRAILMIX_UPDATE_URL` and `TRAILMIX_RELEASES_URL`.
- **Swift with the Command Line Tools only:** no `@State`, `@Entry` or `#Preview` (their macro plugin ships only with
  Xcode); keep view state in an `ObservableObject` held by `@StateObject`. CI's Swift is older than the dev Mac's,
  so avoid `BitwiseCopyable`, `AVCaptureDevice.wasDisconnectedNotification`, and `[weak self]` inside `Task {}`.
  Dangling symlinks in the bundle make `codesign --verify` fail.
- **Self-tests without permissions:** `--self-test <server> <mic.wav> [<them.wav>]`, `--window-test <url> <png>`,
  `--capture-test`, `--snapshot <dir>`, `--list-audio`.
- **Try a build without touching real data:** `env -i HOME=… PATH=/usr/bin:/bin TRAILMIX_DATA_DIR=<tmp>
  TRAILMIX_SERVER_URL=http://127.0.0.1:<spare port> TRAILMIX_NO_OPEN=1 TRAILMIX_PREFETCH=0 dist/Trailmix.app/Contents/MacOS/Trailmix`.

---

## 13. Building, testing, releasing

| | Trailmix | Family apps |
| --- | --- | --- |
| Version | `VERSION` file; a tag must match | the same |
| Tests | `python -m pytest backend/tests` (297 tests), `tsc --noEmit && npm run build` | `scripts/check` (pytest, tsc, build, style rules, family drift) |
| Before tagging | `scripts/preflight.sh`: tests, web build, app build, fresh-install smoke test, about 5 minutes on this Mac | `scripts/check`, `scripts/install-app.sh` |
| Build | `scripts/build-app.sh [--dmg]` → `dist/` | `scripts/build-app.sh [--dmg]` → `dist-app/` |
| On a `vX.Y.Z` tag | `release.yml` on `macos-15`: build, smoke test as a fresh install **and** as an update from the current release by its own updater, then publish as a **pre-release** | the same flow, with the updater's checks |
| Everyone gets it | `promote-beta.yml` daily at 16:00 UTC: after 3 days, unless an open issue titled `[Beta X.Y.Z] [blocks me]` exists; `scripts/promote.sh vX.Y.Z` by hand | `promote.yml`: after 3 days, unless an open issue is labelled `blocks release` |
| Public site | GitHub Pages from `docs/` on `main`: download page, privacy policy, `model-ranks.json`, `recording-laws.json` (installed apps fetch these) | — |

**Two habits worth keeping everywhere:** a fix isn't done until it's been seen working in the installed app (or the
smoke test covers it), because unit tests and browser checks couldn't see the two worst Trailmix regressions; and a
beta is only promoted with the owner's OK, which the 3-day window now stands for. Pushing `main` on Trailmix changes
the public site.

---

## 14. Trailmix and the family host: where they differ today

So other apps copy the family's way, not Trailmix's, where they differ.

| Area | Trailmix today | Family host | Who should move |
| --- | --- | --- | --- |
| Ids | INTEGER autoincrement, plus `uid` on meetings | random text ids everywhere | Trailmix, in the port (key on `uid`) |
| Tables | `meetings`, `action_items`, `workspaces`… | prefixed `<module>_*` | Trailmix (`meetings_*`) |
| Migrations | `_ADDED_COLUMNS`, additive | counted steps per module, append-only | Trailmix |
| Settings | flat names | namespaced `ai.*`, `core.*`, `<module>.*`; secrets also end in `_token`, `_secret` | Trailmix (mapping in §6) |
| Shared keys between apps | not joined: Trailmix has its own AI keys | `family.db`: AI settings, your name, appearance | Trailmix (**Proposed**: join the family link for `ai.*` and `your_name`, even before the port) |
| Background work | a state machine per meeting on one thread, plus seven loops | `jobs.enqueue` with `approve=`, `jobs.Wait`, lanes and a scheduler | Trailmix |
| Action items | its own `action_items` table and Tasks page | `actions.found` contract → the `tasks` module | Trailmix (publish `actions.found` with `source_ref` `meetings:<uid>`) |
| Search | one FTS table | `Module.search` merged across modules | Trailmix |
| Routes | `#meeting-12` | `#/meetings/<uid>` | Trailmix |
| Window bridge | `messageHandlers.trailmix` | `messageHandlers.app` | Trailmix |
| Database backups | once per new version, newest 3, no restore screen | hourly if changed, thinned to 3 hours, 9 days and 4 weeks (at most 20 files); copies before an update and a restore; "Back up now"; restore from four choices | Family (`core/server/backup.py`, rule 15) |
| Release blocker | issue title `[Beta X.Y.Z] [blocks me]` | issue label `blocks release` | pick one family-wide (**Proposed**: the label, plus the title form for reports made from the app) |
| Lockdown | yes | yes | Family (`core.lockdown`, gated in `ai.configured()` and the updater) |
| Paid-AI pricing and usage | yes | no | Family, when a second module spends money |
| Structured AI output | no (parses Markdown) | yes | Trailmix, when it moves |
| Anonymous stats, problem reports | yes | no | Family, later, with a per-app key and privacy page |
| Port | 8765 | 8780–8799 | stays: installed apps and the worker know 8765 |
| Minimum macOS | 14.2 (Core Audio process taps) and mic/audio usage strings | 14.0, none | the family, as an option for apps that record |
| WAL journal | not set | on | Trailmix |

**The plan for Trailmix** (`ARCHITECTURE.md` §13, and Traverse's comparison): keep Trailmix its own app for now,
integrate over its local API (§10), move the family-worthy pieces into the family first (Lockdown, pricing and
usage), and port Trailmix into a `meetings` module later, migration first, released as a beta. In the port, these
must stay the same or installed copies can't update: the bundle ID `local.trailmix.app`, the name "Trailmix" (its data
folder), the `trailmix.db` file name, the DMG names, and the `TheRealEminem/trailmix` release repo. Audio moves from
`audio/<id>/` to `meetings/<uid>/`, copied rather than moved, and the old tables are kept so Go back still opens.

**What a family app can do now to make that easy:**

- Name people the way the family's people directory does, and treat Trailmix's speakers (`You`, `Them`, or real
  names from `speaker_names`) as plain names with no ref until a `meetings` module exists.
- If you link to a Trailmix meeting, store its `uid` (as `meetings:<uid>` with the title beside it), never its integer id.
- Accept `meeting.json` (format `trailmix-meeting`, version 1) if your app ever imports meetings.
- Keep action items in the `- [ ] <person>: <task> (<due>)` form wherever AI writes them, so they parse the same in both.
- Use the same provider ids and setting names for AI, and the same Lockdown meaning, so a shared Settings → AI works for all.

---

## 15. Product rules we've settled on

These came from using Trailmix, and hold for every family app:

- **Local and private by default; cloud only when you choose it,** and say which AI did each piece of work.
- **Show the cost before spending money.** Test on a few items, not the whole library.
- **Nothing you made is lost:** history for every change, versions instead of overwrites, backups before migrations.
- **Ask when unsure, briefly,** and learn from the answer (Quick questions, vocabulary).
- **One general shape over a stack of special cases** (one list plus a picker for connections).
- **Small local models get the basic features;** say plainly what needs a cloud AI or a bigger model.
- **Prefer the better source when two apps have the same thing** (Granola's notes over Trailmix's own, keeping
  Trailmix's audio), and merge instead of duplicating.
- **Tests only touch copies,** with every outward side effect switched off first.
- **Never commit a key.** Keys come from Settings or the environment, never from files in a repository.

---

## 16. Prompt for an AI agent working on a family app

> This app is part of the Trailmix family and must stay compatible with Trailmix and mergeable with the other family
> apps. Before changing anything, read `TRAILMIX.md`, then `ARCHITECTURE.md` and `DESIGN.md` (all three come from
> `~/Code/TrailmixFamily`, and the last two win where they disagree with the first). Build on the family host with
> `scripts/sync-family`; never copy code from `~/Code/Trailmix`. Keep the compatibility contract in §1 of the
> reference: your own port and env prefix, random text ids and prefixed tables, append-only migrations, the same AI
> provider ids and setting names, write-only keys, Lockdown, costs shown before paid AI, nothing written into the app
> bundle, the family's tokens and components, and the beta-first release path. To use Trailmix's data, go through its
> local API at `http://127.0.0.1:8765/api` or `meeting.json`, and key everything on the meeting's `uid`. Run
> `scripts/check` before you finish, and see a change working in the installed app before calling it done.
