#!/usr/bin/env bash
# The skill as a new user gets it: unzip into a fresh project, run setup.sh, send the template job.
# No GPU: a fake nvidia-smi plays a T4; a local bare repo plays GitHub.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
RUNNER=
cleanup() { if [ -n "$RUNNER" ]; then kill "$RUNNER" 2>/dev/null || true; fi; rm -rf "$T"; }
trap cleanup EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
ok() { echo "ok: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

# fake GPU
mkdir -p "$T/bin"
cat > "$T/bin/nvidia-smi" <<'EOF'
#!/bin/sh
case "$*" in
  *query-compute-apps*) ;;
  *index,name*) echo "0, Tesla T4, 15360, 70.00, 1590" ;;
  *utilization.gpu*) echo "0, 97, 40, 6000, 1590, 5000, 65, 68.5, 0x0000000000000004" ;;
  *query-gpu*) echo "Tesla T4, 15360 MiB, 535.104" ;;
  *) echo "fake nvidia-smi" ;;
esac
EOF
chmod +x "$T/bin/nvidia-smi"

# the package, as pip would install it, in a clean venv
python3 -m venv --system-site-packages "$T/venv"  # matplotlib, as on Colab
"$T/venv/bin/pip" install -q "$ROOT"
export PATH="$T/venv/bin:$T/bin:$PATH"

# skill zip
bash "$ROOT/scripts/build_skill.sh" > /dev/null
ZIP="$ROOT/dist/meetproxy-skill.zip"
{ unzip -l "$ZIP" | grep "meetproxy/SKILL.md" >/dev/null; } && ok "zip has SKILL.md at meetproxy/" || fail "zip layout"
{ unzip -p "$ZIP" meetproxy/SKILL.md | head -4 | grep "^name: meetproxy" >/dev/null; } && ok "frontmatter name" || fail "frontmatter name"

# fresh project, skill installed the documented way
git init -q --bare -b main "$T/gh.git"
git clone -q "$T/gh.git" "$T/proj" 2>/dev/null
cd "$T/proj"
echo "print('hello from the project')" > main.py
git add . && git commit -qm init && git push -q origin main
mkdir -p .claude/skills && unzip -q "$ZIP" -d .claude/skills
SK=.claude/skills/meetproxy

{ bash $SK/scripts/setup.sh > "$T/setup.txt" 2>&1; grep -q "No runner" "$T/setup.txt"; } && ok "setup opens mailbox, says no runner" || { cat "$T/setup.txt"; fail "setup"; }
{ bash $SK/scripts/setup.sh > "$T/setup2.txt" 2>&1; grep -q "already open" "$T/setup2.txt"; } && ok "setup is idempotent" || fail "setup idempotent"

# Colab side
mkdir -p "$T/colab" "$T/home"
env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
  HOME="$T/home" GIT_CONFIG_NOSYSTEM=1 XDG_CONFIG_HOME="$T/home" POLL_S=1 PUSH_S=1 HEARTBEAT_S=2 IDLE_MIN=2 \
  python3 -c "import meetproxy.runner as r; r.start('$T/gh.git', '$T/colab/proj', '$T/colab/mb')" \
  > "$T/runner.out" 2>&1 &
RUNNER=$!
for i in $(seq 20); do meet status > "$T/st.txt" 2>/dev/null; grep -q "gpu: Tesla T4" "$T/st.txt" && break; sleep 1; done
{ grep -q "gpu: Tesla T4" "$T/st.txt"; } && ok "status shows the GPU" || { cat "$T/runner.out"; fail "status gpu"; }

# the template job, unmodified
meet run s01_template $SK/templates/job.sh --poll 1 --timeout 90 > "$T/job.txt" 2>&1 \
  && ok "template job exits 0" || { cat "$T/job.txt"; fail "template job"; }
{ grep -q '"exit": 0' .meetproxy/out/s01_template.done; } && ok ".done exit 0" || fail ".done"
{ [ "$(wc -l < .meetproxy/out/s01_template/results.csv)" -eq 7 ]; } && ok "results.csv: header + 6 rows" || fail "results.csv"
{ grep -q "Tesla T4" .meetproxy/out/s01_template.done; } && ok "GPU recorded" || fail "GPU recorded"
{ grep -q '"gpu_stats"' .meetproxy/out/s01_template.done && grep -q '"util_avg": 97' .meetproxy/out/s01_template.done; } \
  && ok "gpu_stats summary in .done" || fail "gpu_stats in .done"
{ test -f .meetproxy/out/s01_template/gpu.csv; } && ok "raw gpu.csv pushed" || fail "gpu.csv"
{ grep -q '"gpu_check": "gpu ok: util 97%' "$T/job.txt" && ! grep -q '"gpu_stats"' "$T/job.txt"; } \
  && ok "agent sees one compact gpu line, not the full stats" || { cat "$T/job.txt"; fail "compact gpu line"; }

# a human report with charts, from the fake T4 telemetry
printf '# timeout: 60\n# gpu: any\n# charts: on\nsleep 3; echo ok\n' > c.sh
meet run s02_charts c.sh --poll 1 --timeout 90 > "$T/c.txt" 2>&1 || true
{ test -f .meetproxy/out/s02_charts/report.md && test -s .meetproxy/out/s02_charts/charts/gpu.svg \
  && grep -q "charts/gpu.svg" .meetproxy/out/s02_charts/report.md; } && ok "report.md with GPU chart" || { cat "$T/c.txt"; fail "charts"; }
{ test -s .meetproxy/out/charts/history.svg; } && ok "history chart" || fail "history chart"

meet stop > /dev/null
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
echo "skill smoke: all checks passed"
