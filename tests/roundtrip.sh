#!/usr/bin/env bash
# End-to-end test with a local bare repo as "GitHub": runner and client in two clones.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'kill $RUNNER 2>/dev/null || true; rm -rf "$T"' EXIT
git init -q --bare -b pilot "$T/remote.git"
git clone -q "$T/remote.git" "$T/seed" 2>/dev/null
( cd "$T/seed" && git checkout -q -b pilot && mkdir cmd out && touch cmd/.keep out/.keep &&
  git add . && git -c user.name=t -c user.email=t@t commit -qm init && git push -q origin pilot )
git clone -q -b pilot "$T/remote.git" "$T/runner"; git clone -q -b pilot "$T/remote.git" "$T/client"
for d in runner client; do git -C "$T/$d" config user.name t; git -C "$T/$d" config user.email t@t; done

export MY_TOKEN=supersecret123
PILOT_MAILBOX="$T/runner" PILOT_WORKDIR="$T" POLL_S=1 PUSH_S=1 IDLE_MIN=1 \
  python3 "$ROOT/pilot/runner.py" > "$T/runner.out" 2>&1 & RUNNER=$!
export PILOT_DIR="$T/client"
P="python3 $ROOT/pilot/cli.py"

printf 'echo hello $PILOT_JOB\necho token=$MY_TOKEN\necho 1,2 > $PILOT_OUT/results.csv\n' | $P send a1 -
$P wait a1 --poll 1 --timeout 60 2>/dev/null
grep -q "hello a1" "$T/client/out/a1.log"
grep -q "token=\*\*\*" "$T/client/out/a1.log"
! grep -q supersecret123 "$T/client/out/a1.log"
test -f "$T/client/out/a1/results.csv"

printf 'exit 3\n' | $P send a2 -
set +e; $P wait a2 --poll 1 --timeout 60 2>/dev/null; rc=$?; set -e
test $rc -eq 3

printf '# timeout: 2\nsleep 100 & sleep 100\n' | $P send a3 -
$P wait a3 --poll 1 --timeout 60 2>/dev/null || true
grep -q timeout "$T/client/out/a3.done"
! pgrep -f "sleep 100" >/dev/null

printf '# gpu: H100\necho no\n' | $P send a4 -
$P wait a4 --poll 1 --timeout 60 2>/dev/null || true
grep -q "wrong gpu" "$T/client/out/a4.done"

$P stop
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
! kill -0 $RUNNER 2>/dev/null
grep -q stopped "$T/runner/out/runner.json"
echo "roundtrip: all checks passed"
