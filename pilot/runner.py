"""colab-pilot runner: executes jobs from a git mailbox branch inside a notebook.

In Colab (one cell):
    !pip -q install git+https://github.com/SergeyChere/colab-pilot
    import pilot.runner; pilot.runner.colab_start("you/your-project")

The mailbox is the branch `pilot` of your own project repository; it is created if missing.
Environment knobs: POLL_S=20 PUSH_S=45 HEARTBEAT_S=300 IDLE_MIN=120 MAX_HOURS=12 GPU_SAMPLE_S=1
"""
import json, os, re, shutil, signal, subprocess, threading, time

try:
    from pilot import telemetry
except ImportError:  # runner.py run as a plain script
    import telemetry
from datetime import datetime, timezone

VERSION = "0.3.0"
BRANCH = os.environ.get("PILOT_BRANCH", "pilot")
SECRET_RE = re.compile(r"TOKEN|SECRET|KEY|PASSWORD", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def secrets():
    return [v for k, v in os.environ.items() if SECRET_RE.search(k) and len(v) >= 8]


def redact(text, vals=None):
    for v in vals if vals is not None else secrets():
        text = text.replace(v, "***")
    return text


def gpu_info():
    try:
        q = "name,memory.total,driver_version"
        r = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout.strip() or "none"
    except Exception:
        return "none"


def header(script, key):
    for line in script.splitlines()[:20]:
        m = re.match(rf"#\s*{key}:\s*(\S+)", line)
        if m:
            return m.group(1)
    return None


def git(path, *args, check=True):
    r = subprocess.run(["git", "-C", path, *args], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(redact(f"git {' '.join(args)}: {r.stderr.strip()}"))
    return r


IDENT = ["-c", "user.name=colab-pilot", "-c", "user.email=colab-pilot@localhost"]


def set_identity(path):
    """Colab has no git identity; without one, `pull --rebase` (needed whenever the agent pushed a
    command meanwhile) and autostash fail, and every later push is rejected."""
    git(path, "config", "user.name", "colab-pilot")
    git(path, "config", "user.email", "colab-pilot@localhost")


def open_mailbox(url, path, branch=BRANCH):
    """Clone the mailbox branch of `url` into `path`; create the branch if it does not exist."""
    shutil.rmtree(path, ignore_errors=True)
    for _ in range(3):
        r = subprocess.run(["git", "clone", "-q", "--depth", "20", "-b", branch, url, path],
                           capture_output=True, text=True)
        if r.returncode == 0:
            set_identity(path)
            return path
        shutil.rmtree(path, ignore_errors=True)
        if "not found" not in r.stderr and "Remote branch" not in r.stderr:
            raise RuntimeError(redact("clone failed: " + r.stderr.strip()))
        # branch missing: create an empty orphan branch with cmd/ and out/
        os.makedirs(path)
        git(path, "init", "-q")
        git(path, "remote", "add", "origin", url)
        git(path, "checkout", "-q", "--orphan", branch)
        for d in ("cmd", "out"):
            os.makedirs(os.path.join(path, d))
            open(os.path.join(path, d, ".keep"), "w").close()
        set_identity(path)
        git(path, "add", "-A")
        git(path, *IDENT, "commit", "-q", "-m", "colab-pilot mailbox")
        if git(path, "push", "-q", "-u", "origin", branch, check=False).returncode == 0:
            return path
        shutil.rmtree(path, ignore_errors=True)  # someone else created it meanwhile: clone again
        time.sleep(2)
    raise RuntimeError("could not open mailbox branch")


class Mailbox:
    """Git clone of the mailbox branch. Files that are still being written (job log, results)
    live outside the clone and are copied into out/ inside push(), so git never rewrites a file
    a job holds open."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.live = {}  # path inside out/ -> live file or directory outside the clone

    def sync(self):
        for dest, src in self.live.items():
            dst = self.p("out", dest)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.exists(src):
                shutil.copyfile(src, dst)

    def _rebase_pull(self):
        r = git(self.path, *IDENT, "-c", "rebase.autoStash=true", "pull", "-q", "--rebase",
                check=False)
        if r.returncode and os.path.isdir(os.path.join(self.path, ".git", "rebase-merge")):
            git(self.path, "rebase", "--abort", check=False)
        if r.returncode:
            print(f"[{now()}] warning: pull failed: {redact(r.stderr.strip())[:300]}", flush=True)
        return r.returncode == 0

    def pull(self):
        with self.lock:
            self._rebase_pull()

    def push(self, msg):
        with self.lock:
            self.sync()
            git(self.path, "add", "-A", "out")
            if git(self.path, "diff", "--cached", "--quiet", check=False).returncode == 0:
                return True
            git(self.path, *IDENT, "commit", "-q", "-m", msg)
            for _ in range(5):
                p = git(self.path, "push", "-q", check=False)
                if p.returncode == 0:
                    return True
                self._rebase_pull()
                time.sleep(2)
            print(f"[{now()}] warning: push failed, will retry later: "
                  f"{redact(p.stderr.strip())[:300]}", flush=True)
            return False

    def p(self, *parts):
        return os.path.join(self.path, *parts)


class Runner:
    def __init__(self, mailbox=None, workdir=None):
        self.mb = Mailbox(mailbox or os.environ["PILOT_MAILBOX"])
        wd = workdir or os.environ.get("PILOT_WORKDIR") or os.getcwd()
        self.workdir = wd if os.path.isdir(wd) else os.getcwd()
        env = lambda k, d: float(os.environ.get(k, d))
        self.poll, self.push_s = env("POLL_S", 20), env("PUSH_S", 45)
        self.hb_s = env("HEARTBEAT_S", 300)
        self.idle, self.max_s = env("IDLE_MIN", 120) * 60, env("MAX_HOURS", 12) * 3600
        self.gpu = gpu_info()
        self.secrets = secrets()
        self.state, self.job = "starting", None
        self.t_start = time.time()
        os.makedirs(self.mb.p("out"), exist_ok=True)

    def heartbeat(self):
        hb = {"state": self.state, "job": self.job, "gpu": self.gpu, "time": now(),
              "workdir": self.workdir, "version": VERSION}
        with open(self.mb.p("out", "runner.json"), "w") as f:
            json.dump(hb, f, indent=1)

    def next_job(self):
        cmd = self.mb.p("cmd")
        if not os.path.isdir(cmd):
            return None
        for name in sorted(os.listdir(cmd)):
            if name.endswith(".sh") and not os.path.exists(self.mb.p("out", name[:-3] + ".done")):
                return name[:-3]
        return None

    def stopped(self):
        """cmd/STOP holds the time it was sent; it stops only runners started before that."""
        try:
            sent = float(open(self.mb.p("cmd", "STOP")).read().strip() or 0)
        except (FileNotFoundError, ValueError):
            return False
        return sent > self.t_start

    def update_workdir(self, branch=None):
        """Check out the newest pushed commit of `branch` (default: the remote default branch),
        so what runs is exactly what the agent pushed."""
        if not os.path.isdir(os.path.join(self.workdir, ".git")):
            return "workdir is not a git repo"
        git(self.workdir, "fetch", "-q", "--prune", "origin", check=False)
        target = f"origin/{branch}" if branch else "origin/HEAD"
        r = git(self.workdir, "checkout", "-q", "--force", "--detach", target, check=False)
        head = git(self.workdir, "log", "-1", "--format=%h %s", check=False).stdout.strip()
        msg = f"code {head} ({branch or 'default branch'})"
        if r.returncode:
            msg += f" CHECKOUT FAILED: {redact(r.stderr.strip())}"
        return msg

    def finish(self, name, done):
        with open(self.mb.p("out", name + ".done"), "w") as f:
            json.dump(done, f, indent=1)

    def run_job(self, name):
        script = open(self.mb.p("cmd", name + ".sh")).read()
        timeout = float(header(script, "timeout") or 0) or None
        want = header(script, "gpu")
        done = {"job": name, "start": now(), "gpu": self.gpu}
        no_gpu = self.gpu == "none"
        if want and (no_gpu or (want.lower() != "any" and want.lower() not in self.gpu.lower())):
            done.update(exit=-2, error=f"wrong gpu: want {want}, have {self.gpu}", seconds=0, end=now())
            self.finish(name, done)
            self.mb.push(f"{name}: skipped, wrong gpu")
            return
        done["code"] = self.update_workdir(header(script, "branch"))
        live = self.mb.path.rstrip("/") + ".live"
        outdir, logpath = os.path.join(live, name), os.path.join(live, name + ".log")
        os.makedirs(outdir, exist_ok=True)
        self.mb.live = {name: outdir, name + ".log": logpath}
        env = dict(os.environ, COLAB_PILOT="1", PILOT_OUT=outdir, PILOT_JOB=name)
        t0 = time.time()
        self.state, self.job = "running", name
        self.heartbeat()
        self.mb.push(f"{name}: start")
        sampler = None
        if not no_gpu and (header(script, "telemetry") or "on").lower() != "off":
            sampler = telemetry.Sampler(os.path.join(outdir, "gpu.csv")).start()
        with open(logpath, "w") as log:
            log.write(f"# colab-pilot: {name} on {self.gpu}; {done['code']}\n")
            proc = subprocess.Popen(["bash", "-c", script], cwd=self.workdir, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            if sampler:
                sampler.pgid = proc.pid  # its own session: pgid == pid
            stop_flag = threading.Event()
            why = {}

            def pusher():
                while not stop_flag.wait(self.push_s):
                    log.flush()
                    self.heartbeat()
                    self.mb.push(f"{name}: log")
                    self.mb.pull()
                    if self.stopped():
                        why["error"] = "stopped"
                        kill(proc)

            def on_timeout():
                why["error"] = "timeout"
                kill(proc)

            th = threading.Thread(target=pusher, daemon=True)
            th.start()
            killer = threading.Timer(timeout, on_timeout) if timeout else None
            if killer:
                killer.start()
            try:
                for line in proc.stdout:
                    log.write(redact(line, self.secrets))
            except KeyboardInterrupt:
                why["error"] = "interrupted"
                raise
            finally:
                kill(proc)  # whole group: no stray GPU processes survive the job
                code = proc.wait()
                stop_flag.set()
                if killer:
                    killer.cancel()
                th.join()
                log.flush()
                done.update(why, exit=code, seconds=round(time.time() - t0, 1), end=now())
                if sampler:
                    try:
                        stats = sampler.stop()
                    except Exception as e:  # telemetry must never cost a job its result
                        stats = {"error": str(e)[:200], "flags": []}
                    if stats:
                        done["gpu_stats"] = stats
                        log.write(telemetry.line(stats) + "\n")
                        log.flush()
                self.finish(name, done)
                self.state, self.job = "idle", None
                self.heartbeat()
                self.mb.push(f"{name}: done exit={code}")
                self.mb.live = {}

    def loop(self):
        print(f"colab-pilot {VERSION}: gpu={self.gpu}\n  mailbox={self.mb.path}\n"
              f"  workdir={self.workdir}\nWaiting for jobs. Stop with the stop button; "
              f"the runtime stays on until you shut it down.", flush=True)
        t_start = last_job = self.t_start
        last_hb = 0
        try:
            while True:
                self.mb.pull()
                if self.stopped():
                    self.state = "stopped"
                    break
                if time.time() - t_start > self.max_s:
                    self.state = "budget"
                    break
                job = self.next_job()
                if job:
                    print(f"[{now()}] run {job}", flush=True)
                    self.run_job(job)
                    last_job = time.time()
                    print(f"[{now()}] done {job}", flush=True)
                    continue
                if time.time() - last_job > self.idle:
                    self.state = "idle-exit"
                    break
                self.state = "idle"
                if time.time() - last_hb > self.hb_s:  # few commits while idle
                    self.heartbeat()
                    self.mb.push("heartbeat")
                    last_hb = time.time()
                time.sleep(self.poll)
        except KeyboardInterrupt:
            self.state = "interrupted"
        finally:
            self.job = None
            self.heartbeat()
            self.mb.push(f"runner exit: {self.state}")
            print(f"colab-pilot exit: {self.state}. The runtime is still on; "
                  f"shut it down yourself when done.", flush=True)


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def start(url, workdir, mailbox):
    """Clone/update the project at `workdir`, open the mailbox at `mailbox`, run until stopped."""
    if os.path.isdir(os.path.join(workdir, ".git")):
        git(workdir, "pull", "-q", "--ff-only", check=False)
    else:
        r = subprocess.run(["git", "clone", "-q", url, workdir], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(redact("clone failed: " + r.stderr.strip()))
    open_mailbox(url, mailbox)
    Runner(mailbox, workdir).loop()


def colab_start(repo, secret="GH_TOKEN", root="/content"):
    """One-call start in Colab. `repo` is "owner/name"; the token comes from Colab secrets.
    Problems are printed as one plain message (no traceback) and the call returns."""
    def stop(msg):
        print("\ncolab-pilot: " + msg + "\n", flush=True)

    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or "") or repo == "owner/repo":
        return stop("put your project's repository into REPO as owner/name "
                    "(for https://github.com/alice/my-kernels: alice/my-kernels), then run again.")
    tok, why = os.environ.get(secret), ""
    if not tok:
        try:
            from google.colab import userdata
            for name in (secret, "GITHUB_TOKEN", "GH_PAT"):
                try:
                    tok = userdata.get(name)
                    break
                except Exception as e:
                    why = type(e).__name__
        except ImportError:
            why = "not running in Colab"
    if not tok:
        if "NotebookAccess" in why:
            return stop(f"the secret exists but this notebook may not read it: key icon on the left "
                        f"-> switch on 'Notebook access' for {secret}, then run again.")
        return stop(f"no GitHub token. Key icon on the left -> 'Add new secret' -> name {secret}, "
                    f"value: a fine-grained token (github.com/settings/personal-access-tokens/new) "
                    f"with access to {repo} only, Repository permissions -> Contents: Read and write. "
                    f"Switch on 'Notebook access', then run again.")
    os.environ[secret] = tok
    gpu = gpu_info()
    if gpu == "none":
        print("WARNING: no GPU. Runtime > Change runtime type > pick a GPU, then run again.")
    url = f"https://x-access-token:{tok}@github.com/{repo}.git"
    name = repo.rstrip("/").split("/")[-1]
    try:
        start(url, os.path.join(root, name), os.path.join(root, ".pilot-mailbox"))
    except RuntimeError as e:
        msg = str(e)
        hint = (f" Check that the token has access to {repo} with Contents: Read and write, "
                f"and that the name is right.") if "clone" in msg or "403" in msg or "404" in msg \
            or "not found" in msg.lower() else ""
        return stop(redact(msg) + hint)


def main():
    Runner().loop()


if __name__ == "__main__":
    main()
