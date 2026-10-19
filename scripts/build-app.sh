#!/usr/bin/env bash
# Builds dist/<Name>.app: one self-contained Mac app holding the menu bar host (mac/), its own Python, the
# server (core/ + the modules listed in app.json) and the web app, so nothing else needs installing.
#
#   scripts/build-app.sh          build dist/<Name>.app
#   scripts/build-app.sh --dmg    also make dist/<Name>-<version>-arm64.dmg (+ .sha256 for the updater)
#
# Needs: Apple silicon, macOS 14+, the Xcode command line tools (swift), Node.js and internet access
# (downloads the Python runtime once into build/cache, plus Python packages).
#
# Signing: ad-hoc by default. To sign for real, set SIGN_IDENTITY="Developer ID Application: …" (this turns on
# the hardened runtime too; notarizing the result is a separate `xcrun notarytool` step).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
field() { plutil -extract "$1" raw -o - "$ROOT/app.json"; }
NAME="$(field name)"
APP_ID="$(field id)"
BUNDLE_ID="$(field bundleId)"
PREFIX="$(field envPrefix)"
PORT="$(field port)"
UPDATE_REPO="$(field updateRepo 2>/dev/null || true)"
VERSION="${VERSION:-$(tr -d '[:space:]' <"$ROOT/VERSION")}"
OUT="${OUT:-$ROOT/dist-app}"   # where the app (and disk image) go
APP="$OUT/$NAME.app"
RES="$APP/Contents/Resources"
CACHE="${CACHE:-$ROOT/build/cache}"

# python-build-standalone (https://github.com/astral-sh/python-build-standalone): a relocatable CPython.
PY_VERSION="3.14.7"
PY_RELEASE="20260929"
PY_FILE="cpython-$PY_VERSION+$PY_RELEASE-aarch64-apple-darwin-install_only_stripped.tar.gz"
PY_SHA256="44b4716f4e63bc85e1c07ea2aca730d13a0ec3557d06526d84a13b1d111cf4f9"

