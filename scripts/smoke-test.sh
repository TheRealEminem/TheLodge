#!/usr/bin/env bash
# The release gate for updates: tries a built app's updater end to end, in a throwaway folder, with a stand-in
# for GitHub. The installed app and its data are never touched. CI runs it before publishing a release.
#
#   scripts/smoke-test.sh dist-app/<Name>.app dist-app/<Name>-<version>-arm64.dmg
#
# A copy of the app relabelled as an older version (0.0.1) plays the installed app, and must:
#   1. not offer a version that's only out as a beta while beta updates are off;
#   2. not update while the app says it's busy (GET /api/jobs/busy);
#   3. with beta updates on, install the beta from the disk image (checksum, bundle ID and signature checked),
#      keeping the version it replaced;
#   4. go back to that version, skipping the one it left;
#   5. then not offer the skipped version again.
# Each step runs the app itself with <PREFIX>_UPDATE_TEST, which installs or goes back after its first check and
# logs each state to stderr ("update: …"). A stand-in answers for the app's server (/api/app, /api/jobs/busy),
# so the bundled server never starts here; scripts/check-app.py tries that part.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
field() { plutil -extract "$1" raw -o - "$ROOT/app.json"; }
NAME="$(field name)"
APP_ID="$(field id)"
PREFIX="$(field envPrefix)"
[ $# = 2 ] && [ -d "$1" ] && [ -f "$2" ] || { echo "Usage: scripts/smoke-test.sh dist-app/$NAME.app dist-app/$NAME-<version>-arm64.dmg" >&2; exit 2; }
APP="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
DMG="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
PORT="${SMOKE_PORT:-8799}"
STAND_IN="http://127.0.0.1:$PORT"
OLD="0.0.1"

T="$(mktemp -d "${TMPDIR:-/tmp}/$APP_ID-smoke.XXXXXX")"
INSTALLED="$T/Applications/$NAME.app"
DATA="$T/data"
FEED="$T/feed"
KEPT="$DATA/updates.noindex/previous/$NAME.app"
mkdir -p "$T/Applications" "$T/home" "$DATA" "$FEED/api/jobs"
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  rm -rf "$T"
}
trap cleanup EXIT

step() { printf '\n== %s\n' "$*"; }
fail() { echo "SMOKE TEST FAILED: $*" >&2; echo "--- the app's log" >&2; tail -n 30 "$T/app.log" >&2 || true; exit 1; }
version_of() { plutil -extract CFBundleShortVersionString raw -o - "$1/Contents/Info.plist"; }
choice() { plutil -extract "$1" raw -o - "$DATA/updates.noindex/choices.json" 2>/dev/null || true; }
if curl -s -o /dev/null -m 2 "$STAND_IN/"; then fail "something is already answering at $STAND_IN (set SMOKE_PORT)"; fi

NEW="$(version_of "$APP")"
echo "new version: $NEW, playing the installed one: $OLD"

# The installed app: this build, relabelled as an older version and signed again, as check-app.py does.
ditto "$APP" "$INSTALLED"
plutil -replace CFBundleShortVersionString -string "$OLD" "$INSTALLED/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$OLD" "$INSTALLED/Contents/Info.plist"
codesign --force --deep --sign - "$INSTALLED" >/dev/null 2>&1 || fail "couldn't sign the relabelled copy"

# The stand-in: GitHub's release list (with the image named as GitHub names it), and the app's server.
IMAGE="${NAME// /.}-$NEW-arm64.dmg"
cp "$DMG" "$FEED/$IMAGE"
(cd "$FEED" && shasum -a 256 "$IMAGE" >"$IMAGE.sha256")
publish() {  # publish true|false: the new version, as a pre-release or a full release
  cat >"$FEED/releases.json" <<EOF
[{"tag_name": "v$NEW", "prerelease": $1, "draft": false, "html_url": "$STAND_IN/",
  "assets": [{"name": "$IMAGE", "browser_download_url": "$STAND_IN/$IMAGE"},
             {"name": "$IMAGE.sha256", "browser_download_url": "$STAND_IN/$IMAGE.sha256"}]}]
EOF
}
busy() { echo "{\"busy\": $1}" >"$FEED/api/jobs/busy"; }
echo "{\"id\": \"$APP_ID\"}" >"$FEED/api/app"
publish true
busy false
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$FEED" >/dev/null 2>&1 &
PIDS+=($!)
for _ in $(seq 1 50); do curl -s -o /dev/null -m 1 "$STAND_IN/api/app" && break; sleep 0.2; done

