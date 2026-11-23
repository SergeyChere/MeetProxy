#!/usr/bin/env bash
# colab-pilot skill: install the `pilot` command and open the mailbox in the current git repository.
# Usage (from the project root): bash <skill-dir>/scripts/setup.sh
# PILOT_PKG overrides the package source (e.g. a local checkout for testing).
set -euo pipefail
PKG="${PILOT_PKG:-git+https://github.com/SergeyChere/colab-pilot}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Run this inside the project's git repository." >&2; exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "This repository has no 'origin' remote. Push it to GitHub first." >&2; exit 1
fi

if ! command -v pilot >/dev/null 2>&1; then
  python3 -m pip install -q "$PKG" 2>/dev/null \
    || python3 -m pip install -q --break-system-packages "$PKG" \
    || python3 -m pip install -q --user "$PKG"
fi
if ! command -v pilot >/dev/null 2>&1; then
  echo "Installed, but 'pilot' is not on PATH. Add $(python3 -m site --user-base)/bin to PATH." >&2
  exit 1
fi

MB="${PILOT_DIR:-$(git rev-parse --show-toplevel)/.pilot}"
if [ -d "$MB/.git" ]; then
  echo "mailbox already open at $MB"
else
  pilot init
fi
pilot status
