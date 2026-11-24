"""Runner pieces in isolation: parsing, redaction, mailbox, job selection, STOP, checkout,
finish/history, reports, loop exits, colab_start messages."""
import json, os, subprocess, sys, threading, time, types

import pytest

from conftest import git
from pilot import runner as R


# ---------- small helpers ----------

def test_header_reads_only_the_first_20_lines():
    s = "# timeout: 30\n# gpu: T4\n" + "x\n" * 30 + "# charts: on\n"
    assert R.header(s, "timeout") == "30"
    assert R.header(s, "gpu") == "T4"
    assert R.header(s, "charts") is None
    assert R.header("#   branch:   feat/x  \n", "branch") == "feat/x"


def test_secrets_and_redact(monkeypatch):
    monkeypatch.setenv("MY_API_KEY", "abcdefgh123")
    monkeypatch.setenv("SHORT_TOKEN", "abc")          # too short to be worth masking
    monkeypatch.setenv("HARMLESS", "abcdefgh999")
    vals = R.secrets()
    assert "abcdefgh123" in vals and "abc" not in vals and "abcdefgh999" not in vals
    assert R.redact("key=abcdefgh123 x") == "key=*** x"
    assert R.redact("a b", ["a"]) == "*** b"


def test_gpu_info(fake_gpu):
    assert R.gpu_info().startswith("Tesla T4")
    fake_gpu("broken")
    assert R.gpu_info() == "none"


def test_gpu_info_without_nvidia_smi(no_gpu):
    assert R.gpu_info() == "none"


def test_git_error_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "supersecret999")
    with pytest.raises(RuntimeError) as e:
        R.git(str(tmp_path), "clone", "https://x-access-token:supersecret999@invalid.invalid/x")
    assert "supersecret999" not in str(e.value)


# ---------- mailbox ----------

def test_open_mailbox_creates_then_clones(world):
    a = R.open_mailbox(str(world.gh), str(world.tmp / "mb1"))
    assert git(world.gh, "rev-parse", "--verify", "pilot")
    assert os.path.isfile(os.path.join(a, "cmd", ".keep"))
    b = R.open_mailbox(str(world.gh), str(world.tmp / "mb2"))       # branch exists: plain clone
    assert git(b, "log", "-1", "--format=%s") == "colab-pilot mailbox"
    assert git(b, "config", "user.name") == "colab-pilot"


def test_open_mailbox_bad_url(tmp_path):
    with pytest.raises(RuntimeError, match="clone failed"):
        R.open_mailbox(str(tmp_path / "missing.git"), str(tmp_path / "mb"))


def test_mailbox_push_nothing_to_commit_and_live_files(world):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    mb = R.Mailbox(path)
    assert mb.push("noop") is True                               # nothing staged
    live = world.tmp / "live"
    (live / "j").mkdir(parents=True)
    (live / "j" / "r.csv").write_text("1\n")
    (live / "j.log").write_text("hello\n")
    mb.live = {"j": str(live / "j"), "j.log": str(live / "j.log"), "gone.log": str(live / "x")}
    assert mb.push("live") is True
    assert (world.tmp / "mb" / "out" / "j" / "r.csv").read_text() == "1\n"
    assert git(world.gh, "show", "pilot:out/j.log") == "hello"


def test_mailbox_push_gives_up_with_a_warning(world, capsys, monkeypatch):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    mb = R.Mailbox(path)
    git(path, "remote", "set-url", "origin", str(world.tmp / "nowhere.git"))
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    open(os.path.join(path, "out", "x"), "w").write("1")
    assert mb.push("x") is False
    assert "push failed" in capsys.readouterr().out


# ---------- runner state ----------

@pytest.fixture
def rn(world, no_gpu):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    work = world.tmp / "work"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    return R.Runner(path, str(work))


