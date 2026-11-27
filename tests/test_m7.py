"""M7: quick fixes to the current mailbox flow — bad headers, git timeouts, stuck runs,
MAX_HOURS, withheld secret files, pinned installs, a reliable resume marker, the notebook cell."""
import json, os, re, subprocess, sys, time

import pytest

from conftest import ROOT, git
from meetproxy import runner as R


@pytest.fixture
def rn(world, no_gpu):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    work = world.tmp / "work"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    return R.Runner(path, str(work))


def done(rn, name):
    return json.load(open(rn.mb.p("out", name + ".done")))


# --- a bad header fails that job, not the runner ---

@pytest.mark.parametrize("bad", ["abc", "-5", "1e400", "nan"])
def test_bad_timeout_header_fails_only_that_job(rn, bad):
    open(rn.mb.p("cmd", "b.sh"), "w").write(f"# timeout: {bad}\necho RAN\n")
    rn.run_job("b")
    d = done(rn, "b")
    assert d["exit"] == -4 and d["error"].startswith("bad header")
    open(rn.mb.p("cmd", "c.sh"), "w").write("echo next\n")
    rn.run_job("c")
    assert done(rn, "c")["exit"] == 0


# --- every git command is bounded ---

def test_git_timeout_returns_an_error_instead_of_hanging(monkeypatch, tmp_path):
    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout"))
    monkeypatch.setattr(R.subprocess, "run", hang)
    r = R.git(str(tmp_path), "fetch", check=False)
    assert r.returncode == 124 and "timed out" in r.stderr
    with pytest.raises(RuntimeError, match="timed out"):
        R.git(str(tmp_path), "fetch")


def test_every_git_call_in_the_runner_has_a_timeout(monkeypatch, tmp_path):
    seen = []
    real = subprocess.run

    def spy(*a, **k):
        seen.append(k.get("timeout"))
        return real(*a, **k)
    monkeypatch.setattr(R.subprocess, "run", spy)
    R.git(str(tmp_path), "--version", check=False)
    R.run_git(["git", "--version"])
    assert seen and all(t and t > 0 for t in seen)


def test_client_git_calls_have_a_timeout(monkeypatch):
    from meetproxy import cli
    seen = []
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: seen.append(k.get("timeout")) or
                        subprocess.CompletedProcess(a[0], 0, "", ""))
    cli.sh("git", "--version")
    assert seen == [float(os.environ.get("MEET_GIT_TIMEOUT_S", 180))]


# --- a job never outlives MAX_HOURS ---

def test_job_timeout_is_capped_by_what_is_left_of_max_hours(rn):
    rn.max_s = 3
    rn.t_start = time.time()
    open(rn.mb.p("cmd", "long.sh"), "w").write("# timeout: 3600\nsleep 60\n")
    t0 = time.time()
    rn.run_job("long")
    d = done(rn, "long")
    assert time.time() - t0 < 30
    assert d["error"] == "timeout" and d["timeout_capped"] is True


def test_job_without_timeout_is_capped_too(rn):
    rn.max_s = 3
    rn.t_start = time.time()
    open(rn.mb.p("cmd", "nt.sh"), "w").write("sleep 60\n")
    rn.run_job("nt")
    d = done(rn, "nt")
    assert d["error"] == "timeout" and d["timeout_capped"] is True


# --- a result file with a secret is withheld, not rewritten ---

def test_result_file_with_a_secret_is_withheld_and_reported(rn, monkeypatch):
    secret = "ghp_" + "S" * 30
    rn.secrets = rn.mb.secrets = [secret]
    open(rn.mb.p("cmd", "s.sh"), "w").write(
        f"echo clean,1 >> $MEET_OUT/results.csv\necho 'token={secret}' > $MEET_OUT/env.txt\n")
    rn.run_job("s")
    d = done(rn, "s")
    assert d["exit"] == 0 and d["withheld"] == ["s/env.txt"]
    assert not os.path.exists(rn.mb.p("out", "s", "env.txt"))
    assert open(rn.mb.p("out", "s", "results.csv")).read() == "clean,1\n"
    assert "withheld s/env.txt" in open(rn.mb.p("out", "s.log")).read()
    pushed = subprocess.run(["git", "-C", rn.mb.path, "log", "-p", "--all"], capture_output=True,
                            text=True).stdout
    assert secret not in pushed


def test_file_that_gains_a_secret_keeps_its_last_clean_copy(rn):
    secret = "ghp_" + "Q" * 30
    rn.mb.secrets = [secret]
    live = rn.mb.path + ".live"
    os.makedirs(os.path.join(live, "j"), exist_ok=True)
    f = os.path.join(live, "j", "r.csv")
    open(f, "w").write("a\n")
    rn.mb.live = {"j": os.path.join(live, "j")}
    rn.mb.sync()
    open(f, "a").write(secret + "\n")
    rn.mb.sync()
    assert open(rn.mb.p("out", "j", "r.csv")).read() == "a\n"
    assert rn.mb.withheld == {"j/r.csv"}


