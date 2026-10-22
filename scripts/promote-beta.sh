#!/usr/bin/env bash
# Makes the newest beta the release everyone gets, once it's been tried: when the newest pre-release has been out
# BETA_DAYS days (3 by default) and no open issue is labelled "blocks release" (BLOCKING_LABEL), it becomes the
# full, latest release. Otherwise it says why not. Run daily by .github/workflows/promote.yml.
# Releases live in app.json's "updateRepo", where installed apps look; with none, updates are off.
#
#   scripts/promote-beta.sh                          promotes the newest beta if it's ready, otherwise says why not
#   DRY_RUN=1 scripts/promote-beta.sh                only says what it would do (reads, never changes anything)
#   BETA_DAYS=0 DRY_RUN=1 scripts/promote-beta.sh    ignores how long it's been out
#   scripts/promote-beta.sh v0.3.0                   promotes that pre-release now, however long it's been out
#
# An open issue with the label holds back whichever beta is newest, until it's closed or the label comes off.
# Needs gh (signed in, or GH_TOKEN) and jq. To try the rules without GitHub, RELEASES_JSON and BLOCKERS_JSON name
# files to read instead (the JSON of `gh release list --json …` and `gh issue list --json …` below).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="${REPO:-$(jq -r '.updateRepo // ""' "$ROOT/app.json")}"
BETA_DAYS="${BETA_DAYS:-3}"
LABEL="${BLOCKING_LABEL:-blocks release}"
DRY_RUN="${DRY_RUN:-0}"
WANTED="${1:-}"

[ -n "$REPO" ] || { echo "Nothing to promote: app.json has no updateRepo, so this app doesn't publish updates."; exit 0; }

if [ -n "${RELEASES_JSON:-}" ]; then releases="$(cat "$RELEASES_JSON")"
else releases="$(gh release list --repo "$REPO" --limit 100 --json tagName,isPrerelease,isDraft,publishedAt)"; fi

# "TAG PUBLISHED_AT" of the newest pre-release (true) or full release (false), by version: only plain vX.Y.Z tags,
# never drafts. With a tag given, that pre-release.
pick() {
  jq -r --argjson pre "$1" --arg tag "$WANTED" '
    [.[] | select(.isDraft | not) | select(.isPrerelease == $pre) | select(.tagName | test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))
     | select($pre == false or $tag == "" or .tagName == $tag)
     | .v = (.tagName | ltrimstr("v") | split(".") | map(tonumber))]
    | max_by(.v) // empty | "\(.tagName) \(.publishedAt)"' <<<"$releases"
}
read -r TAG PUBLISHED <<<"$(pick true)" || true
read -r STABLE _ <<<"$(pick false)" || true

if [ -z "${TAG:-}" ]; then
  [ -n "$WANTED" ] && { echo "Not promoting: $WANTED isn't a pre-release in $REPO." >&2; exit 1; }
  echo "Nothing to promote: there's no pre-release."; exit 0
fi

if [ -n "${STABLE:-}" ] && ! jq -en --arg a "${TAG#v}" --arg b "${STABLE#v}" \
    '($a | split(".") | map(tonumber)) > ($b | split(".") | map(tonumber))' >/dev/null; then
  echo "Nothing to promote: the newest pre-release $TAG isn't newer than the current release $STABLE."; exit 0
fi

# Days since it was published (jq does the date math, so it's the same on GNU and BSD systems).
AGE="$(jq -rn --arg t "$PUBLISHED" '(now - ($t | fromdateiso8601)) / 86400 | . * 10 | floor / 10')"
OUT="$([ "$AGE" = 1 ] && echo "1 day" || echo "$AGE days")"
if [ -z "$WANTED" ] && ! jq -en --argjson age "$AGE" --argjson days "$BETA_DAYS" '$age >= $days' >/dev/null; then
  echo "Not promoting $TAG yet: it's been out for $OUT, and needs $BETA_DAYS."; exit 0
fi

# Open issues labelled as blocking. A failure here stops the script, so it never promotes unchecked.
if [ -n "${BLOCKERS_JSON:-}" ]; then blockers="$(cat "$BLOCKERS_JSON")"
else blockers="$(gh issue list --repo "$REPO" --state open --label "$LABEL" --limit 100 --json number,title)"; fi
if [ "$(jq length <<<"$blockers")" -gt 0 ]; then
  echo "Open issues labelled \"$LABEL\":"
  jq -r '.[] | "  #\(.number) \(.title)"' <<<"$blockers"
  echo "Not promoting $TAG: close them, or take the label off, to let it through."; exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "Would run: gh release edit $TAG --repo $REPO --prerelease=false --latest"
  echo "Would promote $TAG (out for $OUT, nothing labelled \"$LABEL\"; current release ${STABLE:-none}). Dry run: nothing changed."
  exit 0
fi
gh release edit "$TAG" --repo "$REPO" --prerelease=false --latest
echo "Promoted $TAG (out for $OUT, nothing labelled \"$LABEL\"): it's now the release everyone gets, after ${STABLE:-none}."
