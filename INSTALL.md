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

## Granola and calendars

Both are optional and live in Settings, under People. Pasted keys and addresses are saved on this Mac like your AI keys.

- **Granola:** in the Granola app, Settings, Connectors, API keys, make a key and paste it in. It needs a Granola
  Business or Enterprise plan. New meetings are picked up every 15 minutes: Granola's summary and transcript are read,
  the invitees are matched to your people by email, and the meeting is added (or waits in the Inbox, if you turn
  automatic adding off). Put your own email on your own profile so The Lodge knows which attendee is you.
- **Calendar:** in Google Calendar, Settings for the calendar, Integrate calendar, copy the "Secret address in iCal
  format" and paste it in. Meetings from the last week and the next two with people you already know are put on your
  book, so a Granola note taken later joins the same meeting. People you don't know on an invite aren't added.
- **Taking it back:** everything either one adds is marked with where it came from. Under each section, "Remove what
  came from…" deletes just that (it shows how many meetings and people first), and Granola meetings you remove are not
  brought in again.

## Backups, restore and export

Settings, Your data. A copy of everything is made each day and kept for two weeks (they sit in the data folder's
`backups`, readable only by you, and include your keys, so treat that folder like the database). "Back up now" makes
one whenever you like. **Restore** puts everything back as it was at that backup; first it keeps a backup of how
things are now, so a restore can be undone. A backup from a newer version of the app is refused. **Export** writes a
readable JSON file of your people, relationships and notes (no settings, no keys) to the data folder's `exports`;
Show Data Folder in the menu bar opens it.

## Updating

Quit the app and replace it with the new one from a new disk image. Your data stays where it is. (Automatic updates
are off: the updater reads public GitHub releases, and this project is private.)

## If something's wrong

- **"Another app is using port 8791":** quit it, or change `port` in `app.json` and rebuild.
- **The window is blank or old after an update:** quit the app from the menu bar icon and open it again.
- The server log is at `~/Library/Application Support/The Lodge/logs/server.log`.

## Building it yourself

`scripts/install-app.sh` is the usual way: on this Mac it runs `scripts/check`, builds the app, makes a backup
through the running app, swaps the new app into `/Applications` (keeping the old one in `build/previous-app/`), opens
it and checks it serves the new build with the data intact. If anything fails it puts the previous app back.

`scripts/build-app.sh` on its own makes `dist-app/The Lodge.app`; add `--dmg` for the disk image. Builds happen on
this Mac, because GitHub's Mac builders cost ten times its Linux ones: the GitHub workflow that builds a release
(`.github/workflows/release.yml`) only runs when started by hand from the Actions tab.
`scripts/check-app.py` runs behaviour checks on the built app (restarts, quitting, two copies).
