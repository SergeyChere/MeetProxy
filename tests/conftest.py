"""Shared fixtures: an isolated git world (a bare repo plays GitHub), a fake GPU, a runner process,
and a `pilot` helper that runs the real CLI as the agent would."""
import json, os, shutil, signal, stat, subprocess, sys, time
from datetime import datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def git_isolation(monkeypatch, tmp_path):
    """No user/system git config, a fixed identity; nothing leaks between tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@t"),
                 ("GIT_COMMITTER_NAME", "t"), ("GIT_COMMITTER_EMAIL", "t@t")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("PILOT_DIR", raising=False)
    monkeypatch.delenv("PILOT_CHARTS", raising=False)
    monkeypatch.setenv("PYTHONPATH", ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode:
        raise AssertionError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


@pytest.fixture
def fake_gpu(tmp_path, monkeypatch):
    """Put a fake nvidia-smi first on PATH. Returns a setter for the mode."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    dst = bindir / "nvidia-smi"
    shutil.copy(os.path.join(TESTS, "fake_nvidia_smi.py"), dst)
    dst.chmod(dst.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GPU_COUNTER", str(tmp_path / "gpu_counter"))
    monkeypatch.setenv("FAKE_GPU_MODE", "ok")

    def mode(m):
        monkeypatch.setenv("FAKE_GPU_MODE", m)
    return mode


@pytest.fixture
def no_gpu(tmp_path, monkeypatch):
    """PATH without any nvidia-smi."""
    bindir = tmp_path / "nogpu"
    bindir.mkdir()
    keep = [p for p in os.environ["PATH"].split(os.pathsep)
            if not os.path.exists(os.path.join(p, "nvidia-smi"))]
    monkeypatch.setenv("PATH", os.pathsep.join([str(bindir)] + keep))


class World:
    """GitHub (bare repo), the agent's clone, and helpers around them."""

    def __init__(self, tmp):
        self.tmp = tmp
        self.gh = tmp / "gh.git"
        self.agent = tmp / "agent"
        self.colab = tmp / "colab"
        self.runner = None
        self.runner_log = tmp / "runner.out"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.gh)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.gh), str(self.agent)], check=True,
                       capture_output=True)
        (self.agent / "version.txt").write_text("v1\n")
        git(self.agent, "add", ".")
        git(self.agent, "commit", "-qm", "v1")
        git(self.agent, "push", "-q", "origin", "main")

    # --- the agent side: the real CLI, as a subprocess in the project dir ---
    def pilot(self, *args, stdin=None, check=False, timeout=120):
        r = subprocess.run([sys.executable, "-m", "pilot.cli", *args], cwd=self.agent,
                           input=stdin, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode:
            raise AssertionError(f"pilot {args} -> {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def run_job(self, name, script, timeout=90):
        return self.pilot("run", name, "-", "--poll", "0.5", "--timeout", str(timeout),
                          stdin=script, timeout=timeout + 30)

    def commit_push(self, msg, **files):
        for k, v in files.items():
            (self.agent / k).write_text(v)
        git(self.agent, "add", ".")
        git(self.agent, "commit", "-qm", msg)
        git(self.agent, "push", "-q", "origin", "HEAD")

    def out(self, *p):
        return self.agent / ".pilot" / "out" / os.path.join(*p)

    def sync(self):
        """Pull the agent's mailbox clone, as any pilot command would."""
        git(self.agent / ".pilot", "pull", "-q", "--rebase", check=False)

    def done(self, job):
        if not self.out(job + ".done").exists():
            self.sync()
        return json.loads(self.out(job + ".done").read_text())

    # --- the Colab side: the real runner in its own process, with no git identity ---
    def start_runner(self, **env):
        home = self.tmp / f"home{time.time_ns()}"
        home.mkdir()
        e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_AUTHOR")
             and not k.startswith("GIT_COMMITTER")}
        e.update(HOME=str(home), XDG_CONFIG_HOME=str(home), POLL_S="0.5", PUSH_S="1",
                 HEARTBEAT_S="2", IDLE_MIN="5", GPU_SAMPLE_S="0.2")
        e.update({k: str(v) for k, v in env.items()})
        code = (f"import pilot.runner as r; r.start({str(self.gh)!r}, "
                f"{str(self.colab / 'proj')!r}, {str(self.colab / 'mb')!r})")
        self.runner = subprocess.Popen([sys.executable, "-c", code], env=e,
                                       stdout=open(self.runner_log, "a"), stderr=subprocess.STDOUT,
                                       start_new_session=True)
        return self.runner

    def wait_runner_state(self, want, timeout=30):
        t0 = time.time()
        while time.time() - t0 < timeout:
            st = self.pilot("status").stdout
            if want in st:
                return st
            time.sleep(0.5)
        raise AssertionError(f"runner never reached {want!r}; last status:\n{st}\n"
                             f"runner log:\n{self.runner_log.read_text()}")

    def wait_runner_exit(self, timeout=40):
        try:
            return self.runner.wait(timeout)
        except subprocess.TimeoutExpired:
            raise AssertionError("runner did not exit\n" + self.runner_log.read_text())

    def stop_runner(self):
        if self.runner and self.runner.poll() is None:
            try:
                os.killpg(self.runner.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.runner.wait(10)

    # --- writing to the mailbox as the runner would, without a runner ---
    def runner_writes(self, files, msg="fake runner"):
        mb = self.tmp / "fake_runner_mb"
        if not mb.exists():
            subprocess.run(["git", "clone", "-q", "-b", "pilot", str(self.gh), str(mb)],
                           check=True, capture_output=True)
        git(mb, "pull", "-q", "--rebase")
        for k, v in files.items():
            p = mb / k
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(v if isinstance(v, str) else json.dumps(v))
        git(mb, "add", "-A")
        git(mb, "commit", "-qm", msg)
        git(mb, "push", "-q")

    def heartbeat(self, state="idle", minutes_ago=0, job=None, gpu="Tesla T4, 15360 MiB, 535"):
        t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
        self.runner_writes({"out/runner.json": {"state": state, "job": job, "gpu": gpu, "time": t}})


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.stop_runner()


@pytest.fixture
def opened(world):
    """A world with the mailbox already opened by the agent."""
    world.pilot("init", check=True)
    return world
