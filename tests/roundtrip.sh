#!/usr/bin/env bash
# End-to-end test without a GPU. A local bare repo plays GitHub; "agent" and "colab" are two dirs.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
RUNNER=
cleanup() { [ -n "$RUNNER" ] && kill "$RUNNER" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export PYTHONPATH="$ROOT" GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
P="python3 -m pilot.cli"
ok() { echo "ok: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

# the user's project
git init -q --bare -b main "$T/gh.git"
git clone -q "$T/gh.git" "$T/agent" 2>/dev/null
echo v1 > "$T/agent/version.txt"
git -C "$T/agent" add . && git -C "$T/agent" commit -qm v1 && git -C "$T/agent" push -q origin main

# agent side: pilot init creates the branch
cd "$T/agent"
$P init > /dev/null
{ git -C "$T/gh.git" rev-parse -q --verify pilot > /dev/null; } && ok "init created branch pilot" || fail "init created branch pilot"
{ grep -q ".pilot/" .git/info/exclude; } && ok ".pilot excluded from the project" || fail ".pilot excluded from the project"
{ $P status | grep -q "No runner"; } && ok "status explains that no runner is connected" || fail "status explains that no runner is connected"

start_runner() {
  MY_TOKEN=supersecret123 POLL_S=1 PUSH_S=1 HEARTBEAT_S=2 IDLE_MIN=2 \
    python3 -c "import pilot.runner as r; r.start('$T/gh.git', '$T/colab/proj', '$T/colab/mb')" \
    > "$T/runner$1.out" 2>&1 &
  RUNNER=$!
}
mkdir -p "$T/colab"
start_runner 1

export MY_TOKEN=supersecret123
printf 'cat version.txt\necho token=$MY_TOKEN\necho 1,2 > $PILOT_OUT/results.csv\n' > j.sh
{ $P run a1 j.sh --poll 1 --timeout 60 > "$T/a1.txt" 2>&1; grep -q "^v1" "$T/a1.txt"; } && ok "job ran in the project" || fail "job ran in the project"
{ grep -q "token=\*\*\*" .pilot/out/a1.log && ! grep -q supersecret123 .pilot/out/a1.log; } && ok "secret masked" || fail "secret masked"
{ test -f .pilot/out/a1/results.csv; } && ok "results pushed" || fail "results pushed"

# agent pushes new code; the next job must see it
echo v2 > version.txt && git commit -qam v2 && git push -q origin main
{ printf 'cat version.txt\n' | $P run a2 - --poll 1 --timeout 60 2>/dev/null | grep -q "^v2"; } && ok "runner pulled new code" || fail "runner pulled new code"
{ grep -q '"code": "code [0-9a-f]* v2 (main)"' .pilot/out/a2.done; } && ok "commit recorded in .done" || fail "commit recorded in .done"

# the agent works on its own branch: jobs run that branch, unpushed commits are flagged
git checkout -q -b claude/feature && echo v3 > version.txt && git commit -qam v3
printf 'cat version.txt\n' | $P send b1 - 2> "$T/warn.txt" || true
{ grep -q "not on GitHub" "$T/warn.txt"; } && ok "unpushed branch flagged" || fail "unpushed branch flagged"
git push -q -u origin claude/feature 2>/dev/null
printf 'cat version.txt\n' | $P run b2 - --poll 1 --timeout 60 > "$T/b2.txt" 2>&1 || true
{ grep -q "^v3" "$T/b2.txt"; } && ok "job ran the agent's branch" || { cat "$T/b2.txt" .pilot/out/b1.log 2>/dev/null; fail "job ran the agent's branch"; }
$P wait b1 --poll 1 --timeout 60 >/dev/null 2>&1 || true

# a job sent while another is running (rebase with a log being written)
printf 'for i in 1 2 3 4 5 6; do echo tick $i; sleep 1; done\n' | $P send a3 - 2>/dev/null
sleep 3
printf 'echo second\n' | $P send a4 - 2>/dev/null
$P wait a3 --poll 1 --timeout 60 2>/dev/null
{ $P wait a4 --follow --poll 1 --timeout 60 2>/dev/null | grep -q second; } && ok "job queued during a running job" || fail "job queued during a running job"
{ grep -q "tick 6" .pilot/out/a3.log; } && ok "full log streamed" || fail "full log streamed"

set +e; printf 'exit 3\n' | $P run a5 - --poll 1 --timeout 60 >/dev/null 2>&1; rc=$?; set -e
{ [ $rc -eq 3 ]; } && ok "exit code passed through" || fail "exit code passed through"

printf '# timeout: 2\nsleep 77 & sleep 77\n' | $P run a6 - --poll 1 --timeout 60 >/dev/null 2>&1 || true
{ grep -q '"error": "timeout"' .pilot/out/a6.done && ! pgrep -f "sleep 77" > /dev/null; } && ok "timeout kills the whole group" || fail "timeout kills the whole group"

printf '# gpu: H100\necho no\n' | $P run a7 - --poll 1 --timeout 60 >/dev/null 2>&1 || true
printf '# gpu: any\necho no\n' | $P run a7b - --poll 1 --timeout 60 >/dev/null 2>&1 || true
{ grep -q "wrong gpu" .pilot/out/a7b.done; } && ok "gpu: any refused without a GPU" || fail "gpu: any refused without a GPU"
{ grep -q "wrong gpu" .pilot/out/a7.done; } && ok "wrong GPU refused" || fail "wrong GPU refused"

$P stop > /dev/null
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
{ ! kill -0 $RUNNER 2>/dev/null; } && ok "stop ends the runner" || fail "stop ends the runner"
{ $P status | grep -q "Runner exited (stopped)"; } && ok "status explains the stop" || fail "status explains the stop"

# a new runner (next evening) must not be blocked by the old STOP
start_runner 2
{ printf 'echo again\n' | $P run a8 - --poll 1 --timeout 60 2>/dev/null | grep -q again; } && ok "restart after stop works" || fail "restart after stop works"
$P stop > /dev/null
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
echo "roundtrip: all checks passed"
