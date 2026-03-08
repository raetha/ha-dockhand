#!/usr/bin/env bash
# bump_version.sh — update manifest.json, write CHANGELOG entry, commit, and tag
# Usage: ./scripts/bump_version.sh 0.3.0
set -e

if [ -z "$1" ]; then
  echo "Usage: ./scripts/bump_version.sh <new_version>"
  echo "Example: ./scripts/bump_version.sh 0.3.0"
  exit 1
fi

VERSION="$1"
DATE=$(date +%Y-%m-%d)
MANIFEST="custom_components/dockhand/manifest.json"
CHANGELOG="CHANGELOG.md"

# Validate semver-ish format
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "Error: version must be in X.Y.Z format"
  exit 1
fi

# Ensure working tree is clean
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Error: working tree has uncommitted changes. Commit or stash them first."
  exit 1
fi

echo "Bumping version to $VERSION..."

# Update manifest.json
jq ".version = \"$VERSION\"" "$MANIFEST" > manifest.tmp && mv manifest.tmp "$MANIFEST"
echo "  Updated $MANIFEST"

# Prepend CHANGELOG entry
TMPFILE=$(mktemp)
cat > "$TMPFILE" << ENTRY
# Changelog

## $VERSION — $DATE
- <!-- describe changes here before committing -->

ENTRY
# Append everything after the first line of the existing file
tail -n +2 "$CHANGELOG" >> "$TMPFILE"
mv "$TMPFILE" "$CHANGELOG"
echo "  Prepended entry in $CHANGELOG"
echo ""
echo "  Edit CHANGELOG.md to fill in the release notes, then run:"
echo "    git add custom_components/dockhand/manifest.json CHANGELOG.md"
echo "    git commit -m \"Release $VERSION\""
echo "    git tag -a v$VERSION -m \"Release $VERSION\""
echo "    git push && git push --tags"
echo ""
echo "  The GitHub Actions release workflow will trigger automatically on the tag push."
