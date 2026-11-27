#!/usr/bin/env python3
"""MeetProxy client: run jobs on a Colab GPU through the `meetproxy` branch of your repo.

    meet init                    open the mailbox (.meetproxy/) in the current git repo
    meet run <job> <script|->    send and follow the log until it finishes
    meet send <job> <script|->   meet wait <job> [--follow]   meet logs <job> [--tail N]
    meet status                  meet stop                    meet guide
    meet history [--last N]      one line per finished job (compare runs without reading logs)
    meet export [job…|--all]     copy results into meet-runs/ of your project (not committed)
    meet report <job|history>    human report with charts in meet-runs/ (needs matplotlib)
"""
import argparse, json, os, random, re, shutil, subprocess, sys, time
from datetime import datetime, timezone

BRANCH = os.environ.get("MEET_BRANCH", "meetproxy")


def sh(*args, cwd=None, check=True):
    t = float(os.environ.get("MEET_GIT_TIMEOUT_S", 180))  # a hung network must not hang the agent
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=t)
    except subprocess.TimeoutExpired:
        r = subprocess.CompletedProcess(args, 124, "", f"timed out after {t:.0f} s")
    if check and r.returncode:
        sys.exit(f"{' '.join(args[:3])}…: {r.stderr.strip()}")
    return r


