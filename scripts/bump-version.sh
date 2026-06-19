#!/usr/bin/env bash
# Keep the app version in sync across the three places that declare it:
#   1. backend/pyproject.toml         version = "X.Y.Z"
#   2. backend/app/config.py          app_version: str = "X.Y.Z"   (-> FastAPI + /health)
#   3. frontend/package.json          "version": "X.Y.Z"           (-> Vite __APP_VERSION__, UI)
#
# Usage:
#   scripts/bump-version.sh 0.3.0   # set all three to 0.3.0
#   scripts/bump-version.sh --check # verify all three already match (exit 1 if they drift)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYPROJECT="$ROOT/backend/pyproject.toml"
CONFIG="$ROOT/backend/app/config.py"
PACKAGE="$ROOT/frontend/package.json"

current() {
  local py cfg pkg
  py=$(sed -nE 's/^version = "([^"]*)".*/\1/p' "$PYPROJECT" | head -1)
  cfg=$(sed -nE 's/.*app_version: str = "([^"]*)".*/\1/p' "$CONFIG" | head -1)
  pkg=$(sed -nE 's/.*"version": "([^"]*)".*/\1/p' "$PACKAGE" | head -1)
  printf '  backend/pyproject.toml   %s\n  backend/app/config.py    %s\n  frontend/package.json    %s\n' "$py" "$cfg" "$pkg"
  # echo the distinct set for the caller
  printf '%s\n%s\n%s\n' "$py" "$cfg" "$pkg"
}

if [[ "${1:-}" == "--check" ]]; then
  mapfile -t vals < <(current | tail -3)
  echo "Current versions:"; current | head -3
  if [[ "${vals[0]}" == "${vals[1]}" && "${vals[1]}" == "${vals[2]}" ]]; then
    echo "OK: all three match (${vals[0]})"
    exit 0
  fi
  echo "DRIFT: versions do not match" >&2
  exit 1
fi

VERSION="${1:-}"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z.]+)?$ ]]; then
  echo "usage: $0 X.Y.Z   (or --check)" >&2
  exit 1
fi

# Each substitution is anchored tightly so it only touches the intended line.
sed -i -E "s/^version = \"[^\"]*\"/version = \"$VERSION\"/" "$PYPROJECT"
sed -i -E "s/(app_version: str = )\"[^\"]*\"/\1\"$VERSION\"/" "$CONFIG"
sed -i -E "0,/(\"version\": )\"[^\"]*\"/s//\1\"$VERSION\"/" "$PACKAGE"

echo "Bumped to $VERSION:"
current | head -3
echo
echo "Next: update CHANGELOG, then commit & tag, e.g.:"
echo "  git commit -am \"Release v$VERSION\" && git tag -a v$VERSION -m \"v$VERSION\" && git push --follow-tags"
