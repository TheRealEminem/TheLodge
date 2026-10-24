# Installing The Lodge on a Mac

The Lodge is a normal Mac app for Apple silicon (M1 or later), macOS 14 or newer. It keeps everything on your Mac.

## First launch

1. Download `TheLodge-<version>-arm64.dmg` from the [latest release](https://github.com/TheRealEminem/TheLodge/releases/latest),
   open it and drag **The Lodge** onto **Applications**.
2. Open it from Applications. Because the app is signed without an Apple Developer ID, macOS says it can't verify
   it and offers only **Done** or **Move to Trash**: click **Done**. You only do this once:
   - open **System Settings, Privacy & Security**, scroll down to *"The Lodge" was blocked*, and press **Open Anyway**
     (then your Mac password, and **Open Anyway** once more), or
   - in Terminal: `xattr -dr com.apple.quarantine "/Applications/The Lodge.app"`.

   Updates installed from inside the app, and a copy you built yourself on this Mac, open without this step.
3. A window opens, and a small A-frame icon appears in the menu bar. Closing the window leaves the app in the menu bar.
4. A short setup walks you through your name, where AI should run, and Lockdown. It recommends a path for your Mac:
   **On this Mac** (private and free; The Lodge can install Ollama and download a model for you), **Mixed** (most jobs
   here, the careful reading with a cloud AI), or **A cloud AI** (the best results). Keys are typed in there or in
   **Settings**, never into a file, and are kept only in your data folder. A key entered in another Trailmix family
   app on this Mac is already there. Everything can be changed later in **Settings**. To see the setup again (an existing install
   never sees it on its own), use **Settings → The Lodge → Run setup again**; nothing is deleted.

## Where things live

- Your data: `~/Library/Application Support/The Lodge/` (readable only by you). **Back this folder up.** Deleting the app
  doesn't touch it. The menu bar icon has **Show Data Folder** and **Show Server Log**.
- To start fresh, quit the app and move that folder away.
- **Open at Login** is in the menu bar menu.

## Getting your people in

Add people by hand, or drop a spreadsheet, a LinkedIn connections export, documents or notes on the Inbox. The first-run
setup offers a fictional network if you only want to look around (Home has the same link until you add your own people).

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

The Lodge checks this repository's releases and offers new versions in **Settings → Updates** and the menu bar's
Updates menu. It checks each download against its published checksum before installing it, and your data stays
where it is.

- **Beta updates** (off by default) offers each new version as soon as it's out. Without it you get a version once
  it has been a beta for 3 days with no blocker reported.
- **Skip this version** stops it offering that one; **Go back** returns to the version you had before.
- Replacing the app by hand with one from a newer disk image works too.

## If something's wrong

- **"Another app is using port 8791":** quit it, or change `port` in `app.json` and rebuild.
- **The window is blank or old after an update:** quit the app from the menu bar icon and open it again.
- The server log is at `~/Library/Application Support/The Lodge/logs/server.log`.

## Building it yourself

`scripts/install-app.sh` is the usual way. On this Mac it runs `scripts/check`, builds the app and tries it with
`scripts/check-app.py`, makes a backup through the running app, then moves the new app into `/Applications`. The
old one is kept in `build/previous-app.noindex/`, out of Spotlight's way, so there is only ever one copy to open.
Finally it opens the new app and checks that it serves the new build with the data intact. If anything fails, it
puts the previous app back.

`scripts/build-app.sh` on its own makes `dist-app/The Lodge.app`; add `--dmg` for the disk image. Day-to-day builds
happen on this Mac, because GitHub's Mac builders cost ten times its Linux ones. GitHub builds only releases: pushing
a version tag runs `.github/workflows/release.yml`, which publishes it as a beta (see "Releasing" in the README).
`scripts/check-app.py` runs behaviour checks on the built app (restarts, quitting, two copies).
