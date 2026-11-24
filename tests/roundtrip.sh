#!/usr/bin/env bash
# End-to-end test without a GPU. A local bare repo plays GitHub; "agent" and "colab" are two dirs.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
RUNNER=
cleanup() { if [ -n "$RUNNER" ]; then kill "$RUNNER" 2>/dev/null || true; fi; rm -rf "$T"; }
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
{ grep -q "No runner" <<< "$($P status)"; } && ok "status explains that no runner is connected" || fail "status explains that no runner is connected"

start_runner() {
  # the runner gets no git identity at all, like a fresh Colab VM
  mkdir -p "$T/home$1"
  env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
    HOME="$T/home$1" GIT_CONFIG_NOSYSTEM=1 XDG_CONFIG_HOME="$T/home$1" \
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
{ printf 'cat version.txt\n' | $P run a2 - --poll 1 --timeout 60 2>/dev/null | grep "^v2" >/dev/null; } && ok "runner pulled new code" || fail "runner pulled new code"
{ grep -q '"code": "code [0-9a-f]* v2 (main)"' .pilot/out/a2.done; } && ok "commit recorded in .done" || fail "commit recorded in .done"

# history: one line per finished job, compact table for the agent
{ grep -q "^a2,.*,0," .pilot/out/history.csv 2>/dev/null || { $P history >/dev/null; grep -q "^a2," .pilot/out/history.csv; }; } \
  && ok "history.csv has a line per job" || fail "history.csv"
{ H=$($P history --last 1); [ "$(echo "$H" | wc -l)" -eq 2 ] && echo "$H" | grep "^a2 " >/dev/null; } \
  && ok "pilot history: header + newest job" || fail "pilot history"

# human report on request; the agent's output does not mention it
printf '# charts: on\necho measured > $PILOT_OUT/results.csv\n' > c.sh
$P run c1 c.sh --poll 1 --timeout 60 > "$T/c1.txt" 2>&1 || true
{ test -f .pilot/out/c1/report.md && test -f .pilot/out/history.md; } && ok "charts: on -> report.md + history.md" || { cat "$T/runner1.out"; fail "report made"; }
{ ! grep -qi "report" "$T/c1.txt"; } && ok "agent output does not mention the report" || fail "report hidden from agent"
{ ! test -f .pilot/out/a2/report.md; } && ok "no report without asking" || fail "no report by default"

# export to the project folder, not committed
{ $P export a1 c1 | grep "exported 2 job" >/dev/null && test -f pilot-runs/a1/results.csv && test -f pilot-runs/c1/report.md \
  && test -f pilot-runs/history.csv && [ -z "$(git status --porcelain --ignored -- pilot-runs | grep -v '^??')" ]; } \
  && ok "export copies results, not committed" || fail "export"
{ $P report a1 | grep "pilot-runs/a1/report.md" >/dev/null && grep -q "# a1" pilot-runs/a1/report.md; } \
  && ok "pilot report builds a report locally" || fail "pilot report"
rm -rf pilot-runs c.sh

# the agent works on its own branch: jobs run that branch, unpushed commits are flagged
git checkout -q -b claude/feature && echo v3 > version.txt && git commit -qam v3
printf 'cat version.txt\n' | $P send b1 - 2> "$T/warn.txt" || true
{ grep -q "not on GitHub" "$T/warn.txt"; } && ok "unpushed branch flagged" || fail "unpushed branch flagged"
git push -q -u origin claude/feature 2>/dev/null
printf 'cat version.txt\n' | $P run b2 - --poll 1 --timeout 60 > "$T/b2.txt" 2>&1 || true
{ grep -q "^v3" "$T/b2.txt"; } && ok "job ran the agent's branch" || { echo ---b2; cat "$T/b2.txt"; echo ---runner; tail -20 "$T/runner1.out"; echo ---b1; cat .pilot/out/b1.log 2>/dev/null; fail "job ran the agent's branch"; }
$P wait b1 --poll 1 --timeout 60 >/dev/null 2>&1 || true

# a job sent while another is running (rebase with a log being written)
printf 'for i in 1 2 3 4 5 6; do echo tick $i; sleep 1; done\n' | $P send a3 - 2>/dev/null
sleep 3
printf 'echo second\n' | $P send a4 - 2>/dev/null
$P wait a3 --poll 1 --timeout 60 2>/dev/null
{ $P wait a4 --follow --poll 1 --timeout 60 2>/dev/null | grep second >/dev/null; } && ok "job queued during a running job" || fail "job queued during a running job"
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
{ grep -q "Runner exited (stopped)" <<< "$($P status)"; } && ok "status explains the stop" || fail "status explains the stop"

# a machine dies in the middle of a job: a new machine (empty disk) must resume from what was pushed
printf 'touch $PILOT_OUT/r.csv\nn=$(wc -l < $PILOT_OUT/r.csv)\necho line$n >> $PILOT_OUT/r.csv\necho run$n\nsleep 30\n' | $P send r1 - 2>/dev/null
start_runner 3
for i in $(seq 40); do git -C .pilot pull -q --rebase 2>/dev/null; [ -s .pilot/out/r1/r.csv ] && break; sleep 1; done
kill -9 $RUNNER; pkill -9 -f "sleep 30" || true; rm -rf "$T/colab/mb.live" "$T/colab/mb"
start_runner 4
$P wait r1 --poll 1 --timeout 90 > /dev/null 2>&1 || true
{ grep -q line0 .pilot/out/r1/r.csv && grep -q line1 .pilot/out/r1/r.csv; } && ok "new machine resumes pushed job files" || { cat .pilot/out/r1/r.csv; fail "new machine resumes pushed job files"; }
{ grep -q "(resumed)" .pilot/out/r1.log; } && ok "log marks the resume" || fail "log marks the resume"
$P stop > /dev/null
for i in $(seq 40); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done

# a new runner (next evening) must not be blocked by the old STOP
start_runner 2
{ printf 'echo again\n' | $P run a8 - --poll 1 --timeout 60 2>/dev/null | grep again >/dev/null; } && ok "restart after stop works" || fail "restart after stop works"
$P stop > /dev/null
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
echo "roundtrip: all checks passed"
