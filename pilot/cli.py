#!/usr/bin/env python3
"""colab-pilot client: send jobs to a GPU notebook through a git mailbox branch.

    pilot send <job> <script|->   pilot wait <job> [--follow]   pilot logs <job> [--tail N]
    pilot status                  pilot stop
PILOT_DIR: local clone of the mailbox branch (default .pilot).
"""
import argparse, json, os, subprocess, sys, time

DIR = os.environ.get("PILOT_DIR", ".pilot")


def git(*args, check=True):
    return subprocess.run(["git", "-C", DIR, *args], capture_output=True, text=True, check=check)


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


def cmd_send(a):
    os.makedirs(path("cmd"), exist_ok=True)
    if os.path.exists(path("cmd", a.job + ".sh")):
        sys.exit(f"job {a.job} exists; jobs run once, pick a new name")
    body = sys.stdin.read() if a.script == "-" else open(a.script).read()
    with open(path("cmd", a.job + ".sh"), "w") as f:
        f.write(body)
    pull()
    push(f"send {a.job}")
    print(f"sent {a.job}")


def read(p):
    try:
        return open(p).read()
    except FileNotFoundError:
        return None


def cmd_wait(a):
    shown, t0 = 0, time.time()
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
        if a.timeout and time.time() - t0 > a.timeout:
            sys.exit("wait timeout")
        time.sleep(a.poll)


def cmd_logs(a):
    pull()
    log = read(path("out", a.job + ".log"))
    if log is None:
        sys.exit("no log yet")
    lines = log.splitlines()
    print("\n".join(lines[-a.tail:] if a.tail else lines))


def cmd_status(a):
    pull()
    hb = read(path("out", "runner.json"))
    print(hb or "no runner heartbeat yet")
    cmds = sorted(f[:-3] for f in os.listdir(path("cmd")) if f.endswith(".sh")) \
        if os.path.isdir(path("cmd")) else []
    queue = [c for c in cmds if not os.path.exists(path("out", c + ".done"))]
    print("queue:", " ".join(queue) or "(empty)")


def cmd_stop(a):
    os.makedirs(path("cmd"), exist_ok=True)
    open(path("cmd", "STOP"), "w").close()
    pull()
    push("stop")
    print("stop sent")


def main():
    p = argparse.ArgumentParser(prog="pilot")
    s = p.add_subparsers(dest="c", required=True)
    x = s.add_parser("send"); x.add_argument("job"); x.add_argument("script"); x.set_defaults(f=cmd_send)
    x = s.add_parser("wait"); x.add_argument("job"); x.add_argument("--follow", action="store_true")
    x.add_argument("--poll", type=float, default=30); x.add_argument("--timeout", type=float, default=0)
    x.set_defaults(f=cmd_wait)
    x = s.add_parser("logs"); x.add_argument("job"); x.add_argument("--tail", type=int, default=0)
    x.set_defaults(f=cmd_logs)
    s.add_parser("status").set_defaults(f=cmd_status)
    s.add_parser("stop").set_defaults(f=cmd_stop)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