# Runs the installed app with UPDATE_TEST=$1 until it quits (it updated or went back) or settles where it is; the
# log is in app.log. Going back settles only by failing: its first check says "up to date" before it starts.
run_app() {
  local settled='^update: (upToDate|offline|failed)'
  [ "$1" = go-back ] && settled='^update: failed'
  env -i HOME="$T/home" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
    "${PREFIX}_DATA_DIR=$DATA" "${PREFIX}_SERVER_URL=$STAND_IN" "${PREFIX}_NO_OPEN=1" \
    "${PREFIX}_UPDATE_URL=$STAND_IN/releases.json" "${PREFIX}_UPDATE_DELAY=1" "${PREFIX}_UPDATE_NO_RELAUNCH=1" \
    "${PREFIX}_UPDATE_TEST=$1" "$INSTALLED/Contents/MacOS/$NAME" >"$T/app.log" 2>&1 &
  local pid=$!
  PIDS+=("$pid")
  for _ in $(seq 1 360); do
    kill -0 "$pid" 2>/dev/null || return 0
    if grep -qE "$settled" "$T/app.log"; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.5
  done
  fail "the app neither finished nor settled within 3 minutes"
}

step "1. Beta updates off: a version that's only a beta isn't offered"
run_app install
grep -q '^update: upToDate' "$T/app.log" || fail "expected it to say it's up to date"
[ "$(version_of "$INSTALLED")" = "$OLD" ] || fail "it changed version"
echo "not offered"

step "2. Busy: no update in the middle of something"
mkdir -p "$DATA/updates.noindex"
echo '{"beta": true}' >"$DATA/updates.noindex/choices.json"
busy true
run_app install
grep -q "^update: available(\"$NEW\")" "$T/app.log" || fail "with beta updates on, $NEW wasn't offered"
grep -q '^update: failed(.*in the middle of something' "$T/app.log" || fail "expected it to refuse while busy"
[ "$(version_of "$INSTALLED")" = "$OLD" ] || fail "it updated while busy"
echo "refused: $(grep -o 'failed(.*' "$T/app.log" | head -n 1)"

step "3. Beta updates on: the beta installs, and the version it replaced is kept"
busy false
run_app install
[ "$(version_of "$INSTALLED")" = "$NEW" ] || fail "after updating, the app is $(version_of "$INSTALLED"), not $NEW"
codesign --verify --strict "$INSTALLED" || fail "the updated app's signature doesn't verify"
[ -d "$KEPT" ] && [ "$(version_of "$KEPT")" = "$OLD" ] || fail "the version it replaced ($OLD) wasn't kept for going back"
leftovers="$(find "$T/Applications" -mindepth 1 -maxdepth 1 ! -name "$NAME.app")"
[ -z "$leftovers" ] || fail "it left things beside the app: $leftovers"
echo "updated $OLD -> $NEW, $OLD kept"

step "4. Go back: the kept version returns, and the one it left is skipped"
run_app go-back
[ "$(version_of "$INSTALLED")" = "$OLD" ] || fail "after going back, the app is $(version_of "$INSTALLED"), not $OLD"
codesign --verify --strict "$INSTALLED" || fail "the version it went back to doesn't verify"
[ ! -e "$KEPT" ] || fail "the kept copy is still there after going back"
[ "$(choice skipped)" = "$NEW" ] || fail "$NEW wasn't skipped after going back from it (choices: $(cat "$DATA/updates.noindex/choices.json"))"
echo "went back $NEW -> $OLD, skipping $NEW"

step "5. The version you went back from isn't offered again"
run_app install
grep -q '^update: upToDate' "$T/app.log" || fail "expected it to say it's up to date"
[ "$(version_of "$INSTALLED")" = "$OLD" ] || fail "it installed the skipped version"
echo "not offered"

echo
echo "SMOKE TEST PASSED ($OLD -> $NEW and back, beta updates, busy, skip)"