def toplevel():
    r = sh("git", "rev-parse", "--show-toplevel", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def mailbox_dir():
    if os.environ.get("MEET_DIR"):
        return os.environ["MEET_DIR"]
    top = toplevel() or os.getcwd()
    return os.path.join(top, ".meetproxy")


DIR = None


def git(*args, check=True):
    return sh("git", "-C", DIR, *args, check=check)


def need_mailbox():
    if not os.path.isdir(os.path.join(DIR, ".git")):
        sys.exit("no mailbox here: run `meet init` in your project repo first")


def pull():
    git("pull", "-q", "--rebase", check=False)


def push(msg):
    git("add", "-A", "cmd")
    git("commit", "-q", "-m", msg)
    # the runner pushes logs every PUSH_S while a job runs, so a push can lose the race a few
    # times in a row; back off with jitter instead of giving up after a fixed short burst
    for i in range(max(1, int(os.environ.get("MEET_PUSH_TRIES", 12)))):
        r = git("push", "-q", check=False)
        if r.returncode == 0:
            return
        pull()
        time.sleep(min(0.5 * (i + 1), 4) * (0.5 + random.random()))
    sys.exit(f"push failed: {r.stderr.strip()[:300]}")


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
        sys.exit("run `meet init` inside your project's git repository")
    if os.path.isdir(os.path.join(DIR, ".git")):
        print(f"mailbox already open at {DIR}")
        return cmd_status(a)
    url = sh("git", "-C", top, "remote", "get-url", "origin").stdout.strip()
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from meetproxy.runner import open_mailbox
    open_mailbox(url, DIR)
    excl = os.path.join(top, ".git", "info", "exclude")
    if os.path.isfile(excl) and ".meetproxy/" not in open(excl).read():
        with open(excl, "a") as f:
            f.write("\n.meetproxy/\n")
    print(f"mailbox: branch '{BRANCH}' of {url.split('@')[-1]} at {DIR}")
    print("Next: the human opens the Colab notebook and runs it with this repo name.")


def add_branch(body):
    """Pin the job to the exact commit the agent is on (and name its branch). The runner checks out
    that commit, not whatever the branch points to when the job starts."""
    top = toplevel()
    if not top:
        return body
    head = sh("git", "-C", top, "rev-parse", "HEAD", check=False).stdout.strip()
    br = sh("git", "-C", top, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    lines = []
    if head and not re.search(r"^#\s*commit:", body, re.M):
        lines.append(f"# commit: {head}")
    if br and br != "HEAD" and not re.search(r"^#\s*branch:", body, re.M):
        lines.append(f"# branch: {br}")
    if not lines:
        return body
    if br and br != "HEAD":
        # ask GitHub directly: remote-tracking refs can be missing or stale in shallow/odd clones
        remote = sh("git", "-C", top, "ls-remote", "origin", f"refs/heads/{br}", check=False)
        rsha = remote.stdout.split()[0] if remote.returncode == 0 and remote.stdout.strip() else ""
        on_remote = rsha and (rsha == head or sh(
            "git", "-C", top, "merge-base", "--is-ancestor", head, rsha, check=False).returncode == 0)
        if remote.returncode:
            print("warning: could not reach GitHub to check that your code is pushed", file=sys.stderr)
        elif not rsha:
            print(f"warning: branch {br} is not on GitHub yet: the job will not run until you push "
                  f"it (`git push -u origin {br}`)", file=sys.stderr)
        elif not on_remote:
            print(f"warning: commit {head[:7]} is not on GitHub: the job will not run until you push "
                  f"it", file=sys.stderr)
    if sh("git", "-C", top, "status", "--porcelain", "-uno", check=False).stdout.strip():
        print("warning: uncommitted changes are not sent to the GPU", file=sys.stderr)
    return "\n".join(lines) + "\n" + body


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
            short = {k: v for k, v in d.items() if k != "gpu_stats"}
            if "gpu_stats" in d:  # full numbers stay in the file; the agent gets one line
                short["gpu_check"] = gpu_line(d["gpu_stats"])
            print(json.dumps(short), file=sys.stderr)
            sys.exit(d["exit"] if 0 <= d["exit"] < 256 else 1)
        if not warned and time.time() - t0 > float(os.environ.get("MEET_SILENT_S", 120)):
            msg = runner_problem()
            if msg:
                print(msg, file=sys.stderr)
                warned = True
        if a.timeout and time.time() - t0 > a.timeout:
            sys.exit("wait timeout")
        time.sleep(a.poll)


def _pkg():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import meetproxy
    return meetproxy


def gpu_line(stats):
    _pkg()
    from meetproxy.telemetry import line
    return line(stats)


def cmd_history(a):
    need_mailbox()
    pull()
    _pkg()
    from meetproxy import history
    print(history.table(history.read(path("out", "history.csv")), last=a.last))


def export_dir(a):
    if a.dir:
        return a.dir
    return os.path.join(toplevel() or os.getcwd(), "meet-runs")


def export_jobs(jobs, dest):
    """Copy jobs' log, .done and result folder, plus the history, into dest. Returns count."""
    n = 0
    for job in jobs:
        if not os.path.exists(path("out", job + ".done")):
            print(f"skip {job}: not finished", file=sys.stderr)
            continue
        d = os.path.join(dest, job)
        os.makedirs(d, exist_ok=True)
        for ext in (".log", ".done"):
            if os.path.exists(path("out", job + ext)):
                shutil.copyfile(path("out", job + ext), os.path.join(d, job + ext))
        if os.path.isdir(path("out", job)):
            shutil.copytree(path("out", job), d, dirs_exist_ok=True)
        n += 1
    for f in ("history.csv", "history.md", os.path.join("charts", "history.svg")):
        if os.path.exists(path("out", f)):
            os.makedirs(os.path.dirname(os.path.join(dest, f)), exist_ok=True)
            shutil.copyfile(path("out", f), os.path.join(dest, f))
    return n


def finished_jobs():
    out = path("out")
    return sorted(f[:-5] for f in os.listdir(out) if f.endswith(".done")) if os.path.isdir(out) else []


def cmd_export(a):
    need_mailbox()
    pull()
    jobs = finished_jobs() if a.all else (a.jobs or finished_jobs()[-1:])
    if not jobs:
        sys.exit("no finished jobs yet")
    dest = export_dir(a)
    n = export_jobs(jobs, dest)
    print(f"exported {n} job(s) to {os.path.relpath(dest)} (not committed)")


def cmd_report(a):
    """For the human. Prints only where the report is; the agent should not open it."""
    need_mailbox()
    pull()
    _pkg()
    from meetproxy import history, report
    dest = export_dir(a)
    try:
        if a.target == "history":
            export_jobs([], dest)
            md = report.history_report(history.read(path("out", "history.csv")), dest)
        else:
            if not export_jobs([a.target], dest):
                sys.exit(f"no finished job {a.target}")
            d = os.path.join(dest, a.target)
            md = os.path.join(d, "report.md")
            if not os.path.exists(md):  # the runner made none: build it here
                done = json.load(open(os.path.join(d, a.target + ".done")))
                log = read(os.path.join(d, a.target + ".log"))
                md = report.job_report(d, done, log)
    except report.NoMatplotlib as e:
        sys.exit(str(e))
    print(f"report for the human: {os.path.relpath(md)}")


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
    if hb["state"] == "running" and age_min(hb) > 3:  # a running job heartbeats every PUSH_S
        return (f"Runner silent for {age_min(hb):.0f} min during job {hb.get('job')}: the runtime "
                f"was probably disconnected or is stuck; ask the human to check the Colab tab.")
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
    p = argparse.ArgumentParser(prog="meet", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    from .runner import VERSION
    p.add_argument("--version", action="version", version=f"meet {VERSION}")
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
    x = s.add_parser("history"); x.add_argument("--last", type=int, default=10)
    x.set_defaults(f=cmd_history)
    x = s.add_parser("export"); x.add_argument("jobs", nargs="*"); x.add_argument("--all", action="store_true")
    x.add_argument("--dir"); x.set_defaults(f=cmd_export)
    x = s.add_parser("report"); x.add_argument("target"); x.add_argument("--dir")
    x.set_defaults(f=cmd_report)
    a = p.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
