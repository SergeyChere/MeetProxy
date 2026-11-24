"""Credentials stay out of jobs and pushed files; a job runs exactly the pushed commit or not at
all; a push is reported as done only when it reached the remote."""
import base64, json, os, subprocess, sys

import pytest

from conftest import git
from pilot import runner as R


@pytest.fixture(autouse=True)
def clean_auth(monkeypatch):
    monkeypatch.setattr(R, "EXTRA_SECRETS", [])
    for k in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GH_TOKEN"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture
def rn(world, no_gpu):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    work = world.tmp / "work"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    return R.Runner(path, str(work))


# ---------- credentials ----------

def test_use_token_sets_git_auth_without_url(monkeypatch):
    R.use_token("ghp_secret_value_123")
    assert os.environ["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    hdr = os.environ["GIT_CONFIG_VALUE_0"]
    assert base64.b64decode(hdr.split()[-1]).decode() == "x-access-token:ghp_secret_value_123"
    assert "ghp_secret_value_123" in R.secrets() and hdr.split()[-1] in R.secrets()


def test_job_environment_has_no_credentials(rn, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "ghp_secret_value_123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_other_value_456")
    monkeypatch.setenv("HF_TOKEN", "hf_user_wants_this")              # the user's own secret: kept
    R.use_token("ghp_secret_value_123")
    rn.secrets = R.secrets()
    rn.mb.secrets = rn.secrets
    open(rn.mb.p("cmd", "e.sh"), "w").write("env > $PILOT_OUT/env.txt\n")
    rn.run_job("e")
    env = open(os.path.join(rn.mb.path + ".live", "e", "env.txt")).read()
    for leak in ("GH_TOKEN=", "GITHUB_TOKEN=", "GIT_CONFIG_", "ghp_secret_value_123", "ghp_other"):
        assert leak not in env
    assert "HF_TOKEN=" in env


def test_secrets_are_masked_in_pushed_files(rn, monkeypatch, world):
    monkeypatch.setenv("MY_API_KEY", "abcdefgh123456")
    rn.secrets = R.secrets()
    rn.mb.secrets = rn.secrets
    open(rn.mb.p("cmd", "f.sh"), "w").write(
        "echo key=$MY_API_KEY > $PILOT_OUT/results.csv\n"
        "mkdir -p $PILOT_OUT/sub && printf 'x\\0abcdefgh123456' > $PILOT_OUT/sub/blob.bin\n")
    rn.run_job("f")
    assert git(world.gh, "show", "pilot:out/f/results.csv") == "key=***"
    blob = subprocess.run(["git", "-C", str(world.gh), "show", "pilot:out/f/sub/blob.bin"],
                          capture_output=True).stdout
    assert b"abcdefgh123456" not in blob and b"***" in blob


def test_colab_start_keeps_the_token_out_of_urls(monkeypatch, no_gpu):
    monkeypatch.setenv("GH_TOKEN", "tok12345678")
    seen = {}
    monkeypatch.setattr(R, "start", lambda url, wd, mb: seen.update(url=url))
    R.colab_start("alice/kernels", root="/content")
    assert seen["url"] == "https://github.com/alice/kernels.git"
    assert "tok12345678" in base64.b64decode(os.environ["GIT_CONFIG_VALUE_0"].split()[-1]).decode()


def test_start_cleans_a_token_url_left_by_an_old_version(world, no_gpu, monkeypatch):
    old = "https://x-access-token:oldtok12345@github.com/a/b.git"
    work = world.tmp / "proj"
    subprocess.run(["git", "clone", "-q", str(world.gh), str(work)], check=True, capture_output=True)
    git(work, "remote", "set-url", "origin", old)
    monkeypatch.setattr(R.Runner, "loop", lambda self: None)
    monkeypatch.setattr(R, "open_mailbox", lambda url, path: path)
    R.start(str(world.gh), str(work), str(world.tmp / "mb"))
    assert "oldtok" not in (work / ".git" / "config").read_text()


# ---------- exact commit ----------

def test_failed_checkout_refuses_the_job(rn):
    open(rn.mb.p("cmd", "b.sh"), "w").write("# branch: does-not-exist\necho RAN > $PILOT_OUT/r\n")
    rn.run_job("b")
    d = json.load(open(rn.mb.p("out", "b.done")))
    assert d["exit"] == -3 and d["error"].startswith("checkout failed")
    assert not os.path.exists(os.path.join(rn.mb.path + ".live", "b", "r"))


def test_failed_fetch_refuses_the_job(rn):
    git(rn.workdir, "remote", "set-url", "origin", "/nonexistent/repo.git")
    open(rn.mb.p("cmd", "n.sh"), "w").write("echo RAN\n")
    rn.run_job("n")
    d = json.load(open(rn.mb.p("out", "n.done")))
    assert d["exit"] == -3 and d["error"].startswith("fetch failed")


def test_done_records_the_full_commit_sha(rn, world):
    open(rn.mb.p("cmd", "s.sh"), "w").write("true\n")
    rn.run_job("s")
    d = json.load(open(rn.mb.p("out", "s.done")))
    assert d["commit"] == git(world.gh, "rev-parse", "main") and len(d["commit"]) == 40


# ---------- honest push ----------

def test_failed_push_is_retried_not_reported_as_done(world, monkeypatch):
    path = R.open_mailbox(str(world.gh), str(world.tmp / "mb"))
    mb = R.Mailbox(path)
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    good = git(path, "remote", "get-url", "origin")
    git(path, "remote", "set-url", "origin", str(world.tmp / "nowhere.git"))
    open(os.path.join(path, "out", "a.done"), "w").write("{}")
    assert mb.push("a") is False                      # commit made locally, push failed
    assert mb.push("again") is False                  # nothing new staged: still not pushed
    git(path, "remote", "set-url", "origin", good)
    assert mb.push("now") is True                     # the old commit goes out
    assert git(world.gh, "show", "pilot:out/a.done") == "{}"
