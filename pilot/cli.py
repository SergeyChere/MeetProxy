#!/usr/bin/env python3
"""colab-pilot client: run jobs on a Colab GPU through the `pilot` branch of your repo.

    pilot init                    open the mailbox (.pilot/) in the current git repo
    pilot run <job> <script|->    send and follow the log until it finishes
    pilot send <job> <script|->   pilot wait <job> [--follow]   pilot logs <job> [--tail N]
    pilot status                  pilot stop                    pilot guide
"""
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timezone

BRANCH = os.environ.get("PILOT_BRANCH", "pilot")


def sh(*args, cwd=None, check=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"{' '.join(args[:3])}…: {r.stderr.strip()}")
    return r


def toplevel():
    r = sh("git", "rev-parse", "--show-toplevel", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def mailbox_dir():
    if os.environ.get("PILOT_DIR"):
        return os.environ["PILOT_DIR"]
    top = toplevel() or os.getcwd()
    return os.path.join(top, ".pilot")


DIR = None


def git(*args, check=True):
    return sh("git", "-C", DIR, *args, check=check)


def need_mailbox():
    if not os.path.isdir(os.path.join(DIR, ".git")):
        sys.exit("no mailbox here: run `pilot init` in your project repo first")


def pull():
    git("pull", "-q", "--rebase", check=False)


def push(msg):
    git("add", "-A", "cmd")
    git("commit", "-q", "-m", msg)
    for _ in range(5):
        if git("push", "-q", check=False).returncode == 0:
            return
        pull()
        time.sleep(1)
    sys.exit("push failed")


def path(*p):
    return os.path.join(DIR, *p)


def read(p):
    try:
        return open(p).read()
    except FileNotFoundError:
        return None


def cmd_init(a):
    top = toplevel()
    if not top:
        sys.exit("run `pilot init` inside your project's git repository")
    if os.path.isdir(os.path.join(DIR, ".git")):
        print(f"mailbox already open at {DIR}")
        return cmd_status(a)
    url = sh("git", "-C", top, "remote", "get-url", "origin").stdout.strip()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from pilot.runner import open_mailbox
    open_mailbox(url, DIR)
    excl = os.path.join(top, ".git", "info", "exclude")
    if os.path.isfile(excl) and ".pilot/" not in open(excl).read():
        with open(excl, "a") as f:
            f.write("\n.pilot/\n")
    print(f"mailbox: branch '{BRANCH}' of {url.split('@')[-1]} at {DIR}")
    print("Next: the human opens the Colab notebook and runs it with this repo name.")


def add_branch(body):
    """Pin the job to the agent's current branch and warn if its last commit is not pushed."""
    top = toplevel()
    if not top or re.search(r"^#\s*branch:", body, re.M):
        return body
    br = sh("git", "-C", top, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    if not br or br == "HEAD":
        return body
    # ask GitHub directly: remote-tracking refs can be missing or stale in shallow/odd clones
    remote = sh("git", "-C", top, "ls-remote", "origin", f"refs/heads/{br}", check=False)
    rsha = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.strip() else ""
    head = sh("git", "-C", top, "rev-parse", "HEAD", check=False).stdout.strip()
    if remote.returncode:
        print("warning: could not reach GitHub to check that your code is pushed", file=sys.stderr)
    elif not rsha:
        print(f"warning: branch {br} is not on GitHub yet: `git push -u origin {br}` first",
              file=sys.stderr)
    elif rsha != head:
        print(f"warning: your HEAD {head[:7]} differs from {br} on GitHub ({rsha[:7]}); "
              f"the GPU runs the pushed version", file=sys.stderr)
    if sh("git", "-C", top, "status", "--porcelain", "-uno", check=False).stdout.strip():
        print("warning: uncommitted changes are not sent to the GPU", file=sys.stderr)
    return f"# branch: {br}\n" + body


def cmd_send(a):
    need_mailbox()
    pull()
    os.makedirs(path("cmd"), exist_ok=True)
    if os.path.exists(path("cmd", a.job + ".sh")):
        sys.exit(f"job {a.job} exists; jobs run once, pick a new name")
    body = sys.stdin.read() if a.script == "-" else open(a.script).read()
    body = add_branch(body)
    with open(path("cmd", a.job + ".sh"), "w") as f:
        f.write(body)
    push(f"send {a.job}")
    print(f"sent {a.job}", file=sys.stderr)


def cmd_wait(a):
    need_mailbox()
    shown, t0, warned = 0, time.time(), False
    while True:
        pull()
        log = read(path("out", a.job + ".log")) or ""
        if a.follow and len(log) > shown:
            sys.stdout.write(log[shown:])
            sys.stdout.flush()
            shown = len(log)
        done = read(path("out", a.job + ".done"))
        if done:
            d = json.loads(done)
            print(json.dumps(d), file=sys.stderr)
            sys.exit(d["exit"] if 0 <= d["exit"] < 256 else 1)
        if not warned and not log and time.time() - t0 > 120:
            msg = runner_problem()
            if msg:
                print(msg, file=sys.stderr)
                warned = True
        if a.timeout and time.time() - t0 > a.timeout:
            sys.exit("wait timeout")
        time.sleep(a.poll)


def cmd_run(a):
    cmd_send(a)
    a.follow = True
    cmd_wait(a)


def cmd_logs(a):
    need_mailbox()
    pull()
    log = read(path("out", a.job + ".log"))
    if log is None:
        sys.exit("no log yet")
    lines = log.splitlines()
    print("\n".join(lines[-a.tail:] if a.tail else lines))


def heartbeat():
    hb = read(path("out", "runner.json"))
    return json.loads(hb) if hb else None


def age_min(hb):
    t = datetime.fromisoformat(hb["time"])
    return (datetime.now(timezone.utc) - t).total_seconds() / 60


def runner_problem():
    hb = heartbeat()
    if not hb:
        return "No runner has connected yet: ask the human to run the Colab notebook."
    if hb["state"] not in ("idle", "running", "starting"):
        return f"Runner exited ({hb['state']}): ask the human to run the notebook cell again."
    if hb["state"] == "idle" and age_min(hb) > 12:
        return (f"Runner silent for {age_min(hb):.0f} min: the runtime was probably "
                f"disconnected; ask the human to reconnect and run the notebook again.")
    return None


def cmd_status(a):
    need_mailbox()
    pull()
    hb = heartbeat()
    if hb:
        print(f"runner: {hb['state']} {hb.get('job') or ''} | gpu: {hb['gpu']} | "
              f"last seen {age_min(hb):.0f} min ago")
    msg = runner_problem()
    if msg:
        print(msg)
    cmds = sorted(f[:-3] for f in os.listdir(path("cmd")) if f.endswith(".sh")) \
        if os.path.isdir(path("cmd")) else []
    queue = [c for c in cmds if not os.path.exists(path("out", c + ".done"))]
    print("queue:", " ".join(queue) or "(empty)")


def cmd_stop(a):
    need_mailbox()
    pull()
    os.makedirs(path("cmd"), exist_ok=True)
    with open(path("cmd", "STOP"), "w") as f:
        f.write(f"{time.time():.0f}\n")
    push("stop")
    print("stop sent; the runner ends after the current job is killed")


def cmd_guide(a):
    print(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "guide.md")).read())


def main():
    global DIR
    DIR = mailbox_dir()
    p = argparse.ArgumentParser(prog="pilot", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="c", required=True)
    s.add_parser("init").set_defaults(f=cmd_init)
    for name, f in (("send", cmd_send), ("run", cmd_run)):
        x = s.add_parser(name); x.add_argument("job"); x.add_argument("script")
        x.add_argument("--poll", type=float, default=20)
        x.add_argument("--timeout", type=float, default=0); x.set_defaults(f=f)
    x = s.add_parser("wait"); x.add_argument("job"); x.add_argument("--follow", action="store_true")
    x.add_argument("--poll", type=float, default=20); x.add_argument("--timeout", type=float, default=0)
    x.set_defaults(f=cmd_wait)
    x = s.add_parser("logs"); x.add_argument("job"); x.add_argument("--tail", type=int, default=0)
    x.set_defaults(f=cmd_logs)
    s.add_parser("status").set_defaults(f=cmd_status)
    s.add_parser("stop").set_defaults(f=cmd_stop)
    s.add_parser("guide").set_defaults(f=cmd_guide)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
