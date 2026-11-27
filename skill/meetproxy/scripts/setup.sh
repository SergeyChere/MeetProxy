#!/usr/bin/env bash
# MeetProxy skill: make sure the right `meet` is available and open the mailbox in this git repo.
# Usage (from the project root): bash <skill-dir>/scripts/setup.sh
#   Installs nothing unless MEET_INSTALL=yes (ask the user first). Then MeetProxy goes into its own
#   virtual environment ($MEET_VENV, default ~/.meetproxy/venv-<version>); system packages are
#   never touched. A `meet` on PATH is used only if `meet --version` matches exactly.
# MEET_PKG overrides the package source (e.g. a local checkout for testing).
set -euo pipefail
WANT="${MEET_VERSION:-0.7.0}"
PKG="${MEET_PKG:-git+https://github.com/SergeyChere/MeetProxy@v$WANT}"
VENV="${MEET_VENV:-$HOME/.meetproxy/venv-$WANT}"

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Run this inside the project's git repository." >&2; exit 1
fi
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "This repository has no 'origin' remote. Push it to GitHub first." >&2; exit 1
fi

right_meet() { command -v meet >/dev/null 2>&1 && [ "$(meet --version 2>/dev/null)" = "meet $WANT" ]; }

if ! right_meet && [ -x "$VENV/bin/meet" ]; then export PATH="$VENV/bin:$PATH"; fi
if ! right_meet; then
  if [ "${MEET_INSTALL:-}" != "yes" ]; then
    found=$(command -v meet >/dev/null 2>&1 && meet --version 2>/dev/null || echo "none")
    echo "MeetProxy $WANT is not installed (meet on PATH: $found)."
    echo "Ask the user before installing. With consent rerun with MEET_INSTALL=yes: it creates an"
    echo "isolated environment in $VENV and installs $PKG there; system packages are not touched."
    exit 2
  fi
  python3 -m venv "$VENV" \
    || { echo "python3 -m venv failed: install the python3-venv package and retry." >&2; exit 1; }
  "$VENV/bin/python" -m pip install -q "$PKG"
  export PATH="$VENV/bin:$PATH"
  right_meet || { echo "installed meet is not version $WANT" >&2; exit 1; }
fi
case "$(command -v meet)" in
  "$VENV"/*) echo "meet $WANT is in $VENV. In every later shell run first:"
             echo "export PATH=\"$VENV/bin:\$PATH\"" ;;
esac

MB="${MEET_DIR:-$(git rev-parse --show-toplevel)/.meetproxy}"
if [ -d "$MB/.git" ]; then
  echo "mailbox already open at $MB"
else
  meet init
fi
meet status
