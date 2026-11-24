#!/usr/bin/env bash
# Every test: unit + CLI + end-to-end (pytest) and the two shell journeys.
# Usage: bash tests/run_all.sh [--coverage]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
export GIT_CONFIG_GLOBAL=/dev/null   # never touch the user's git config

if [ "${1:-}" = "--coverage" ]; then
  # measure subprocesses too (runner and CLI run as separate processes in the tests)
  SP=$(python3 -c "import site; print(site.getsitepackages()[0])")
  PTH="$SP/zz_meetproxy_cov.pth"
  echo "import coverage; coverage.process_startup()" > "$PTH"
  trap 'rm -f "$PTH"' EXIT
  sed "s#^data_file = .*#data_file = $ROOT/.coverage#" .coveragerc > /tmp/meetproxy-covrc
  export COVERAGE_PROCESS_START=/tmp/meetproxy-covrc
  rm -f .coverage .coverage.*
fi

python3 -m pytest -q -p no:cacheprovider
bash tests/roundtrip.sh
bash tests/skill_smoke.sh

if [ "${1:-}" = "--coverage" ]; then
  python3 -m coverage combine -q --rcfile=/tmp/meetproxy-covrc
  python3 -m coverage report -i --rcfile=/tmp/meetproxy-covrc --omit='*/venv/*,*/site-packages/*'
fi
echo "all tests passed"
