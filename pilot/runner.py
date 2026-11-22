"""colab-pilot runner: executes jobs from a git mailbox branch inside a notebook.

Usage in a notebook cell (after cloning the mailbox branch into MAILBOX):
    %env PILOT_MAILBOX=/content/mailbox
    %run pilot/runner.py
Environment:
    PILOT_MAILBOX  clone of the mailbox branch (required)
    PILOT_WORKDIR  directory jobs run in (default: current directory)
    POLL_S=20 PUSH_S=45 IDLE_MIN=120 MAX_HOURS=12
"""
import json, os, re, signal, subprocess, threading, time
from datetime import datetime, timezone

VERSION = "0.1.0"
SECRET_RE = re.compile(r"TOKEN|SECRET|KEY|PASSWORD", re.I)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def secrets():
    return [v for k, v in os.environ.items() if SECRET_RE.search(k) and len(v) >= 8]


def redact(text, vals):
    for v in vals:
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


class Mailbox:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", self.path, *args], capture_output=True,
                              text=True, check=check)

    def pull(self):
        with self.lock:
            self.git("pull", "-q", "--rebase", check=False)

    def push(self, msg):
        with self.lock:
            self.git("add", "-A", "out")
            if self.git("diff", "--cached", "--quiet", check=False).returncode == 0:
                return
            self.git("commit", "-q", "-m", msg)
            for _ in range(5):
                if self.git("push", "-q", check=False).returncode == 0:
                    return
                self.git("pull", "-q", "--rebase", check=False)
                time.sleep(2)

    def p(self, *parts):
        return os.path.join(self.path, *parts)


class Runner:
    def __init__(self):
        self.mb = Mailbox(os.environ["PILOT_MAILBOX"])
        self.workdir = os.environ.get("PILOT_WORKDIR", os.getcwd())
        self.poll = float(os.environ.get("POLL_S", 20))
        self.push_s = float(os.environ.get("PUSH_S", 45))
        self.idle = float(os.environ.get("IDLE_MIN", 120)) * 60
        self.max_s = float(os.environ.get("MAX_HOURS", 12)) * 3600
        self.gpu = gpu_info()
        self.secrets = secrets()
        self.state, self.job = "starting", None
        os.makedirs(self.mb.p("out"), exist_ok=True)

    def heartbeat(self):
        hb = {"state": self.state, "job": self.job, "gpu": self.gpu, "time": now(),
              "version": VERSION}
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
        return os.path.exists(self.mb.p("cmd", "STOP"))

    def run_job(self, name):
        script = open(self.mb.p("cmd", name + ".sh")).read()
        timeout = float(header(script, "timeout") or 0) or None
        want = header(script, "gpu")
        done = {"job": name, "start": now(), "gpu": self.gpu}
        if want and want.lower() != "any" and want.lower() not in self.gpu.lower():
            done.update(exit=-2, error=f"wrong gpu: want {want}", seconds=0, end=now())
            json.dump(done, open(self.mb.p("out", name + ".done"), "w"), indent=1)
            self.mb.push(f"{name}: skipped, wrong gpu")
            return
        outdir = self.mb.p("out", name)
        os.makedirs(outdir, exist_ok=True)
        env = dict(os.environ, COLAB_PILOT="1", PILOT_OUT=outdir, PILOT_JOB=name)
        logpath = self.mb.p("out", name + ".log")
        t0 = time.time()
        self.state, self.job = "running", name
        self.heartbeat()
        self.mb.push(f"{name}: start")
        with open(logpath, "w") as log:
            proc = subprocess.Popen(["bash", "-c", script], cwd=self.workdir, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, start_new_session=True)
            stop_flag = threading.Event()

            def pusher():
                while not stop_flag.wait(self.push_s):
                    log.flush()
                    self.heartbeat()
                    self.mb.push(f"{name}: log")
                    self.mb.pull()
                    if self.stopped():
                        kill(proc)

            th = threading.Thread(target=pusher, daemon=True)
            th.start()
            killer = threading.Timer(timeout, kill, [proc]) if timeout else None
            if killer:
                killer.start()
            try:
                for line in proc.stdout:
                    log.write(redact(line, self.secrets))
            except KeyboardInterrupt:
                kill(proc)
                raise
            finally:
                code = proc.wait()
                kill(proc)  # whole group: no stray GPU processes survive the job
                stop_flag.set()
                if killer:
                    killer.cancel()
        done.update(exit=code, seconds=round(time.time() - t0, 1), end=now())
        if timeout and done["seconds"] >= timeout:
            done["error"] = "timeout"
        json.dump(done, open(self.mb.p("out", name + ".done"), "w"), indent=1)
        self.state, self.job = "idle", None
        self.heartbeat()
        self.mb.push(f"{name}: done exit={code}")

    def loop(self):
        print(f"colab-pilot {VERSION}: gpu={self.gpu}, mailbox={self.mb.path}", flush=True)
        t_start = last_job = time.time()
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
            self.heartbeat()
            self.mb.push("heartbeat")
            time.sleep(self.poll)
        self.heartbeat()
        self.mb.push(f"runner exit: {self.state}")
        print(f"colab-pilot exit: {self.state}. The runtime is still on; shut it down yourself.")


def kill(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


if __name__ == "__main__":
    Runner().loop()