def test_next_job_in_name_order_skipping_done(rn):
    cmd, out = rn.mb.p("cmd"), rn.mb.p("out")
    for n in ("b2", "a1", "c3"):
        open(os.path.join(cmd, n + ".sh"), "w").write("true\n")
    open(os.path.join(cmd, "STOP"), "w").write("0")
    assert rn.next_job() == "a1"
    open(os.path.join(out, "a1.done"), "w").write("{}")
    assert rn.next_job() == "b2"


def test_next_job_without_cmd_dir(rn):
    os.rmdir(rn.mb.p("cmd")) if not os.listdir(rn.mb.p("cmd")) else None
    import shutil
    shutil.rmtree(rn.mb.p("cmd"))
    assert rn.next_job() is None


def test_stop_only_stops_runners_started_before_it(rn):
    stop = rn.mb.p("cmd", "STOP")
    assert rn.stopped() is False
    open(stop, "w").write(f"{rn.t_start - 100:.0f}\n")          # stale STOP from yesterday
    assert rn.stopped() is False
    open(stop, "w").write(f"{rn.t_start + 5:.0f}\n")
    assert rn.stopped() is True
    open(stop, "w").write("garbage")
    assert rn.stopped() is False


def test_update_workdir(rn, world):
    msg = rn.update_workdir()
    assert msg.startswith("code ") and "v1" in msg and "(default branch)" in msg
    assert "CHECKOUT FAILED" in rn.update_workdir("no-such-branch")
    rn.workdir = str(world.tmp)
    assert rn.update_workdir() == "workdir is not a git repo"


def test_workdir_falls_back_to_cwd(world, no_gpu):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    assert R.Runner(path, str(world.tmp / "missing")).workdir == os.getcwd()


def test_finish_writes_done_and_history(rn):
    rn.finish("j1", {"job": "j1", "exit": 0, "seconds": 1.5, "code": "code abc1234 msg (main)"})
    assert json.load(open(rn.mb.p("out", "j1.done")))["exit"] == 0
    hist = open(rn.mb.p("out", "history.csv")).read().splitlines()
    assert hist[0].startswith("job,") and hist[1].startswith("j1,") and "abc1234" in hist[1]


def test_history_failure_is_not_fatal(rn, capsys):
    os.makedirs(rn.mb.p("out", "history.csv"))                    # a directory: append fails
    rn.finish("j1", {"job": "j1", "exit": 0})
    assert os.path.exists(rn.mb.p("out", "j1.done"))
    assert "history not written" in capsys.readouterr().out


