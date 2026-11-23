"""The agent's CLI against a mailbox, with the runner's side written by hand (no runner process):
every message the agent can get, and every command's edge cases."""
import json, os, subprocess, sys

import pytest

from conftest import git


def test_help_lists_every_command(world):
    out = world.pilot("--help").stdout
    for c in ("init", "run", "send", "wait", "logs", "status", "stop", "guide", "history",
              "export", "report"):
        assert c in out


def test_guide_prints_the_agent_guide(world):
    assert "colab-pilot guide for the AI agent" in world.pilot("guide").stdout


def test_init_outside_a_repo(tmp_path):
    r = subprocess.run([sys.executable, "-m", "pilot.cli", "init"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "inside your project's git repository" in r.stderr


def test_init_without_origin(world):
    git(world.agent, "remote", "remove", "origin")
    r = world.pilot("init")
    assert r.returncode != 0


def test_init_creates_branch_and_excludes_mailbox(world):
    out = world.pilot("init", check=True).stdout
    assert "mailbox: branch 'pilot'" in out and "Next: the human opens the Colab notebook" in out
    assert git(world.gh, "rev-parse", "--verify", "pilot")
    assert ".pilot/" in (world.agent / ".git" / "info" / "exclude").read_text()
    again = world.pilot("init", check=True).stdout
    assert "already open" in again and "No runner has connected yet" in again
    assert (world.agent / ".git" / "info" / "exclude").read_text().count(".pilot/") == 1


def test_commands_need_a_mailbox(world):
    for args in (["status"], ["stop"], ["logs", "x"], ["history"], ["export"], ["wait", "x"],
                 ["send", "x", "-"], ["report", "x"]):
        r = world.pilot(*args, stdin="")
        assert r.returncode != 0 and "run `pilot init`" in r.stderr, args


def test_pilot_dir_env(world, monkeypatch, tmp_path):
    monkeypatch.setenv("PILOT_DIR", str(tmp_path / "elsewhere"))
    world.pilot("init", check=True)
    assert (tmp_path / "elsewhere" / ".git").is_dir() and not (world.agent / ".pilot").exists()


# ---------- send ----------

def test_send_pins_branch_and_refuses_duplicates(opened):
    opened.pilot("send", "j1", "-", stdin="echo hi\n", check=True)
    body = git(opened.gh, "show", "pilot:cmd/j1.sh")
    assert body.splitlines()[0] == "# branch: main" and "echo hi" in body
    r = opened.pilot("send", "j1", "-", stdin="echo again\n")
    assert r.returncode != 0 and "jobs run once" in r.stderr


def test_send_from_file_keeps_explicit_branch(opened):
    (opened.agent / "job.sh").write_text("# branch: release\necho x\n")
    opened.pilot("send", "j2", "job.sh", check=True)
    assert git(opened.gh, "show", "pilot:cmd/j2.sh").count("# branch:") == 1


def test_send_warnings(opened):
    git(opened.agent, "checkout", "-q", "-b", "feature")
    r = opened.pilot("send", "w1", "-", stdin="true\n")
    assert "branch feature is not on GitHub yet" in r.stderr
    git(opened.agent, "push", "-q", "-u", "origin", "feature")
    (opened.agent / "version.txt").write_text("local\n")
    git(opened.agent, "commit", "-qam", "local only")
    r = opened.pilot("send", "w2", "-", stdin="true\n")
    assert "the GPU runs the pushed version" in r.stderr
    (opened.agent / "version.txt").write_text("dirty\n")
    r = opened.pilot("send", "w3", "-", stdin="true\n")
    assert "uncommitted changes are not sent" in r.stderr


def test_send_detached_head_has_no_branch_line(opened):
    git(opened.agent, "checkout", "-q", "--detach")
    opened.pilot("send", "d1", "-", stdin="true\n", check=True)
    assert "# branch:" not in git(opened.gh, "show", "pilot:cmd/d1.sh")


def test_send_when_github_unreachable(opened, monkeypatch):
    monkeypatch.setenv("PILOT_PUSH_TRIES", "2")
    git(opened.agent, "remote", "set-url", "origin", str(opened.tmp / "gone.git"))
    git(opened.agent / ".pilot", "remote", "set-url", "origin", str(opened.tmp / "gone.git"))
    r = opened.pilot("send", "u1", "-", stdin="true\n")
    assert "could not reach GitHub" in r.stderr
    assert r.returncode != 0 and "push failed" in r.stderr


def test_wait_tells_the_agent_when_no_runner_is_there(opened, monkeypatch):
    monkeypatch.setenv("PILOT_SILENT_S", "0.5")
    r = opened.pilot("wait", "j", "--poll", "0.2", "--timeout", "2")
    assert "No runner has connected yet" in r.stderr and r.stderr.count("No runner") == 1


# ---------- status, heartbeat, stop ----------

def test_status_messages(opened):
    assert "No runner has connected yet" in opened.pilot("status").stdout
    opened.heartbeat("idle", minutes_ago=1)
    out = opened.pilot("status").stdout
    assert "runner: idle" in out and "gpu: Tesla T4" in out and "queue: (empty)" in out
    opened.heartbeat("idle", minutes_ago=30)
    assert "Runner silent for 30 min" in opened.pilot("status").stdout
    opened.heartbeat("running", minutes_ago=30, job="long")      # running jobs may be quiet
    assert "silent" not in opened.pilot("status").stdout
    opened.heartbeat("idle-exit")
    assert "Runner exited (idle-exit)" in opened.pilot("status").stdout


def test_status_queue(opened):
    opened.pilot("send", "q1", "-", stdin="true\n", check=True)
    opened.pilot("send", "q2", "-", stdin="true\n", check=True)
    opened.runner_writes({"out/q1.done": {"job": "q1", "exit": 0}})
    assert "queue: q2" in opened.pilot("status").stdout


def test_stop_writes_a_timestamp(opened):
    assert "stop sent" in opened.pilot("stop", check=True).stdout
    assert float(git(opened.gh, "show", "pilot:cmd/STOP")) > 1e9


# ---------- wait, logs ----------

def test_wait_returns_job_exit_code_and_compact_done(opened):
    opened.runner_writes({"out/j.log": "line\n", "out/j.done": {
        "job": "j", "exit": 3, "seconds": 1,
        "gpu_stats": {"util_avg": 10, "flags": ["idle 90%"], "samples": 100}}})
    r = opened.pilot("wait", "j", "--poll", "0.2")
    assert r.returncode == 3
    d = json.loads(r.stderr.strip().splitlines()[-1])
    assert "gpu_stats" not in d and d["gpu_check"].startswith("gpu WARN: idle 90%")


def test_wait_maps_negative_exit_to_1(opened):
    opened.runner_writes({"out/g.done": {"job": "g", "exit": -2, "error": "wrong gpu"}})
    assert opened.pilot("wait", "g", "--poll", "0.2").returncode == 1


def test_wait_follow_prints_log(opened):
    opened.runner_writes({"out/f.log": "a\nb\n", "out/f.done": {"job": "f", "exit": 0}})
    r = opened.pilot("wait", "f", "--follow", "--poll", "0.2")
    assert r.returncode == 0 and r.stdout == "a\nb\n"


def test_wait_timeout(opened):
    r = opened.pilot("wait", "never", "--poll", "0.2", "--timeout", "1")
    assert r.returncode != 0 and "wait timeout" in r.stderr


def test_logs(opened):
    assert "no log yet" in opened.pilot("logs", "x").stderr
    opened.runner_writes({"out/x.log": "".join(f"l{i}\n" for i in range(10))})
    assert opened.pilot("logs", "x").stdout.count("\n") == 10
    assert opened.pilot("logs", "x", "--tail", "2").stdout == "l8\nl9\n"


# ---------- history, export, report ----------

HIST = ("job,end,gpu,commit,branch,seconds,exit,error,util_avg,mem_peak_mb,flags\n"
        "a1,2026-11-23T18:00:00+00:00,Tesla T4,abc1234,main,10.5,0,,97,6000,\n"
        "a2,2026-11-23T18:05:00+00:00,Tesla T4,def5678,main,3.0,1,timeout,,,\n")


def test_history(opened):
    assert opened.pilot("history").stdout.strip() == "no finished jobs yet"
    opened.runner_writes({"out/history.csv": HIST})
    out = opened.pilot("history").stdout.splitlines()
    assert out[0].split()[:3] == ["job", "gpu", "commit"] and len(out) == 3
    assert "T4" in out[1] and "timeout" in out[2]
    assert len(opened.pilot("history", "--last", "1").stdout.splitlines()) == 2


def test_export(opened):
    assert "no finished jobs yet" in opened.pilot("export").stderr
    opened.runner_writes({"out/a1.done": {"job": "a1", "exit": 0}, "out/a1.log": "x\n",
                          "out/a1/results.csv": "v\n1\n", "out/a2.done": {"job": "a2", "exit": 0},
                          "out/history.csv": HIST})
    r = opened.pilot("export", check=True)                       # default: the newest job
    assert "exported 1 job(s)" in r.stdout and (opened.agent / "pilot-runs" / "a2" / "a2.done").exists()
    r = opened.pilot("export", "--all", "--dir", "runs", check=True)
    assert "exported 2 job(s) to runs" in r.stdout
    assert (opened.agent / "runs" / "a1" / "results.csv").read_text() == "v\n1\n"
    assert (opened.agent / "runs" / "history.csv").exists()
    r = opened.pilot("export", "nope", "a1")
    assert "skip nope: not finished" in r.stderr and "exported 1 job(s)" in r.stdout
    assert git(opened.agent, "status", "--porcelain", "--untracked-files=no") == ""   # nothing staged


def test_report(opened):
    assert "no finished job x" in opened.pilot("report", "x").stderr
    opened.runner_writes({"out/a1.done": {"job": "a1", "exit": 0, "seconds": 1}, "out/a1.log": "ok\n",
                          "out/history.csv": HIST})
    r = opened.pilot("report", "a1", check=True)
    md = opened.agent / "pilot-runs" / "a1" / "report.md"
    assert r.stdout.strip() == f"report for the human: {os.path.join('pilot-runs', 'a1', 'report.md')}"
    assert md.read_text().startswith("# a1")
    r = opened.pilot("report", "history", check=True)
    assert "history.md" in r.stdout and (opened.agent / "pilot-runs" / "charts" / "history.svg").exists()


def test_report_uses_runner_made_report(opened):
    opened.runner_writes({"out/a1.done": {"job": "a1", "exit": 0}, "out/a1/report.md": "# from runner\n"})
    opened.pilot("report", "a1", check=True)
    assert (opened.agent / "pilot-runs" / "a1" / "report.md").read_text() == "# from runner\n"


def test_report_without_matplotlib(opened, tmp_path, monkeypatch):
    stub = tmp_path / "stub" / "matplotlib"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text("raise ImportError('no matplotlib here')\n")
    monkeypatch.setenv("PYTHONPATH", f"{stub.parent}{os.pathsep}{os.environ['PYTHONPATH']}")
    opened.runner_writes({"out/a1.done": {"job": "a1", "exit": 0}})
    r = opened.pilot("report", "a1")
    assert r.returncode != 0 and "pip install matplotlib" in r.stderr
