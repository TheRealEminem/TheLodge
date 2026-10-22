#!/usr/bin/env bash
# Builds The Lodge on this Mac and publishes it as a GitHub release, the way Trailmix ships: the disk image, its
# checksum (the app's updater checks it) and a copy with a fixed name, so the download page (docs/) can always link
# to releases/latest/download/TheLodge-arm64.dmg. Built here, not on GitHub: its Mac builders cost ten times the
# Linux ones.
#
#   scripts/release.sh v0.2.0          the release everyone gets: the download page and the updater offer it
#   scripts/release.sh v0.3.0 --beta   a pre-release to try first ("latest" skips it); scripts/promote.sh v0.3.0 later
#
# Before it builds: VERSION says the same version, the work is committed and pushed, and scripts/check passes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG=${1:?usage: scripts/release.sh vX.Y.Z [--beta]}
BETA=0
[ "${2:-}" = "--beta" ] && BETA=1
REPO=${LODGE_REPO:-TheRealEminem/TheLodge}
field() { plutil -extract "$1" raw -o - "$ROOT/app.json"; }
NAME="$(field name)"
SLUG="${NAME// /}"   # GitHub turns spaces in file names into dots, so the published files have none
VERSION="${TAG#v}"

say() { printf '\033[1;32m›\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "The tag looks like v1.2.3, not $TAG."
[ "$(tr -d '[:space:]' <"$ROOT/VERSION")" = "$VERSION" ] || die "VERSION says $(cat "$ROOT/VERSION"); set it to $VERSION and commit first."
[ "$(field updateRepo)" = "$REPO" ] || die "app.json's updateRepo should be $REPO, so the app updates itself from these releases."
git -C "$ROOT" diff --quiet HEAD -- || die "There are uncommitted changes; commit them first, so the release is exactly a commit."
gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1 && die "$TAG is already released."
COMMIT="$(git -C "$ROOT" rev-parse HEAD)"
git -C "$ROOT" fetch -q origin
git -C "$ROOT" branch -r --contains "$COMMIT" | grep -q . || die "This commit isn't on GitHub yet; push it first."

say "Checking…"
"$ROOT/scripts/check" >/dev/null || die "scripts/check failed; nothing was released. Run it to see why."
VERSION="$VERSION" "$ROOT/scripts/build-app.sh" --dmg
say "Trying the new app on a spare port…"
PY="$([ -x "$ROOT/.venv/bin/python" ] && echo "$ROOT/.venv/bin/python" || echo python3)"
"$PY" "$ROOT/scripts/check-app.py" | sed 's/^/  /' || die "scripts/check-app.py found a problem; nothing was released."

OUT="$ROOT/dist-app"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp "$OUT/$NAME-$VERSION-arm64.dmg" "$STAGE/$SLUG-$VERSION-arm64.dmg"
cp "$OUT/$NAME-$VERSION-arm64.dmg" "$STAGE/$SLUG-arm64.dmg"   # the fixed name the download page links to
(cd "$STAGE" && shasum -a 256 "$SLUG-$VERSION-arm64.dmg" >"$SLUG-$VERSION-arm64.dmg.sha256")

say "Publishing $TAG$([ $BETA = 1 ] && echo " as a pre-release")…"
FLAGS=(--latest)
[ $BETA = 1 ] && FLAGS=(--prerelease)
gh release create "$TAG" --repo "$REPO" --target "$COMMIT" --title "$NAME $VERSION" --generate-notes "${FLAGS[@]}" \
  "$STAGE/$SLUG-$VERSION-arm64.dmg" "$STAGE/$SLUG-$VERSION-arm64.dmg.sha256" "$STAGE/$SLUG-arm64.dmg"
say "Released: https://github.com/$REPO/releases/tag/$TAG"
