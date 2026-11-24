"""colab-pilot runner: executes jobs from a git mailbox branch inside a notebook.

In Colab (one cell):
    !pip -q install git+https://github.com/SergeyChere/colab-pilot
    import pilot.runner; pilot.runner.colab_start("you/your-project")

The mailbox is the branch `pilot` of your own project repository; it is created if missing.
Environment knobs: POLL_S=20 PUSH_S=45 HEARTBEAT_S=300 IDLE_MIN=120 MAX_HOURS=12 GPU_SAMPLE_S=1
PILOT_CHARTS=1 makes a human report for every job (otherwise only for `# charts: on`).
"""
import base64, json, os, re, shutil, signal, subprocess, threading, time

try:
    from pilot import history, report, telemetry
except ImportError:  # runner.py run as a plain script
    import history, report, telemetry
from datetime import datetime, timezone

VERSION = "0.5.0"
BRANCH = os.environ.get("PILOT_BRANCH", "pilot")
SECRET_RE = re.compile(r"TOKEN|SECRET|KEY|PASSWORD", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


EXTRA_SECRETS = []  # values to mask that are not in a secret-looking variable (git auth header)
TOKEN_VARS = {"GH_TOKEN", "GITHUB_TOKEN", "GH_PAT"}


def secrets():
    env = [v for k, v in os.environ.items() if SECRET_RE.search(k) and len(v) >= 8]
    return env + [v for v in EXTRA_SECRETS if v not in env]


def use_token(tok):
    """Authenticate the runner's own git calls to GitHub without putting the token in any URL or
    config file: git reads an Authorization header from GIT_CONFIG_* variables, which jobs never
    get (see job_env)."""
    b64 = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    os.environ.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                      GIT_CONFIG_VALUE_0=f"Authorization: Basic {b64}")
    EXTRA_SECRETS.extend(v for v in (tok, b64) if v not in EXTRA_SECRETS)


def job_env(**extra):
    """The runner's environment minus every credential the runner itself uses."""
    drop = set(EXTRA_SECRETS)
    env = {k: v for k, v in os.environ.items()
           if k not in TOKEN_VARS and not k.startswith("GIT_CONFIG_") and v not in drop}
    env.update(extra)
    return env


def copy_redacted(src, dst, vals):
    """Copy a file, replacing every secret value (also inside binary files) with ***."""
    with open(src, "rb") as f:
        data = f.read()
    for v in vals:
        data = data.replace(v.encode(), b"***")
    with open(dst, "wb") as f:
        f.write(data)


def redact(text, vals=None):
    for v in vals if vals is not None else secrets():
        text = text.replace(v, "***")
    return text