# --- resume decides by an attempt marker, not by file size ---

def test_resume_same_attempt_keeps_the_local_copy(tmp_path):
    pushed, live = tmp_path / "pushed", tmp_path / "live"
    pushed.mkdir(); live.mkdir()
    for d in (pushed, live):
        (d / R.ATTEMPT).write_text("a1\n")
    (pushed / "results.csv").write_text("h\nline0\nline1\n")
    (live / "results.csv").write_text("h\n")   # same attempt: local is newest even if shorter
    assert R.seed_from_pushed(str(pushed), str(live)) == "local"
    assert (live / "results.csv").read_text() == "h\n"


def test_resume_other_attempt_takes_the_pushed_copy(tmp_path):
    pushed, live = tmp_path / "pushed", tmp_path / "live"
    (pushed / "charts").mkdir(parents=True); live.mkdir()
    (pushed / R.ATTEMPT).write_text("a2\n")
    (live / R.ATTEMPT).write_text("a1\n")
    (pushed / "results.csv").write_text("h\n")
    (pushed / "charts" / "a.svg").write_text("<svg/>")
    (live / "results.csv").write_text("h\nstale but longer\n")
    (live / "leftover.txt").write_text("from a1")
    assert R.seed_from_pushed(str(pushed), str(live)) == "pushed"
    assert (live / "results.csv").read_text() == "h\n"
    assert (live / "charts" / "a.svg").read_text() == "<svg/>"
    assert not (live / "leftover.txt").exists()


def test_resume_on_a_new_machine_takes_the_pushed_copy(tmp_path):
    pushed, live = tmp_path / "pushed", tmp_path / "live"
    pushed.mkdir()
    (pushed / R.ATTEMPT).write_text("a1\n")
    (pushed / "results.csv").write_text("h\nx\n")
    assert R.seed_from_pushed(str(pushed), str(live)) == "pushed"
    assert (live / "results.csv").read_text() == "h\nx\n"


def test_every_attempt_writes_a_fresh_marker(rn):
    open(rn.mb.p("cmd", "m.sh"), "w").write("true\n")
    rn.run_job("m")
    first = open(rn.mb.p("out", "m", R.ATTEMPT)).read()
    os.remove(rn.mb.p("out", "m.done"))
    rn.run_job("m")
    assert open(rn.mb.p("out", "m", R.ATTEMPT)).read() != first


# --- status and wait notice a stuck `running` ---

def test_status_flags_a_silent_running_job(opened):
    opened.heartbeat(state="running", job="s07", minutes_ago=5)
    out = opened.meet("status").stdout
    assert "silent" in out and "s07" in out


def test_status_is_quiet_for_a_fresh_running_job(opened):
    opened.heartbeat(state="running", job="s07", minutes_ago=0)
    assert "silent" not in opened.meet("status").stdout


def test_wait_warns_when_a_running_job_goes_silent(opened, monkeypatch):
    opened.meet("send", "w1", "-", stdin="true\n", check=True)
    opened.runner_writes({"out/w1.log": "started\n"})
    opened.heartbeat(state="running", job="w1", minutes_ago=6)
    monkeypatch.setenv("MEET_SILENT_S", "0")
    r = opened.meet("wait", "w1", "--poll", "0.2", "--timeout", "2")
    assert "silent" in r.stderr


# --- installs are pinned to a release, and the notebook cell actually works ---

def version():
    return re.search(r'^version = "(.+)"', open(os.path.join(ROOT, "pyproject.toml")).read(), re.M)[1]


INSTALL_FILES = ["colab_runner.ipynb", "README.md", "meetproxy/guide.md", "meetproxy/runner.py",
                 "skill/meetproxy/SKILL.md", "skill/meetproxy/scripts/setup.sh"]


@pytest.mark.parametrize("f", INSTALL_FILES)
def test_installs_are_pinned_to_the_current_release(f):
    text = open(os.path.join(ROOT, f)).read()
    for var in ("$V", "$WANT"):                      # a shell variable holding the version
        if "@v" + var in text:
            assert re.search(rf"(V|WANT)=\"?(\$\{{MEET_VERSION:-)?{re.escape(version())}", text), f
            text = text.replace("@v" + var, "@v" + version())
    urls = re.findall(r"git\+https://github\.com/SergeyChere/MeetProxy[^\s\"'`)};\\]*", text)
    assert urls, f
    assert all(u.endswith(f"@v{version()}") for u in urls), urls


def test_runner_version_matches_the_package():
    assert R.VERSION == version()


def test_notebook_cell_starts_the_runner(monkeypatch):
    nb = json.load(open(os.path.join(ROOT, "colab_runner.ipynb")))
    code = [c for c in nb["cells"] if c["cell_type"] == "code"]
    src = "".join(code[0]["source"])
    calls = []
    monkeypatch.setattr(R, "colab_start", lambda repo: calls.append(repo))
    py = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("!"))
    exec(compile(py, "notebook", "exec"), {})
    assert calls == ["owner/repo"]
