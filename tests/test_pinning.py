"""A job runs the commit the agent submitted, not whatever its branch points to at run time."""
import json, os, subprocess

import pytest

from conftest import git
from meetproxy import runner as R


@pytest.fixture
def rn(world, no_gpu):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    work = world.tmp / "work"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    return R.Runner(path, str(work))


def submitted(world, name):
    return git(world.gh, "show", f"meetproxy:cmd/{name}.sh")


def test_send_pins_the_full_head_sha(opened):
    head = git(opened.agent, "rev-parse", "HEAD")
    opened.meet("send", "p1", "-", stdin="cat version.txt\n", check=True)
    body = submitted(opened, "p1")
    assert f"# commit: {head}" in body.splitlines()[:3] and "# branch: main" in body


def test_explicit_commit_header_is_kept(opened):
    opened.meet("send", "p2", "-", stdin="# commit: " + "a" * 40 + "\ntrue\n", check=True)
    assert submitted(opened, "p2").count("# commit:") == 1


def test_detached_head_is_pinned_too(opened):
    git(opened.agent, "checkout", "-q", "--detach")
    opened.meet("send", "p3", "-", stdin="true\n", check=True)
    body = submitted(opened, "p3")
    assert "# commit: " in body and "# branch:" not in body


def test_unpushed_head_is_announced_as_not_runnable(opened):
    (opened.agent / "version.txt").write_text("local\n")
    git(opened.agent, "commit", "-qam", "local only")
    r = opened.meet("send", "p4", "-", stdin="true\n")
    assert "push it" in r.stderr and "will not run" in r.stderr


def test_branch_advanced_after_submit_still_runs_the_submitted_commit(world, rn):
    """Submit at A, push B to the same branch before the runner picks the job: A runs."""
    a = git(world.agent, "rev-parse", "HEAD")
    open(rn.mb.p("cmd", "j.sh"), "w").write(f"# branch: main\n# commit: {a}\ncat version.txt\n")
    world.commit_push("v2", **{"version.txt": "v2\n"})            # the branch moves on
    rn.run_job("j")
    d = json.load(open(rn.mb.p("out", "j.done")))
    assert d["exit"] == 0 and d["commit"] == a and d["pinned"] is True
    assert "v1" in open(rn.mb.p("out", "j.log")).read()


def test_commit_missing_on_remote_refuses_the_job(world, rn):
    ghost = "0123456789abcdef0123456789abcdef01234567"
    open(rn.mb.p("cmd", "g.sh"), "w").write(f"# commit: {ghost}\necho RAN\n")
    rn.run_job("g")
    d = json.load(open(rn.mb.p("out", "g.done")))
    assert d["exit"] == -3 and d["error"].startswith("commit not found")
    assert "RAN" not in open(rn.mb.p("out", "g.log")).read() if os.path.exists(rn.mb.p("out", "g.log")) else True


@pytest.mark.parametrize("bad", ["abc", "z" * 40, "1234567", "a" * 41])
def test_malformed_commit_header_is_rejected(rn, bad):
    open(rn.mb.p("cmd", "m.sh"), "w").write(f"# commit: {bad}\necho RAN\n")
    rn.run_job("m")
    d = json.load(open(rn.mb.p("out", "m.done")))
    assert d["exit"] == -3 and d["error"].startswith("bad commit header")


def test_legacy_job_without_commit_is_marked_unpinned(world, rn):
    open(rn.mb.p("cmd", "l.sh"), "w").write("# branch: main\ntrue\n")
    rn.run_job("l")
    d = json.load(open(rn.mb.p("out", "l.done")))
    assert d["exit"] == 0 and d["pinned"] is False and "branch head at run time" in d["code"]


def test_end_to_end_pinning_through_the_cli(world, no_gpu):
    """The agent sends at v1, pushes v2 before the runner starts: the log shows v1."""
    world.meet("init", check=True)
    world.meet("send", "e1", "-", stdin="cat version.txt\n", check=True)
    world.commit_push("v2", **{"version.txt": "v2\n"})
    world.start_runner()
    r = world.meet("wait", "e1", "--follow", "--poll", "0.5", "--timeout", "60")
    assert r.returncode == 0 and "v1" in r.stdout and "v2" not in r.stdout
    assert world.done("e1")["pinned"] is True
