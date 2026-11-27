# Spike: Colab CLI lifecycle

Stage 0 of [DESIGN.md](../DESIGN.md#15-stages-and-acceptance-gates). Goal: learn, on a real session,
what the official Colab CLI can and cannot do for MeetProxy's lifecycle — **before** building the
adapter. Nothing in the design is claimed for Colab until this page holds the facts.

- **Where:** your own computer (Claude Code can run it with you there; the CLI signs in through a
  browser). It cannot run in a cloud sandbox.
- **GPU:** one T4 session, the cheapest. Expected total: under 2 hours of runtime.
- **Rule:** every session created here is named `meet-spike-*` and is stopped at the end (step 13).
- **Record:** exact commands, full output (or a file next to this page), CLI version, date. Fill the
  tables at the bottom. "Did not work" is a valid, valuable result.

## 0. Helper job

Save as `spike_job.py` in an empty folder. It behaves like the future wrapper: writes its identity,
then a heartbeat file every 5 s for 5 minutes.

```python
import json, os, sys, time, uuid
d = os.path.expanduser("~/meet-spike")
os.makedirs(d, exist_ok=True)
ident = {"nonce": uuid.uuid4().hex, "pid": os.getpid(),
         "boot_id": open("/proc/sys/kernel/random/boot_id").read().strip(),
         "start": open(f"/proc/{os.getpid()}/stat").read().split()[21]}
json.dump(ident, open(f"{d}/identity.json", "w"))
print("IDENTITY", json.dumps(ident), flush=True)
quiet = "--quiet" in sys.argv          # step 8: no output at all
for i in range(60):
    open(f"{d}/heartbeat", "w").write(f"{i} {time.time()}\n")
    if not quiet:
        print("tick", i, flush=True)
    time.sleep(5)
open(f"{d}/done", "w").write("ok\n")
print("DONE", flush=True)
```

And `spike_probe.py` (prints what is running and the last heartbeat):

```python
import os, subprocess, time
d = os.path.expanduser("~/meet-spike")
for f in ("identity.json", "heartbeat", "done"):
    p = f"{d}/{f}"
    print(f, open(p).read().strip() if os.path.exists(p) else "-")
print("now", time.time())
print(subprocess.run(["bash", "-c", "ps -eo pid,lstart,cmd | grep spike_job | grep -v grep"],
                     capture_output=True, text=True).stdout)
```

## Steps

| # | What | Commands (adapt to `colab --help`) | Record |
|---|---|---|---|
| 1 | Install, version | `pip install google-colab-cli` · `colab --version` · `colab --help > help.txt` | version, Python, OS |
| 2 | Sign-in | the CLI's auth command | interactive only? needs a TTY? where are credentials stored? can it be checked without side effects (for `meet doctor`)? |
| 3 | Acquire | `colab new -s meet-spike-1 --gpu T4` | time to ready; output format (JSON option?); run it **again with the same name** — error, reuse, or a second session? (idempotency) |
| 4 | Discovery | `colab sessions` before and after step 3; then close the terminal, open a new one, run it again | is the session found by name after the client is gone? machine-readable output? |
| 5 | Long job, then lose the client | `colab exec -s meet-spike-1 -f spike_job.py`; after ~30 s kill the local process (`Ctrl-C`, then separately `kill -9` in a second try) | does the remote job keep running? (check with step 6) |
| 6 | Observe after loss | `colab exec -s meet-spike-1 -f spike_probe.py` (or `colab ssh`) | heartbeat still advancing? same identity (nonce, boot_id, start)? can stdout of the running job be re-attached at all? |
| 7 | Cancel | kill the remote job via `colab ssh` or a small exec script using the identity from step 6; probe again | is cancellation confirmable (process gone **and** no `done` file)? |
| 8 | Idle vs wall-clock | `colab exec … -f spike_job.py --quiet` (no output for 5 min); try the CLI's timeout option if any | does exec cut a silent job? after how long? is the limit idle-based or wall-clock? |
| 9 | Session expiry | after step 8, stop any keep-alive the CLI runs locally (see `--help`), leave the session idle; check `colab sessions` every 10 min (up to 90 min) | does Colab end an idle session by itself, after how long? is there a server-side TTL option? what happens if the laptop sleeps? |
| 10 | Bash | `colab exec` a Python one-liner that runs `subprocess.run(["bash","-c","nvidia-smi; echo ok"])` | can the wrapper run arbitrary bash through Python? |
| 11 | Transfer | in a test repo: `git bundle create one.bundle HEAD`; `colab upload` it; on the VM `git clone one.bundle && git rev-parse HEAD`; `colab download` a 50 MB file and compare `sha256sum` | exact SHA arrives? resumable/partial download behaviour? |
| 12 | GPU facts | exec: `nvidia-smi --query-gpu=index,name,memory.total,driver_version,clocks.max.sm,power.limit,clocks_throttle_reasons.active --format=csv` | which fields work on this driver; CUDA version (`nvcc --version` / `nvidia-smi`) |
| 13 | Release | `colab stop -s meet-spike-1`; `colab sessions` | gone? any session left from steps 3–9? (stop them all) |

## Results

CLI version: … · Date: … · GPU / driver / CUDA: …

| Capability (DESIGN §9) | Result | Evidence |
|---|---|---|
| acquire a GPU by type | | step 3 |
| idempotent acquire (same name twice) | | step 3 |
| find the session after the client is gone | | step 4 |
| job survives client loss | | step 5–6 |
| observe a running job after reconnect | | step 6 |
| re-attach to its output stream | | step 6 |
| confirmed cancel | | step 7 |
| exec timeout semantics (idle / wall-clock) | | step 8 |
| server-side session expiry | | step 9 |
| arbitrary bash via Python | | step 10 |
| exact commit via bundle | | step 11 |
| verified download | | step 11 |
| telemetry fields available | | step 12 |
| release | | step 13 |
| sign-in checkable without side effects | | step 2 |

## Conclusions for the adapter

(to fill after the spike: what the Colab adapter can promise, what it must report as best-effort,
what is unsupported)
