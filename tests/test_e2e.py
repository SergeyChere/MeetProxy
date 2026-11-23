"""End to end: the real runner in its own process (no git identity, like a fresh Colab VM), the
real CLI as the agent, a bare repo as GitHub, a fake nvidia-smi as the GPU. Each test is a story
a user goes through."""
import json, os, stat, subprocess, sys, time, zipfile

import pytest

from conftest import ROOT, git


def wait_for(cond, timeout=30, every=0.3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(every)
    return False


@pytest.fixture
def pilot_on_path(tmp_path, monkeypatch):
    """`pilot` as a command, as pip would install it."""
    b = tmp_path / "pbin"
    b.mkdir()
    shim = b / "pilot"
    shim.write_text(f"#!/bin/sh\nexec {sys.executable} -m pilot.cli \"$@\"\n")
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{b}{os.pathsep}{os.environ['PATH']}")


def test_new_user_installs_the_skill_and_runs_a_benchmark(world, fake_gpu, pilot_on_path):
    """Skill zip → setup → notebook started → template job → gpu line → history → charts →
    export → stop. The path a first-time user takes."""
    zp = subprocess.run(["bash", os.path.join(ROOT, "scripts", "build_skill.sh")],
                        capture_output=True, text=True, check=True).stdout.splitlines()[0]
    skills = world.agent / ".claude" / "skills"
    zipfile.ZipFile(zp).extractall(skills)
    sk = skills / "colab-pilot"
    assert (sk / "SKILL.md").read_text().startswith("---\nname: colab-pilot\n")

    setup = subprocess.run(["bash", str(sk / "scripts" / "setup.sh")], cwd=world.agent,
                           capture_output=True, text=True)
    assert setup.returncode == 0 and "No runner has connected yet" in setup.stdout

    world.start_runner()
    world.wait_runner_state("gpu: Tesla T4")

    r = world.run_job("s01_template", (sk / "templates" / "job.sh").read_text())
    assert r.returncode == 0, r.stdout + r.stderr
    d = world.done("s01_template")
    assert d["exit"] == 0 and d["gpu"].startswith("Tesla T4") and d["code"].startswith("code ")
    assert len(world.out("s01_template", "results.csv").read_text().splitlines()) == 7
    assert world.out("s01_template", "gpu.csv").exists()
    agent_view = json.loads(r.stderr.strip().splitlines()[-1])
    assert agent_view["gpu_check"].startswith("gpu ok: util 97%") and "gpu_stats" not in agent_view
    assert r.stdout.rstrip().splitlines()[-1].startswith("gpu ok")        # last log line

    hist = world.pilot("history").stdout
    assert "s01_template" in hist and "T4" in hist

    r = world.run_job("s02_charts", "# timeout: 60\n# gpu: any\n# charts: on\nsleep 2\necho done\n")
    assert r.returncode == 0
    assert "report" not in (r.stdout + r.stderr).lower()                  # the agent never hears of it
    md = world.out("s02_charts", "report.md").read_text()
    assert "![GPU telemetry](charts/gpu.svg)" in md
    assert world.out("s02_charts", "charts", "gpu.svg").stat().st_size > 1000
    assert "[s02_charts](s02_charts/report.md)" in world.out("history.md").read_text()
    assert git(world.gh, "show", "pilot:out/s02_charts/report.md").startswith("# s02_charts")

    assert "exported 2 job(s)" in world.pilot("export", "--all").stdout
    assert (world.agent / "pilot-runs" / "s02_charts" / "charts" / "gpu.svg").exists()

    world.pilot("stop", check=True)
    world.wait_runner_exit()
    assert "Runner exited (stopped)" in world.pilot("status").stdout


def test_unhealthy_gpu_is_reported_in_one_line(world, fake_gpu):
    fake_gpu("bad")
    world.pilot("init", check=True)
    world.start_runner()
    world.wait_runner_state("runner: idle")
    r = world.run_job("hot", "# timeout: 60\n# gpu: any\nsleep 12\n")
    view = json.loads(r.stderr.strip().splitlines()[-1])
    assert view["gpu_check"].startswith("gpu WARN: ")
    for want in ("idle", "mem peak", "thermal throttle"):
        assert want in view["gpu_check"]
    st = world.done("hot")["gpu_stats"]
    assert st["thermal_throttle_pct"] > 0 and st["mem_peak_mb"] == 14500
    assert "thermal throttle" in world.pilot("history").stdout


def test_job_control_on_a_gpu(world, fake_gpu, monkeypatch):
    """Code updates, branches, exit codes, secrets, timeouts, STOP mid-job, queueing, GPU checks,
    telemetry off, streaming logs."""
    world.pilot("init", check=True)
    world.start_runner(MY_TOKEN="supersecret123")
    world.wait_runner_state("runner: idle")

    r = world.run_job("c1", "# gpu: any\ncat version.txt\necho t=$MY_TOKEN\n")
    assert "v1" in r.stdout and "t=***" in r.stdout and "supersecret123" not in r.stdout

    world.commit_push("v2", **{"version.txt": "v2\n"})
    assert "v2" in world.run_job("c2", "cat version.txt\n").stdout

    git(world.agent, "checkout", "-q", "-b", "claude/feat")
    world.commit_push("v3", **{"version.txt": "v3\n"})
    r = world.run_job("c3", "cat version.txt\n")
    assert "v3" in r.stdout and "(claude/feat)" in world.done("c3")["code"]

    assert world.run_job("c4", "exit 7\n").returncode == 7

    world.run_job("c5", "# timeout: 2\nsleep 300 & sleep 300\n")
    assert world.done("c5")["error"] == "timeout"
    assert subprocess.run(["pgrep", "-f", "sleep 300"], capture_output=True).returncode != 0

    world.run_job("c6", "# gpu: A100\necho no\n")
    assert "wrong gpu: want A100" in world.done("c6")["error"]

    world.run_job("c7", "# telemetry: off\n# gpu: any\necho x\n")
    assert "gpu_stats" not in world.done("c7") and not world.out("c7", "gpu.csv").exists()

    # a long job streams its log; a second job queues behind it
    world.pilot("send", "c8", "-", stdin="for i in $(seq 8); do echo tick $i; sleep 1; done\n",
                check=True)
    assert wait_for(lambda: "tick" in world.pilot("logs", "c8").stdout)    # visible before the end
    world.pilot("send", "c9", "-", stdin="echo second\n", check=True)
    assert world.pilot("wait", "c9", "--follow", "--poll", "0.5").stdout.count("second") >= 1
    assert "tick 8" in world.out("c8.log").read_text()

    # STOP while a job runs: the job is killed, the runner exits
    world.pilot("send", "c10", "-", stdin="sleep 120\n", check=True)
    assert wait_for(lambda: "running c10" in world.pilot("status").stdout)
    world.pilot("stop", check=True)
    world.wait_runner_exit()
    assert world.done("c10")["error"] == "stopped"

    # the next evening: a new runner is not blocked by yesterday's STOP
    world.start_runner()
    assert "again" in world.run_job("c11", "echo again\n").stdout
    assert len(world.pilot("history", "--last", "0").stdout.splitlines()) == 12   # header + 11


def test_cpu_only_runtime(world, no_gpu):
    world.pilot("init", check=True)
    world.start_runner()
    world.wait_runner_state("runner: idle")
    world.run_job("g", "# gpu: any\necho no\n")
    assert "wrong gpu: want any, have none" in world.done("g")["error"]
    r = world.run_job("p", "echo plain\n")
    assert r.returncode == 0 and "plain" in r.stdout and "gpu_stats" not in world.done("p")
    assert "gpu_check" not in r.stderr


def test_runner_exits_when_idle_and_status_says_so(world, fake_gpu):
    world.pilot("init", check=True)
    world.start_runner(IDLE_MIN="0.03")
    world.wait_runner_exit()
    assert "Runner exited (idle-exit)" in world.pilot("status").stdout


def test_charts_for_every_job_with_env(world, fake_gpu):
    world.pilot("init", check=True)
    world.start_runner(PILOT_CHARTS="1")
    world.wait_runner_state("runner: idle")
    world.run_job("e1", "# gpu: any\necho x\n")
    assert world.out("e1", "report.md").exists() and world.out("history.md").exists()


def test_runner_killed_mid_job_leaves_partial_results(world, fake_gpu):
    """The runtime dies (Colab disconnect): what was pushed so far stays readable."""
    world.pilot("init", check=True)
    world.start_runner()
    world.wait_runner_state("runner: idle")
    world.pilot("send", "k1", "-", stdin=(
        "echo v,i > $PILOT_OUT/results.csv\n"
        "for i in $(seq 100); do echo r,$i >> $PILOT_OUT/results.csv; echo step $i; sleep 0.2; done\n"),
        check=True)
    assert wait_for(lambda: (world.pilot("logs", "k1").stdout.count("step") >= 5), timeout=30)
    world.stop_runner()                                   # kill -9: no goodbye push
    world.sync()
    assert world.out("k1", "results.csv").read_text().startswith("v,i\nr,1")
    assert not world.out("k1.done").exists()
    assert "running k1" in world.pilot("status").stdout   # last heartbeat; silence check covers the rest
