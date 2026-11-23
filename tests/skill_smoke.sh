#!/usr/bin/env bash
# The skill as a new user gets it: unzip into a fresh project, run setup.sh, send the template job.
# No GPU: a fake nvidia-smi plays a T4; a local bare repo plays GitHub.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d)
RUNNER=
cleanup() { [ -n "$RUNNER" ] && kill "$RUNNER" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
ok() { echo "ok: $*"; }
fail() { echo "FAIL: $*"; exit 1; }

# fake GPU
mkdir -p "$T/bin"
cat > "$T/bin/nvidia-smi" <<'EOF'
#!/bin/sh
case "$*" in
  *query-gpu*) echo "Tesla T4, 15360 MiB, 535.104" ;;
  *query-compute-apps*) ;;
  *) echo "fake nvidia-smi" ;;
esac
EOF
chmod +x "$T/bin/nvidia-smi"

# the package, as pip would install it, in a clean venv
python3 -m venv "$T/venv"
"$T/venv/bin/pip" install -q "$ROOT"
export PATH="$T/venv/bin:$T/bin:$PATH"

# skill zip
bash "$ROOT/scripts/build_skill.sh" > /dev/null
ZIP="$ROOT/dist/colab-pilot-skill.zip"
{ unzip -l "$ZIP" | grep -q "colab-pilot/SKILL.md"; } && ok "zip has SKILL.md at colab-pilot/" || fail "zip layout"
{ unzip -p "$ZIP" colab-pilot/SKILL.md | head -4 | grep -q "^name: colab-pilot"; } && ok "frontmatter name" || fail "frontmatter name"

# fresh project, skill installed the documented way
git init -q --bare -b main "$T/gh.git"
git clone -q "$T/gh.git" "$T/proj" 2>/dev/null
cd "$T/proj"
echo "print('hello from the project')" > main.py
git add . && git commit -qm init && git push -q origin main
mkdir -p .claude/skills && unzip -q "$ZIP" -d .claude/skills
SK=.claude/skills/colab-pilot

{ bash $SK/scripts/setup.sh > "$T/setup.txt" 2>&1; grep -q "No runner" "$T/setup.txt"; } && ok "setup opens mailbox, says no runner" || { cat "$T/setup.txt"; fail "setup"; }
{ bash $SK/scripts/setup.sh > "$T/setup2.txt" 2>&1; grep -q "already open" "$T/setup2.txt"; } && ok "setup is idempotent" || fail "setup idempotent"

# Colab side
mkdir -p "$T/colab" "$T/home"
env -u GIT_AUTHOR_NAME -u GIT_AUTHOR_EMAIL -u GIT_COMMITTER_NAME -u GIT_COMMITTER_EMAIL \
  HOME="$T/home" GIT_CONFIG_NOSYSTEM=1 XDG_CONFIG_HOME="$T/home" POLL_S=1 PUSH_S=1 HEARTBEAT_S=2 IDLE_MIN=2 \
  python3 -c "import pilot.runner as r; r.start('$T/gh.git', '$T/colab/proj', '$T/colab/mb')" \
  > "$T/runner.out" 2>&1 &
RUNNER=$!
for i in $(seq 20); do pilot status > "$T/st.txt" 2>/dev/null; grep -q "gpu: Tesla T4" "$T/st.txt" && break; sleep 1; done
{ grep -q "gpu: Tesla T4" "$T/st.txt"; } && ok "status shows the GPU" || { cat "$T/runner.out"; fail "status gpu"; }

# the template job, unmodified
pilot run s01_template $SK/templates/job.sh --poll 1 --timeout 90 > "$T/job.txt" 2>&1 \
  && ok "template job exits 0" || { cat "$T/job.txt"; fail "template job"; }
{ grep -q '"exit": 0' .pilot/out/s01_template.done; } && ok ".done exit 0" || fail ".done"
{ [ "$(wc -l < .pilot/out/s01_template/results.csv)" -eq 7 ]; } && ok "results.csv: header + 6 rows" || fail "results.csv"
{ grep -q "Tesla T4" .pilot/out/s01_template.done; } && ok "GPU recorded" || fail "GPU recorded"

pilot stop > /dev/null
for i in $(seq 30); do kill -0 $RUNNER 2>/dev/null || break; sleep 1; done
echo "skill smoke: all checks passed"
