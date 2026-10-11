# Family starter

A working app to start every Trailmix-family app from: the shared host (server, database, settings,
background jobs, AI providers, search, sign-in, the web shell and the Mac app) plus two example modules,
**Notes** and **Tasks**, that work together without knowing about each other.

Every app built from this is a set of modules, so the apps can later become one app with each of them as an
add-on. Read **[ARCHITECTURE.md](ARCHITECTURE.md)** for how it fits together and the rules that keep it that
way, and **[DESIGN.md](DESIGN.md)** for how it looks.

## Try it

Needs Python 3.11+, Node 18+, and (for AI summaries) [Ollama](https://ollama.com) with a model, or an API key
for a cloud provider in Settings.

```bash
scripts/dev
```

Open http://localhost:5173. Write a note and press **Summarize**: its action items turn up in **Tasks**,
linked back to the note.

## Make your own app from it

1. Copy this folder and edit `app.json` (name, id, port, modules…).
2. Start your feature as a module:
   ```bash
   scripts/new-module journal "Journal"
   ```
3. Build it, following `modules/notes` as the reference.
4. Check everything (tests, types, build, style rules):
   ```bash
   scripts/check
   ```
5. Build the Mac app (`dist-app/<Name>.app`, and a disk image with `--dmg`):
   ```bash
   scripts/build-app.sh --dmg
   ```

## Prompt for an AI agent

> This app is built on the Trailmix family starter. Before changing anything, read ARCHITECTURE.md and
> DESIGN.md in full, then core/server/module.py, core/web/registry.ts and modules/notes (the reference
> module). Put new features in a module (scripts/new-module), follow the rules in ARCHITECTURE.md §3, never
> import one module from another (use events, contracts, links and search through the host), and run
> scripts/check before you finish.
