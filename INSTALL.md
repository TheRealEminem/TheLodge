# Installing The Lodge on a Mac

The Lodge is a normal Mac app for Apple silicon (M1 or later), macOS 14 or newer. It keeps everything on your Mac.

## First launch

1. Open `The Lodge-<version>-arm64.dmg` and drag **The Lodge** onto **Applications**.
2. Open it from Applications. Because the app is signed without an Apple Developer ID (it is built for you, not
   sold), macOS will say it can't verify it. This is expected, and you only do this once per version:
   - **Right-click (or Control-click) the app, choose Open, then Open again**, or
   - open **System Settings, Privacy & Security**, scroll down to *"The Lodge" was blocked*, and press **Open Anyway**.
   (A copy you built yourself on this Mac doesn't carry the download flag and opens normally.)
3. A window opens, and a small A-frame icon appears in the menu bar. Closing the window leaves the app in the menu bar.
4. Go to **Settings** and add your AI keys (Claude, and Gemini if you want it for sorting and spreadsheet columns).
   They're typed in there, never into a file, and are kept only in your data folder.

## Where things live

- Your data: `~/Library/Application Support/The Lodge/` (readable only by you). **Back this folder up.** Deleting the app
  doesn't touch it. The menu bar icon has **Show Data Folder** and **Show Server Log**.
- To start fresh, quit the app and move that folder away.
- **Open at Login** is in the menu bar menu.

## Getting your people in from DynaCRM

Quit The Lodge, then (with the old project's database running):

```bash
.venv/bin/python scripts/import-dynacrm.py --data-dir "$HOME/Library/Application Support/The Lodge"
```

## Updating

Quit the app and replace it with the new one from a new disk image. Your data stays where it is. (Automatic updates
are off: the updater reads public GitHub releases, and this project is private.)

## If something's wrong

- **"Another app is using port 8791":** quit it, or change `port` in `app.json` and rebuild.
- **The window is blank or old after an update:** quit the app from the menu bar icon and open it again.
- The server log is at `~/Library/Application Support/The Lodge/logs/server.log`.

## Building it yourself

`scripts/build-app.sh` makes `dist-app/The Lodge.app`; add `--dmg` for the disk image. Pushing a tag like `v0.2.0` builds
and attaches the disk image to a GitHub release (`.github/workflows/release.yml`).
`scripts/check-app.py` runs behaviour checks on the built app (restarts, quitting, two copies).
