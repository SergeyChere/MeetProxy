"""The skill installs MeetProxy safely: the exact version, in an isolated environment, only with the
user's consent, never by overriding system package protection."""
import os, re, subprocess, sys

import pytest

from conftest import ROOT
from meetproxy import runner as R

SETUP = os.path.join(ROOT, "skill", "meetproxy", "scripts", "setup.sh")


def version():
    return re.search(r'^version = "(.+)"', open(os.path.join(ROOT, "pyproject.toml")).read(), re.M)[1]


def test_meet_version_flag():
    r = subprocess.run([sys.executable, "-m", "meetproxy.cli", "--version"], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.stdout.strip() == f"meet {version()}"


@pytest.mark.parametrize("f", ["skill/meetproxy/scripts/setup.sh", "skill/meetproxy/SKILL.md", "skill/meetproxy/reference/mailbox.md",
                               "meetproxy/guide.md", "README.md",
                               "skill/meetproxy/reference/troubleshooting.md"])
def test_no_install_overrides_system_package_protection(f):
    assert "break-system-packages" not in open(os.path.join(ROOT, f)).read()


def test_setup_expects_the_current_version():
    assert f'MEET_VERSION:-{version()}' in open(SETUP).read()


def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null")
    for c in (["git", "init", "-q"], ["git", "remote", "add", "origin", str(tmp_path / "gh.git")]):
        subprocess.run(c, cwd=p, check=True, env=env)
    return p


def fake_meet(tmp_path, ver):
    b = tmp_path / "bin"
    b.mkdir()
    (b / "meet").write_text(f"#!/bin/sh\n[ \"$1\" = --version ] && echo 'meet {ver}' && exit 0\n"
                            "echo FAKE MEET RAN; exit 0\n")
    (b / "meet").chmod(0o755)
    return b


def run_setup(cwd, path, **env):
    e = dict(os.environ, PATH=f"{path}:/bin", HOME=str(cwd.parent / "home"),
             GIT_CONFIG_GLOBAL="/dev/null", **env)
    return subprocess.run(["bash", SETUP], cwd=cwd, capture_output=True, text=True, env=e)


def test_wrong_version_on_path_is_not_used_and_nothing_installs_without_consent(tmp_path):
    p = project(tmp_path)
    r = run_setup(p, fake_meet(tmp_path, "0.1.0"))
    assert r.returncode == 2
    assert "FAKE MEET RAN" not in r.stdout + r.stderr
    assert "MEET_INSTALL=yes" in r.stdout and "ask the user" in r.stdout.lower()
    assert not (tmp_path / "home" / ".meetproxy").exists()


def test_matching_version_on_path_is_used(tmp_path):
    p = project(tmp_path)
    r = run_setup(p, fake_meet(tmp_path, version()))
    assert r.returncode == 0 and "FAKE MEET RAN" in r.stdout


@pytest.mark.skipif(os.environ.get("MEET_SKIP_SLOW") == "1", reason="creates a venv")
def test_consented_install_goes_into_an_isolated_venv(tmp_path):
    p = project(tmp_path)
    subprocess.run(["git", "init", "-q", "--bare", str(tmp_path / "gh.git")], check=True)
    venv = tmp_path / "venv"
    tools = tmp_path / "tools"          # python and git, but no meet on PATH
    tools.mkdir()
    for t in ("python3", "git"):
        os.symlink(subprocess.run(["which", t], capture_output=True, text=True).stdout.strip(),
                   tools / t)
    r = run_setup(p, tools, MEET_INSTALL="yes", MEET_PKG=ROOT, MEET_VENV=str(venv))
    assert (venv / "bin" / "meet").exists(), r.stdout + r.stderr
    out = subprocess.run([str(venv / "bin" / "meet"), "--version"], capture_output=True, text=True)
    assert out.stdout.strip() == f"meet {version()}"
    assert f"export PATH=\"{venv}/bin:$PATH\"" in r.stdout