say() { printf '\033[1;32m›\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] || die "The app is built on an Apple silicon Mac."
command -v swift >/dev/null || die "Building needs the Xcode command line tools: xcode-select --install"
command -v npm >/dev/null || die "Building needs Node.js (brew install node)."

# ── Web app ────────────────────────────────────────────────────────────
say "Building the web app…"
(cd "$ROOT" && { [ -d node_modules ] || npm ci --silent; } && npm run -s build >/dev/null)

# ── Menu bar host ──────────────────────────────────────────────────────
say "Building the menu bar app…"
# The menu bar icon is the app's own (identity/mac/Mark.swift); it's copied in for the build and never committed in mac/.
cp "$ROOT/identity/mac/Mark.swift" "$ROOT/mac/Sources/AppHost/Mark.swift"
swift build -c release --package-path "$ROOT/mac" 2>&1 | grep -E "error|Build complete" | tail -n 3 || true
BIN="$(swift build -c release --package-path "$ROOT/mac" --show-bin-path)/AppHost"
[ -x "$BIN" ] || die "The menu bar app didn't build. Run: swift build -c release --package-path mac"

# ── Bundle ─────────────────────────────────────────────────────────────
say "Assembling $NAME.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES/bin" "$RES/app"
cp "$BIN" "$APP/Contents/MacOS/$NAME"
[ -f "$ROOT/identity/mac/AppIcon.icns" ] && cp "$ROOT/identity/mac/AppIcon.icns" "$RES/AppIcon.icns"

cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>$NAME</string>
  <key>CFBundleDisplayName</key><string>$NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleExecutable</key><string>$NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.productivity</string>
  <key>LSUIElement</key><true/>
  <key>NSHighResolutionCapable</key><true/>
  <key>FamilyAppID</key><string>$APP_ID</string>
  <key>FamilyEnvPrefix</key><string>$PREFIX</string>
  <key>FamilyPort</key><string>$PORT</string>
  <key>FamilyUpdateRepo</key><string>$UPDATE_REPO</string>
</dict></plist>
PLIST

# ── Python runtime ─────────────────────────────────────────────────────
mkdir -p "$CACHE"
if [ ! -f "$CACHE/$PY_FILE" ]; then
  say "Downloading the Python runtime ($PY_VERSION, once)…"
  curl -fL --progress-bar -o "$CACHE/$PY_FILE.part" "https://github.com/astral-sh/python-build-standalone/releases/download/$PY_RELEASE/${PY_FILE//+/%2B}"
  mv "$CACHE/$PY_FILE.part" "$CACHE/$PY_FILE"
fi
[ "$(shasum -a 256 "$CACHE/$PY_FILE" | cut -d' ' -f1)" = "$PY_SHA256" ] || { rm -f "$CACHE/$PY_FILE"; die "The downloaded Python runtime failed its checksum; try again."; }
tar -xzf "$CACHE/$PY_FILE" -C "$RES"   # -> Resources/python
PY="$RES/python/bin/python3"

say "Installing Python packages…"
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1
"$PY" -m pip install -q --no-compile -r "$ROOT/requirements.txt"
# A module that needs more (a native binary, a model runtime) adds a scripts/bundle-<module>.sh; it runs here.
for extra in "$ROOT"/scripts/bundle-*.sh; do
  [ -f "$extra" ] && { say "Adding $(basename "$extra" .sh | sed 's/^bundle-//')…"; RES="$RES" PY="$PY" bash "$extra"; }
done

# ── Slim down ──────────────────────────────────────────────────────────
say "Trimming…"
LIB="$RES/python/lib/python${PY_VERSION%.*}"
SITE="$LIB/site-packages"
rm -rf "$SITE"/pip "$SITE"/pip-* "$SITE"/setuptools "$SITE"/setuptools-* "$SITE"/pkg_resources "$SITE"/_distutils_hack "$SITE"/distutils-precedence.pth
rm -rf "$LIB"/test "$LIB"/idlelib "$LIB"/tkinter "$LIB"/turtledemo "$LIB"/ensurepip "$LIB"/config-* "$LIB"/lib-dynload/_tkinter*
rm -rf "$RES"/python/include "$RES"/python/share "$RES"/python/lib/pkgconfig "$RES"/python/lib/*.a
rm -rf "$RES"/python/lib/tcl* "$RES"/python/lib/tk* "$RES"/python/lib/itcl* "$RES"/python/lib/thread* "$RES"/python/lib/libtcl* "$RES"/python/lib/libtk*
# Only the interpreter stays in bin/: the launchers pip made point at the build machine, and leftovers would be dangling links.
find "$RES/python/bin" -mindepth 1 ! -name python3 ! -name "python${PY_VERSION%.*}" -delete
find "$SITE" -type d \( -name tests -o -name test \) -prune -exec rm -rf {} +
find "$RES/python" -name __pycache__ -type d -prune -exec rm -rf {} +

# ── The app itself ─────────────────────────────────────────────────────
# Server code: core/ and every module (Python files and any assets/ folders; no web sources or tests).
rsync -a --prune-empty-dirs --exclude='tests/' --exclude='web/' --exclude='__pycache__/' \
  --include='*/' --include='*.py' --include='assets/**' --exclude='*' "$ROOT/core" "$ROOT/modules" "$RES/app/"
cp "$ROOT/app.json" "$ROOT/VERSION" "$RES/app/"
rsync -a --delete "$ROOT/dist/" "$RES/ui/"

# Compile ahead of time, never re-checked against the source: the app is never written to while it runs
# (that would break its signature), and starts faster.
"$PY" -m compileall -q -j 0 --invalidation-mode unchecked-hash "$RES/python/lib" "$RES/app" >/dev/null

# ── Sign ───────────────────────────────────────────────────────────────
IDENTITY="${SIGN_IDENTITY:--}"
SIGN=(codesign --force --sign "$IDENTITY")
if [ "$IDENTITY" != "-" ]; then SIGN+=(--timestamp --options runtime); fi
say "Signing ($([ "$IDENTITY" = "-" ] && echo "ad-hoc" || echo "$IDENTITY"))…"
while IFS= read -r -d '' f; do
  case "$(file -b "$f")" in *Mach-O*) "${SIGN[@]}" "$f" >/dev/null 2>&1 || die "Couldn't sign $f" ;; esac
done < <(find "$APP" -type f -print0)
ENTITLEMENTS=()
[ "$IDENTITY" != "-" ] && [ -f "$ROOT/mac/App.entitlements" ] && ENTITLEMENTS=(--entitlements "$ROOT/mac/App.entitlements")
"${SIGN[@]}" ${ENTITLEMENTS[@]+"${ENTITLEMENTS[@]}"} "$APP" >/dev/null 2>&1 || die "Couldn't sign the app"
codesign --verify --strict "$APP" 2>&1 | head -n 3

du -sh "$APP" | awk -v app="$APP" '{print "› Built " app " (" $1 ")"}'

# ── Disk image ─────────────────────────────────────────────────────────
if [ "${1:-}" = "--dmg" ]; then
  DMG="$OUT/$NAME-$VERSION-arm64.dmg"
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  say "Making the disk image…"
  ditto "$APP" "$STAGE/$NAME.app"
  ln -s /Applications "$STAGE/Applications"
  rm -f "$DMG"
  hdiutil create -quiet -volname "$NAME" -srcfolder "$STAGE" -format ULFO -ov "$DMG"
  # The app's updater checks a download against this before installing it.
  (cd "$OUT" && shasum -a 256 "$(basename "$DMG")" >"$(basename "$DMG").sha256")
  du -sh "$DMG" | awk -v dmg="$DMG" '{print "› Built " dmg " (" $1 ")"}'
fi
