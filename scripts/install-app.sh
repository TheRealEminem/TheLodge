#!/usr/bin/env bash
# Builds the Mac app on this Mac and puts it in /Applications in place of the copy you're running, safely.
# Everything happens locally: GitHub's Mac builders cost ten times its Linux ones, so they're not used for this.
#
#   scripts/install-app.sh              check, build, check the app, back up, swap, open, verify
#   scripts/install-app.sh --no-check   skip scripts/check and scripts/check-app.py (when they've only just passed)
#
# 1. scripts/check: tests, types, the web build and the style rules.
# 2. scripts/build-app.sh makes dist-app/<Name>.app, and scripts/check-app.py tries it on a spare port with its own
#    data folder (restarts, quitting, two copies).
# 3. A backup through the running app ("Back up now", so it shows in Settings), or a direct SQLite copy into the
#    same folder when the app isn't running.
# 4. The app is asked to quit (its server stops with it) and the new one is moved into its place, so there is only
#    ever one copy to open. The one it replaces is kept in build/previous-app.noindex/, where Spotlight and
#    Launchpad don't offer it.
# 5. The new app is opened, and the script waits for its server, then checks that it serves this build's web app,
#    that the database passes SQLite's own check, and that no table lost rows. If any of that fails, the previous
#    app is put back and opened, and the backup from step 3 is named so you can restore it from Settings.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
field() { plutil -extract "$1" raw -o - "$ROOT/app.json"; }
NAME="$(field name)"
APP_ID="$(field id)"
BUNDLE_ID="$(field bundleId)"
PORT="$(field port)"
MODULES="$(python3 -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["modules"]))' "$ROOT/app.json")"
BUILT="$ROOT/dist-app/$NAME.app"
TARGET="/Applications/$NAME.app"
PREVIOUS="$ROOT/build/previous-app.noindex/$NAME.app"
DATA="$HOME/Library/Application Support/$NAME"
DB="$DATA/$APP_ID.db"
API="http://127.0.0.1:$PORT/api"

say() { printf '\033[1;32m›\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }
up() { curl -sf -m 2 "$API/app" >/dev/null; }
running() { pgrep -f "$TARGET/Contents/MacOS/" >/dev/null; }

# Rows per table for the modules' own tables (not search indexes), as "table count" lines. Reads only; a normal
# connection, because SQLite can't open a database in WAL mode read-only while the app holds it.
counts() {
  [ -f "$DB" ] || return 0
  local t
  for t in $(sqlite3 "$DB" "select name from sqlite_master where type='table' order by name"); do
    case "$t" in *_fts*) continue ;; esac
    for m in $MODULES; do
      [[ "$t" == "${m}_"* ]] && echo "$t $(sqlite3 "$DB" "select count(*) from \"$t\"")"
    done
  done
  return 0
}

CHECK=1
[ "${1:-}" = "--no-check" ] && CHECK=0
[ $CHECK = 0 ] || { say "Checking…"; "$ROOT/scripts/check" >/dev/null || die "scripts/check failed; nothing was installed. Run it to see why."; }

"$ROOT/scripts/build-app.sh"
[ -d "$BUILT" ] || die "The build didn't produce $BUILT."
codesign --verify --strict "$BUILT" || die "The new app's signature doesn't verify; nothing was installed."
if [ $CHECK = 1 ]; then
  say "Trying the new app on a spare port…"
  PY="$([ -x "$ROOT/.venv/bin/python" ] && echo "$ROOT/.venv/bin/python" || echo python3)"
  "$PY" "$ROOT/scripts/check-app.py" | sed 's/^/  /' || die "scripts/check-app.py found a problem; nothing was installed."
fi

# ── Back up ────────────────────────────────────────────────────────────
BACKUP=""
if up; then
  BACKUP="$(curl -sf -m 60 -X POST "$API/backups" | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')" \
    || die "The running app couldn't make a backup, so nothing was installed."
elif [ -f "$DB" ]; then
  mkdir -p "$DATA/backups" && chmod 700 "$DATA/backups"
  BACKUP="$APP_ID-$(date -u +%Y%m%d-%H%M%S)-manual.db"
  sqlite3 "$DB" ".backup '$DATA/backups/$BACKUP'" && chmod 600 "$DATA/backups/$BACKUP" \
    || die "Couldn't back up the database, so nothing was installed."
fi
[ -n "$BACKUP" ] && say "Backed up: $BACKUP"
BEFORE="$(counts)"

# ── Swap ───────────────────────────────────────────────────────────────
if running || up; then
  say "Quitting $NAME…"
  osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
  for _ in $(seq 1 40); do { running || up; } || break; sleep 0.5; done
  running && die "$NAME didn't quit; nothing was changed. Quit it from the menu bar and run this again."
  up && die "Something else is answering on port $PORT (scripts/dev?). Stop it and run this again."
fi

say "Installing…"
if [ -d "$TARGET" ]; then
  rm -rf "$PREVIOUS" && mkdir -p "$(dirname "$PREVIOUS")"
  mv "$TARGET" "$PREVIOUS"
fi
mv "$BUILT" "$TARGET"

rollback() {
  printf '\033[1;31m✗\033[0m %s\n' "$1" >&2
  if [ -d "$PREVIOUS" ]; then
    osascript -e "tell application id \"$BUNDLE_ID\" to quit" >/dev/null 2>&1 || true
    for _ in $(seq 1 40); do running || break; sleep 0.5; done
    rm -rf "$TARGET" && mv "$PREVIOUS" "$TARGET" && open "$TARGET"
    echo "  The previous app is back in /Applications and open again." >&2
  fi
  [ -n "$BACKUP" ] && echo "  The backup from just before is $BACKUP (Settings → Your data)." >&2
  exit 1
}

# ── Open and verify ────────────────────────────────────────────────────
say "Opening the new $NAME…"
open "$TARGET"
for _ in $(seq 1 120); do up && break; sleep 0.5; done
up || rollback "The new app's server didn't start within a minute (see Show Server Log in its menu)."

served="$(curl -sf -m 5 "http://127.0.0.1:$PORT/" | grep -o 'assets/index-[^"]*\.js' | head -n 1 || true)"
built="$(grep -o 'assets/index-[^"]*\.js' "$ROOT/dist/index.html" | head -n 1)"
[ -n "$served" ] && [ "$served" = "$built" ] || rollback "The app is serving a different web app ($served) from the one just built ($built)."

[ "$(sqlite3 "$DB" 'pragma integrity_check')" = "ok" ] || rollback "The database failed SQLite's integrity check after the update."
AFTER="$(counts)"
lost="$(awk 'NF == 0 { next } NR == FNR { before[$1] = $2; next } { after[$1] = $2 }
  END { for (t in before) { n = (t in after) ? after[t] : 0; if (n + 0 < before[t] + 0) print "  " t ": " before[t] " → " n } }' \
  <(echo "$BEFORE") <(echo "$AFTER"))"
[ -z "$lost" ] || rollback "Rows went missing after the update:
$lost"

say "Installed $NAME $(curl -sf "$API/app" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])') ($(git -C "$ROOT" rev-parse --short HEAD)$(git -C "$ROOT" diff --quiet HEAD -- core modules app.json VERSION || echo ", with uncommitted changes")); data checked: $(echo "$AFTER" | grep -c .) tables, nothing missing."
