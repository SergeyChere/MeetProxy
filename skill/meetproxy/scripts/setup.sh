#!/usr/bin/env bash
# MeetProxy skill: install the `meet` command and open the mailbox in the current git repository.
# Usage (from the project root): bash <skill-dir>/scripts/setup.sh
# MEET_PKG overrides the package source (e.g. a local checkout for testing).
set -euo pipefail
PKG="${MEET_PKG:-git+https://github.com/SergeyChere/MeetProxy}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Run this inside the project's git repository." >&2; exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "This repository has no 'origin' remote. Push it to GitHub first." >&2; exit 1
fi

if ! command -v meet >/dev/null 2>&1; then
  python3 -m pip install -q "$PKG" 2>/dev/null \
    || python3 -m pip install -q --break-system-packages "$PKG" \
    || python3 -m pip install -q --user "$PKG"
fi
if ! command -v meet >/dev/null 2>&1; then
  echo "Installed, but 'meet' is not on PATH. Add $(python3 -m site --user-base)/bin to PATH." >&2
  exit 1
fi

MB="${MEET_DIR:-$(git rev-parse --show-toplevel)/.meetproxy}"
if [ -d "$MB/.git" ]; then
  echo "mailbox already open at $MB"
else
  meet init
fi
meet status
