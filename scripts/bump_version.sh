#!/usr/bin/env bash
# bump_version.sh — update manifest.json, promote the Unreleased CHANGELOG
# section to a dated release heading, maintain compare links, commit hints.
# Usage: ./scripts/bump_version.sh 1.7.4
set -e

if [ -z "$1" ]; then
  echo "Usage: ./scripts/bump_version.sh <new_version>"
  echo "Example: ./scripts/bump_version.sh 1.7.4"
  exit 1
fi

VERSION="$1"
DATE=$(date +%Y-%m-%d)
MANIFEST="custom_components/dockhand/manifest.json"
CHANGELOG="CHANGELOG.md"
REPO_URL="https://github.com/raetha/ha-dockhand"

# Validate semver-ish format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "Error: version must be in X.Y.Z format"
  exit 1
fi

if ! command -v jq >/dev/null; then
  echo "Error: jq is required (used to update manifest.json)"
  exit 1
fi

# A dirty tree is fine — the version bump is commonly committed together
# with the associated changes. Warn (don't block) if the two files this
# script rewrites already have uncommitted edits, since undoing a bump then
# requires manual cleanup instead of a simple git checkout.
if ! git diff --quiet -- "$MANIFEST" "$CHANGELOG" \
   || ! git diff --cached --quiet -- "$MANIFEST" "$CHANGELOG"; then
  echo "Warning: $MANIFEST and/or $CHANGELOG have uncommitted changes."
  echo "         This script rewrites both; undoing the bump will require"
  echo "         manual edits rather than 'git checkout'."
fi

# The Unreleased section and its compare link must exist — the release
# heading is inserted beneath it and the previous tag is read from its link.
if ! grep -q '^## \[Unreleased\]' "$CHANGELOG"; then
  echo "Error: no '## [Unreleased]' section found in $CHANGELOG"
  exit 1
fi
PREV_TAG=$(grep -oE '^\[Unreleased\]: .*/compare/v[0-9]+\.[0-9]+\.[0-9]+\.\.\.HEAD' "$CHANGELOG" \
  | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1)
if [ -z "$PREV_TAG" ]; then
  echo "Error: could not determine previous tag from the [Unreleased] compare link"
  exit 1
fi

echo "Bumping version to $VERSION (previous release: $PREV_TAG)..."

# Update manifest.json
jq ".version = \"$VERSION\"" "$MANIFEST" > manifest.tmp && mv manifest.tmp "$MANIFEST"
echo "  Updated $MANIFEST"

# Insert the dated release heading directly beneath [Unreleased], so any
# notes drafted under Unreleased become the notes for this release.
awk -v ver="$VERSION" -v date="$DATE" '
  /^## \[Unreleased\]/ && !done {
    print; print ""; print "## [" ver "] — " date; done=1; next
  }
  { print }
' "$CHANGELOG" > changelog.tmp && mv changelog.tmp "$CHANGELOG"

# Update compare links: point Unreleased at the new tag and add this
# release directly beneath it.
awk -v ver="$VERSION" -v prev="$PREV_TAG" -v repo="$REPO_URL" '
  /^\[Unreleased\]: / {
    print "[Unreleased]: " repo "/compare/v" ver "...HEAD"
    print "[" ver "]: " repo "/compare/" prev "...v" ver
    next
  }
  { print }
' "$CHANGELOG" > changelog.tmp && mv changelog.tmp "$CHANGELOG"
echo "  Updated $CHANGELOG (release heading + compare links)"
echo ""
echo "  Review CHANGELOG.md, then commit (together with any other staged"
echo "  changes for this release) and tag:"
echo "    git add -A"
echo "    git commit -m \"Release $VERSION\""
echo "    git tag -a v$VERSION -m \"Release $VERSION\""
echo "    git push && git push --tags"
echo ""
echo "  The GitHub Actions release workflow will trigger automatically on the tag push."