def test_report_failure_is_not_fatal(rn, capsys, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no fonts")
    monkeypatch.setattr(R.report, "job_report", boom)
    rn.make_reports(rn.mb.p("out", "j"), {"job": "j"}, None)
    assert "charts skipped: no fonts" in capsys.readouterr().out


def test_heartbeat_file(rn):
    rn.state, rn.job = "running", "j9"
    rn.heartbeat()
    hb = json.load(open(rn.mb.p("out", "runner.json")))
    assert hb["state"] == "running" and hb["job"] == "j9" and hb["version"] == R.VERSION


def test_wrong_gpu_is_refused_and_recorded(rn):
    open(rn.mb.p("cmd", "g1.sh"), "w").write("# gpu: any\necho hi\n")
    rn.run_job("g1")
    d = json.load(open(rn.mb.p("out", "g1.done")))
    assert d["exit"] == -2 and "wrong gpu" in d["error"]
    assert "g1," in open(rn.mb.p("out", "history.csv")).read()


def test_run_job_basics_without_gpu(rn, monkeypatch):
    monkeypatch.setenv("SOME_PASSWORD", "hunter2hunter2")
    rn.secrets = R.secrets()
    open(rn.mb.p("cmd", "j.sh"), "w").write(
        "echo pw=$SOME_PASSWORD\necho $COLAB_PILOT $PILOT_JOB\necho 7 > $PILOT_OUT/r.csv\nexit 4\n")
    rn.run_job("j")
    d = json.load(open(rn.mb.p("out", "j.done")))
    log = open(rn.mb.p("out", "j.log")).read()
    assert d["exit"] == 4 and "gpu_stats" not in d                 # no GPU: no telemetry
    assert "pw=***" in log and "hunter2" not in log and "1 j" in log
    assert open(rn.mb.p("out", "j", "r.csv")).read() == "7\n"


# ---------- the loop's exits ----------

def _loop(rn, monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    r = R.Runner(rn.mb.path, rn.workdir)
    r.loop()
    return json.load(open(r.mb.p("out", "runner.json")))


def test_loop_idle_exit(rn, monkeypatch):
    hb = _loop(rn, monkeypatch, POLL_S=0.1, IDLE_MIN=0.01, HEARTBEAT_S=0)
    assert hb["state"] == "idle-exit"


def test_loop_budget_exit(rn, monkeypatch):
    hb = _loop(rn, monkeypatch, POLL_S=0.1, MAX_HOURS=0.0002, IDLE_MIN=100)
    assert hb["state"] == "budget"


def test_loop_keyboard_interrupt(rn, monkeypatch):
    monkeypatch.setenv("POLL_S", "0.1")
    r = R.Runner(rn.mb.path, rn.workdir)
    calls = {"n": 0}
    real = r.next_job

    def interrupt():
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real()
    r.next_job = interrupt
    r.loop()
    assert json.load(open(r.mb.p("out", "runner.json")))["state"] == "interrupted"


def test_main_uses_env(rn, monkeypatch):
    monkeypatch.setenv("PILOT_MAILBOX", rn.mb.path)
    monkeypatch.setenv("PILOT_WORKDIR", rn.workdir)
    monkeypatch.setenv("IDLE_MIN", "0.005")
    monkeypatch.setenv("POLL_S", "0.1")
    R.main()
    assert json.load(open(rn.mb.p("out", "runner.json")))["state"] == "idle-exit"


def test_start_updates_existing_project(world, no_gpu, monkeypatch):
    calls = []
    monkeypatch.setattr(R.Runner, "loop", lambda self: calls.append(self.workdir))
    R.start(str(world.gh), str(world.tmp / "proj"), str(world.tmp / "mb"))
    R.start(str(world.gh), str(world.tmp / "proj"), str(world.tmp / "mb"))   # second time: pull
    assert calls == [str(world.tmp / "proj")] * 2
    with pytest.raises(RuntimeError, match="clone failed"):
        R.start(str(world.tmp / "nope.git"), str(world.tmp / "p2"), str(world.tmp / "mb2"))


# ---------- colab_start: every message a human can see ----------

def _fake_colab(monkeypatch, secrets=None, error=None):
    userdata = types.SimpleNamespace()

    def get(name):
        if error:
            raise type(error, (Exception,), {})()
        if secrets and name in secrets:
            return secrets[name]
        raise type("SecretNotFoundError", (Exception,), {})()
    userdata.get = get
    colab = types.ModuleType("google.colab")
    colab.userdata = userdata
    google = types.ModuleType("google")
    google.colab = colab
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.colab", colab)


@pytest.mark.parametrize("repo", ["", "owner/repo", "not a repo", "a/b/c"])
def test_colab_start_rejects_bad_repo(repo, capsys):
    R.colab_start(repo)
    assert "put your project's repository into REPO" in capsys.readouterr().out


def test_colab_start_without_token_outside_colab(monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setitem(sys.modules, "google.colab", None)
    R.colab_start("alice/kernels")
    out = capsys.readouterr().out
    assert "no GitHub token" in out and "alice/kernels" in out and "Traceback" not in out


def test_colab_start_secret_without_notebook_access(monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    _fake_colab(monkeypatch, error="NotebookAccessError")
    R.colab_start("alice/kernels")
    assert "Notebook access" in capsys.readouterr().out


def test_colab_start_reads_fallback_secret_and_starts(monkeypatch, capsys, no_gpu):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    _fake_colab(monkeypatch, secrets={"GITHUB_TOKEN": "tok12345678"})
    seen = {}
    monkeypatch.setattr(R, "start", lambda url, wd, mb: seen.update(url=url, wd=wd, mb=mb))
    R.colab_start("alice/kernels", root="/content")
    assert seen["url"] == "https://x-access-token:tok12345678@github.com/alice/kernels.git"
    assert seen["wd"] == "/content/kernels" and seen["mb"] == "/content/.pilot-mailbox"
    assert "WARNING: no GPU" in capsys.readouterr().out
    assert os.environ["GH_TOKEN"] == "tok12345678"


def test_colab_start_clone_failure_is_one_redacted_message(monkeypatch, capsys, fake_gpu):
    monkeypatch.setenv("GH_TOKEN", "tok_secret_123")

    def fail(url, wd, mb):
        raise RuntimeError(f"clone failed: remote: Repository not found {url}")
    monkeypatch.setattr(R, "start", fail)
    R.colab_start("alice/kernels")
    out = capsys.readouterr().out
    assert "tok_secret_123" not in out and "Check that the token has access to alice/kernels" in out


def test_exit_code_is_never_lost_to_the_cleanup_kill(rn):
    """Regression: the group kill used to race bash's exit and report -9 for a good job."""
    for i in range(15):
        open(rn.mb.p("cmd", f"e{i:02d}.sh"), "w").write("echo a\necho b\nexit 0\n")
        rn.run_job(f"e{i:02d}")
        assert json.load(open(rn.mb.p("out", f"e{i:02d}.done")))["exit"] == 0, i


def test_stray_background_process_is_killed_but_exit_kept(rn):
    open(rn.mb.p("cmd", "bg.sh"), "w").write("sleep 300 >/dev/null 2>&1 &\nexit 5\n")
    rn.run_job("bg")
    assert json.load(open(rn.mb.p("out", "bg.done")))["exit"] == 5
    assert subprocess.run(["pgrep", "-f", "sleep 300"], capture_output=True).returncode != 0


def test_interrupt_during_a_job_is_recorded_and_re_raised(rn):
    import _thread
    open(rn.mb.p("cmd", "i.sh"), "w").write("echo start\nsleep 30\n")
    threading.Timer(1.0, _thread.interrupt_main).start()
    with pytest.raises(KeyboardInterrupt):
        rn.run_job("i")
    d = json.load(open(rn.mb.p("out", "i.done")))
    assert d["error"] == "interrupted"
    assert subprocess.run(["pgrep", "-f", "sleep 30"], capture_output=True).returncode != 0


def test_telemetry_crash_does_not_lose_the_job(world, fake_gpu, monkeypatch):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    work = world.tmp / "work"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    r = R.Runner(path, str(work))

    def boom(self):
        raise RuntimeError("sampler broke")
    monkeypatch.setattr(R.telemetry.Sampler, "stop", boom)
    open(r.mb.p("cmd", "t.sh"), "w").write("echo fine\n")
    r.run_job("t")
    d = json.load(open(r.mb.p("out", "t.done")))
    assert d["exit"] == 0 and d["gpu_stats"]["error"] == "sampler broke"


def test_seed_from_pushed_prefers_the_larger_copy(tmp_path):
    from pilot.runner import seed_from_pushed
    pushed, live = tmp_path / "pushed", tmp_path / "live"
    (pushed / "charts").mkdir(parents=True)
    (pushed / "results.csv").write_text("h\nline0\nline1\n")
    (pushed / "charts" / "a.svg").write_text("<svg/>")
    (pushed / "small.txt").write_text("x")
    live.mkdir()
    (live / "results.csv").write_text("h\n")          # stale copy from an earlier attempt
    (live / "small.txt").write_text("newer and longer")  # local copy already ahead
    seed_from_pushed(str(pushed), str(live))
    assert (live / "results.csv").read_text() == "h\nline0\nline1\n"
    assert (live / "charts" / "a.svg").read_text() == "<svg/>"
    assert (live / "small.txt").read_text() == "newer and longer"
