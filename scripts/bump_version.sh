#!/usr/bin/env bash
# bump_version.sh — prepare a release pull request: set manifest.json's version,
# promote the Unreleased CHANGELOG section to a dated release heading, and update
# the compare links. CI tags and publishes the release once the pull request is
# merged into main (docs/development.md -> "Branches and releases").
#
# Usage: ./scripts/bump_version.sh <X.Y.Z> [YYYY-MM-DD]
#   The date defaults to today; pass one when preparing a release ahead of
#   the day it ships.
#
# Every check runs before anything is written, and both files are written
# before anything is printed, so the bump is all-or-nothing: piping the
# output into `head` (or the terminal going away) can't stop it halfway with
# manifest.json bumped but CHANGELOG.md not.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
  echo "Usage: ./scripts/bump_version.sh <X.Y.Z> [YYYY-MM-DD]" >&2
  exit 1
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
VERSION="$1"
DATE="${2:-$(date +%Y-%m-%d)}"
MANIFEST="custom_components/dockhand/manifest.json"
CHANGELOG="CHANGELOG.md"
REPO_URL="https://github.com/raetha/ha-dockhand"

fail() {
  echo "Error: $*" >&2
  exit 1
}

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "version must be X.Y.Z, got '$VERSION'"
[[ "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail "date must be YYYY-MM-DD, got '$DATE'"
grep -qE '^  "version": "[^"]*",?$' "$MANIFEST" || fail "no \"version\" line found in $MANIFEST"
grep -q '^## \[Unreleased\]' "$CHANGELOG" || fail "no '## [Unreleased]' section in $CHANGELOG"
if grep -qF "## [$VERSION]" "$CHANGELOG"; then
  fail "$CHANGELOG already has a [$VERSION] section — already bumped?"
fi
PREV_TAG=$(grep -oE '^\[Unreleased\]: .*/compare/v?[0-9]+\.[0-9]+\.[0-9]+\.\.\.HEAD' "$CHANGELOG" \
  | grep -oE 'v?[0-9]+\.[0-9]+\.[0-9]+' | tail -1 || true)
[ -n "$PREV_TAG" ] || fail "could not read the previous tag from the [Unreleased] compare link"

DIRTY=""
if ! git diff --quiet -- "$MANIFEST" "$CHANGELOG" 2>/dev/null \
   || ! git diff --cached --quiet -- "$MANIFEST" "$CHANGELOG" 2>/dev/null; then
  DIRTY=1
fi

TMP_MANIFEST=$(mktemp)
TMP_CHANGELOG=$(mktemp)
trap 'rm -f "$TMP_MANIFEST" "$TMP_CHANGELOG"' EXIT

# A plain line edit rather than a JSON rewrite, so the file's own key order
# (domain, name, then alphabetical) and formatting stay exactly as they are.
sed -E "s/^(  \"version\": )\"[^\"]*\"/\1\"$VERSION\"/" "$MANIFEST" > "$TMP_MANIFEST"

# Insert the dated heading directly beneath [Unreleased], so the notes
# drafted there become this release's, and point the compare links at it.
awk -v ver="$VERSION" -v date="$DATE" -v prev="$PREV_TAG" -v repo="$REPO_URL" '
  /^## \[Unreleased\]/ && !heading {
    print; print ""; print "## [" ver "] - " date; heading = 1; next
  }
  /^\[Unreleased\]: / && !links {
    print "[Unreleased]: " repo "/compare/" ver "...HEAD"
    print "[" ver "]: " repo "/compare/" prev "..." ver
    links = 1; next
  }
  { print }
' "$CHANGELOG" > "$TMP_CHANGELOG"

grep -qF "\"version\": \"$VERSION\"" "$TMP_MANIFEST" || fail "manifest.json version edit didn't apply"
grep -qF "## [$VERSION] - $DATE" "$TMP_CHANGELOG" || fail "CHANGELOG heading edit didn't apply"

cat "$TMP_MANIFEST" > "$MANIFEST"
cat "$TMP_CHANGELOG" > "$CHANGELOG"

{
  echo "Bumped to $VERSION ($DATE), previous release $PREV_TAG."
  echo "  Updated $MANIFEST and $CHANGELOG (release heading + compare links)."
  if [ -n "$DIRTY" ]; then
    echo "  Note: both files had uncommitted changes, so undoing this needs"
    echo "  manual edits rather than 'git checkout'."
  fi
  echo ""
  echo "  Review CHANGELOG.md, commit, and open the release pull request (dev -> main)."
  echo "  CI tags $VERSION and publishes the release when it's merged; don't tag by hand."
} || true