def gpu_info():
    try:
        q = "name,memory.total,driver_version"
        r = subprocess.run(["nvidia-smi", f"--query-gpu={q}", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=20)
        # a failing nvidia-smi prints its error to stdout: that is not a GPU name
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "none"
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

    def __init__(self, path, secrets=None):
        self.path = path
        self.lock = threading.Lock()
        self.live = {}  # path inside out/ -> live file or directory outside the clone
        self.secrets = secrets or []

    def sync(self):
        """Copy live job files into out/, masking secrets: what a job writes is pushed, and a job
        may print its environment into a results file by accident."""
        for dest, src in self.live.items():
            dst = self.p("out", dest)
            if os.path.isdir(src):
                for root, _, files in os.walk(src):
                    rel = os.path.relpath(root, src)
                    os.makedirs(os.path.join(dst, rel), exist_ok=True)
                    for f in files:
                        copy_redacted(os.path.join(root, f), os.path.join(dst, rel, f), self.secrets)
            elif os.path.exists(src):
                copy_redacted(src, dst, self.secrets)

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
            if git(self.path, "diff", "--cached", "--quiet", check=False).returncode != 0:
                git(self.path, *IDENT, "commit", "-q", "-m", msg)
            elif not self.unpushed():
                return True  # nothing new and nothing left over from a failed push
            for _ in range(5):
                p = git(self.path, "push", "-q", check=False)
                if p.returncode == 0:
                    return True
                self._rebase_pull()
                time.sleep(2)
            print(f"[{now()}] warning: push failed, will retry later: "
                  f"{redact(p.stderr.strip())[:300]}", flush=True)
            return False

    def unpushed(self):
        """Local commits not on the remote yet (left by a push that failed)."""
        r = git(self.path, "rev-list", "--count", "@{u}..HEAD", check=False)
        return r.returncode != 0 or r.stdout.strip() != "0"

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
        self.mb.secrets = self.secrets
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
        """Check out the newest pushed commit of `branch` (default: the remote default branch).
        Returns (error or None, description, full sha): a job must run exactly what the agent
        pushed, so a failed fetch or checkout means the job does not run at all."""
        if not os.path.isdir(os.path.join(self.workdir, ".git")):
            return None, "workdir is not a git repo", None
        for attempt in range(3):
            f = git(self.workdir, "fetch", "-q", "--prune", "origin", check=False)
            if f.returncode == 0:
                break
            time.sleep(2 * attempt)
        else:
            return f"fetch failed: {redact(f.stderr.strip())[:300]}", "", None
        target = f"origin/{branch}" if branch else "origin/HEAD"
        r = git(self.workdir, "checkout", "-q", "--force", "--detach", target, check=False)
        if r.returncode:
            return f"checkout failed: {target}: {redact(r.stderr.strip())[:300]}", "", None
        sha = git(self.workdir, "rev-parse", "HEAD", check=False).stdout.strip()
        head = git(self.workdir, "log", "-1", "--format=%h %s", check=False).stdout.strip()
        return None, f"code {head} ({branch or 'default branch'})", sha

    def finish(self, name, done):
        with open(self.mb.p("out", name + ".done"), "w") as f:
            json.dump(done, f, indent=1)
        try:
            history.append(self.mb.p("out", "history.csv"), done)
        except Exception as e:
            print(f"[{now()}] warning: history not written: {e}", flush=True)

    def make_reports(self, job_dir, done, logpath):
        """report.md + charts for humans. Never shown to the agent, never fatal."""
        try:
            log_text = redact(open(logpath).read(), self.secrets) if logpath else None
            report.job_report(job_dir, done, log_text)
            self.mb.sync()  # so history.md can link the new report
            report.history_report(history.read(self.mb.p("out", "history.csv")), self.mb.p("out"))
        except Exception as e:
            print(f"[{now()}] charts skipped: {e}", flush=True)

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
        err, done["code"], sha = self.update_workdir(header(script, "branch"))
        if sha:
            done["commit"] = sha
        if err:
            done.update(exit=-3, error=err, seconds=0, end=now())
            self.finish(name, done)
            self.mb.push(f"{name}: not run, {err.split(':')[0]}")
            return
        live = self.mb.path.rstrip("/") + ".live"
        outdir, logpath = os.path.join(live, name), os.path.join(live, name + ".log")
        os.makedirs(outdir, exist_ok=True)
        # resume on a new machine: files this job already pushed are the starting point, so a job
        # that skips finished work (e.g. parts already in results.csv) does not redo it and its
        # pushed results are never overwritten by an empty copy
        pushed = self.mb.p("out", name)
        if os.path.isdir(pushed):
            seed_from_pushed(pushed, outdir)
        resumed = os.path.exists(self.mb.p("out", name + ".log"))
        if resumed and not os.path.exists(logpath):
            shutil.copyfile(self.mb.p("out", name + ".log"), logpath)
        self.mb.live = {name: outdir, name + ".log": logpath}
        env = job_env(COLAB_PILOT="1", PILOT_OUT=outdir, PILOT_JOB=name)
        t0 = time.time()
        self.state, self.job = "running", name
        self.heartbeat()
        self.mb.push(f"{name}: start")
        charts = (header(script, "charts") or "").lower() in ("on", "yes", "1") or \
            os.environ.get("PILOT_CHARTS") == "1"
        sampler = None
        if not no_gpu and (header(script, "telemetry") or "on").lower() != "off":
            sampler = telemetry.Sampler(os.path.join(outdir, "gpu.csv")).start()
        with open(logpath, "a") as log:
            log.write(f"# colab-pilot: {name} on {self.gpu}; {done['code']}"
                      f"{' (resumed)' if resumed else ''}\n")
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
                if "error" not in why:  # output ended normally: let bash report its own exit code
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
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
                if charts:
                    self.make_reports(outdir, done, logpath)
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


def seed_from_pushed(pushed, live):
    """Before a job (re)starts, take every file it already pushed unless the local copy is at least
    as large: on a new machine the local copy is missing, on the same machine after a restart it
    may be stale (e.g. an empty results file left by an earlier attempt). Results files only grow,
    so the larger copy is the newer one."""
    for root, _, files in os.walk(pushed):
        rel = os.path.relpath(root, pushed)
        for f in files:
            src = os.path.join(root, f)
            dst = os.path.normpath(os.path.join(live, rel, f))
            if not os.path.exists(dst) or os.path.getsize(dst) < os.path.getsize(src):
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def start(url, workdir, mailbox):
    """Clone/update the project at `workdir`, open the mailbox at `mailbox`, run until stopped."""
    if os.path.isdir(os.path.join(workdir, ".git")):
        git(workdir, "remote", "set-url", "origin", url, check=False)  # drop old token URLs
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
    use_token(tok)
    gpu = gpu_info()
    if gpu == "none":
        print("WARNING: no GPU. Runtime > Change runtime type > pick a GPU, then run again.")
    url = f"https://github.com/{repo}.git"
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
