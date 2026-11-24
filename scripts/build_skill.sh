#!/usr/bin/env bash
# Package skill/meetproxy into dist/meetproxy-skill.zip (the upload for skill marketplaces).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/meetproxy-skill.zip"
rm -f "$OUT"
cd "$ROOT/skill"
zip -qr -X "$OUT" meetproxy -x '*.DS_Store' -x '*__pycache__*'
echo "$OUT"
unzip -l "$OUT"
