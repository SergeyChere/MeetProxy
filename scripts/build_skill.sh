#!/usr/bin/env bash
# Package skill/colab-pilot into dist/colab-pilot-skill.zip (the upload for skill marketplaces).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/colab-pilot-skill.zip"
rm -f "$OUT"
cd "$ROOT/skill"
zip -qr -X "$OUT" colab-pilot -x '*.DS_Store' -x '*__pycache__*'
echo "$OUT"
unzip -l "$OUT"
