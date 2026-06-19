#!/bin/bash
set -euo pipefail

PROJECT_DIR="$HOME/supernote-obsidian-sync"
FORMULA="/opt/homebrew/Library/Taps/kulturban/homebrew-supernote-obsidian-sync/Formula/supernote-obsidian-sync.rb"

cd "$PROJECT_DIR"

VERSION=$(python3 - <<'PY'
from pathlib import Path
import re

text = Path("pyproject.toml").read_text(encoding="utf-8")
match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)

if not match:
    raise SystemExit("Could not find version in pyproject.toml")

print(match.group(1))
PY
)

TAG="v$VERSION"
URL="https://github.com/Kulturban/supernote-obsidian-sync/archive/refs/tags/$TAG.tar.gz"
TMP="/tmp/supernote-obsidian-sync-$TAG.tar.gz"

echo "Version: $VERSION"
echo "Tag:     $TAG"
echo "URL:     $URL"
echo ""

curl -L -o "$TMP" "$URL"

SHA=$(shasum -a 256 "$TMP" | awk '{print $1}')

echo "SHA256:  $SHA"
echo ""

python3 - <<PY
from pathlib import Path
import re

formula = Path("$FORMULA")
text = formula.read_text(encoding="utf-8")

text = re.sub(
    r'url "https://github\\.com/Kulturban/supernote-obsidian-sync/archive/refs/tags/v[^"]+\\.tar\\.gz"',
    'url "$URL"',
    text,
)

text = re.sub(
    r'sha256 "[a-f0-9]{64}"',
    'sha256 "$SHA"',
    text,
    count=1,
)

formula.write_text(text, encoding="utf-8")
PY

echo "Updated Formula:"
grep -nE 'url|sha256' "$FORMULA" | head -2
