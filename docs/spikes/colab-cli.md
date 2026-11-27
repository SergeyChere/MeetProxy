# Spike: Colab CLI lifecycle

Stage 0 of [DESIGN.md](../DESIGN.md#15-stages-and-acceptance-gates). Goal: learn, on real sessions,
what the official Colab CLI can and cannot do for MeetProxy's lifecycle — **before** building the
adapter. Until this page holds results, every Colab capability in DESIGN §9 is **provisional**.

Rules of evidence (DESIGN §4.1): **absence is not evidence.** A process that is gone, a missing file
or an ended session prove nothing about *why*. Only a positive signal tied to the job's identity
counts (an acknowledgement file with the job's nonce, a provider status naming the session).

## Before you start

- **Where:** your own computer; Claude Code can run the steps with you present (the CLI signs in
  through a browser). Not in a cloud sandbox.
- **Budget:** decide a cap before step 1 — proposal: **at most 2 T4 sessions at a time, 3 session
  hours in total**. Write it here: `cap: ____`. Stop at the cap even if steps remain.
- **Names:** every session is `meet-spike-<scenario>-<random 4 hex>`, never reused.
- **Inventory:** run `colab sessions` (save the output with a timestamp) **before and after every
  acquire and every release**. Every session that appears must be accounted for in the cleanup table.
- **Fresh directories:** every scenario uses its own directory `~/meet-spike/<scenario>-<nonce>/` on
  the VM, so files from an earlier scenario cannot be mistaken for this one's.
- **Record:** exact commands, full output (files next to this page), CLI version, UTC timestamps,
  session IDs (or redacted equivalents). Every capability ends as **PASS / FAIL / UNKNOWN**, and an
  *observation* (what happened once) is kept apart from a *guarantee* (what the provider documents).

## Helper scripts

`spike_job.py` — behaves like the future wrapper: identity, heartbeat, terminal events, and a
positive acknowledgement when it is cancelled on purpose.

```python
import json, os, signal, sys, time, uuid
d = sys.argv[1]                       # fresh directory per scenario
quiet = "--quiet" in sys.argv         # no output at all (idle-timeout test)
seconds = int(next((a.split("=")[1] for a in sys.argv if a.startswith("--seconds=")), "300"))
os.makedirs(d, exist_ok=False)        # refuses a directory that already exists
nonce = uuid.uuid4().hex
ident = {"nonce": nonce, "pid": os.getpid(),
         "boot_id": open("/proc/sys/kernel/random/boot_id").read().strip(),
         "start": open(f"/proc/{os.getpid()}/stat").read().split()[21]}
json.dump(ident, open(f"{d}/identity.json", "w"))
def event(kind):
    with open(f"{d}/events.jsonl", "a") as f:
        f.write(json.dumps({"event": kind, "nonce": nonce, "t": time.time()}) + "\n")
def on_term(signum, frame):            # intentional cancel = SIGTERM from the controller
    event("cancel_ack")
    sys.exit(143)
signal.signal(signal.SIGTERM, on_term)
event("started")
print("IDENTITY", json.dumps(ident), flush=True)
for i in range(seconds // 5):
    open(f"{d}/heartbeat", "w").write(f"{i} {time.time()}\n")
    if not quiet:
        print("tick", i, flush=True)
    time.sleep(5)
event("finished")
print("DONE", flush=True)
```

`spike_probe.py <dir>` — what is known about that scenario's job right now.

```python
import json, os, sys, time
d = sys.argv[1]
ident = json.load(open(f"{d}/identity.json")) if os.path.exists(f"{d}/identity.json") else None
events = [json.loads(l) for l in open(f"{d}/events.jsonl")] if os.path.exists(f"{d}/events.jsonl") else []
alive = False
if ident and os.path.exists(f"/proc/{ident['pid']}/stat"):
    same_boot = open("/proc/sys/kernel/random/boot_id").read().strip() == ident["boot_id"]
    same_start = open(f"/proc/{ident['pid']}/stat").read().split()[21] == ident["start"]
    alive = same_boot and same_start            # a reused PID does not count
hb = open(f"{d}/heartbeat").read().strip() if os.path.exists(f"{d}/heartbeat") else None
print(json.dumps({"now": time.time(), "identity": ident, "alive": alive, "heartbeat": hb,
                  "events": [e["event"] for e in events if ident and e["nonce"] == ident["nonce"]]}))
```

`spike_cancel.py <dir>` — cancels only the process that matches the recorded identity.

```python
import json, os, signal, sys
d = sys.argv[1]
ident = json.load(open(f"{d}/identity.json"))
stat = open(f"/proc/{ident['pid']}/stat").read().split()
if stat[21] != ident["start"]:
    sys.exit("identity mismatch: not our process")
os.kill(ident["pid"], signal.SIGTERM)
print("SIGTERM sent to", ident["pid"])
```

## Scenarios

| # | Scenario | Steps (adapt flags to `colab --help`) | Record |
|---|---|---|---|
| 1 | Install, version | `pip install google-colab-cli` · `colab --version` · `colab --help > help.txt` | version, Python, OS |
| 2 | Sign-in | the CLI's auth command; then its status command | interactive only? needs a TTY? where stored? can status be checked **without side effects** (for `meet doctor`)? |
| 3 | Acquire + inventory | inventory · `colab new -s meet-spike-acq-<rnd> --gpu T4` · inventory | time to ready, output format, session ID |
| 4 | Same name twice | inventory · repeat 3 with the **same** name · inventory · release any extra session at once | error, reuse, or a second (paid) session? → idempotency |
| 5 | Normal exit | upload the helpers; `colab exec -s … -f spike_job.py -- ~/meet-spike/exit-<n> --seconds=30` · probe | `finished` event present, `alive: false` |
| 6 | Client killed, job alive? | start `spike_job.py ~/meet-spike/kill-<n>` (300 s); after 30 s `kill -9` the **local** `colab` process; then probe from a new terminal | does the job keep running (`alive: true`, heartbeat advancing, same nonce)? |
| 7 | Reconnect | from a new terminal: `colab sessions`, probe; try any CLI way to re-attach to the job's output | session found by name after client loss? output re-attachable, or only files? |
| 8 | Intentional cancel | `spike_cancel.py` on the job from 6 · probe | `cancel_ack` with the matching nonce → **only this** counts as CANCELLED |
| 9 | External kill (no ack) | start a job in a fresh dir; kill it with `kill -9 <pid>` via exec/ssh · probe | gone, **no** `cancel_ack` → must stay UNKNOWN for the adapter, never CANCELLED |
| 10 | Stale evidence | probe the directory of scenario 5 while pretending it is a new job's | nonce mismatch is detected; stale `finished` is not taken for the new job |
| 11 | Idle vs wall-clock | `spike_job.py … --quiet --seconds=600`; also the CLI's timeout option if any | does `exec` cut a silent job, when? does it cut a talkative long job? idle limit or wall-clock? |
| 12 | Expiry, idle session | stop any local keep-alive the CLI runs; leave a session idle; inventory every 10 min up to 90 min | ends by itself? when? (observation only) |
| 13 | Expiry, client gone during compute | start a 30-min job, then close the CLI and any keep-alive (simulate a sleeping laptop); inventory every 10 min | does compute keep the session alive, does it end, when? (observation only) |
| 14 | Documented guarantee | search Colab CLI docs for a server-side TTL / max-runtime option | quote + link, or "none found" |
| 15 | Bash through Python | exec a Python one-liner running `subprocess.run(["bash","-c","nvidia-smi; echo ok"])` | arbitrary bash via the wrapper: yes/no |
| 16 | Snapshot without history | in a test repo, commit a file `secret.txt`, delete it in the next commit; `git archive --format=tar HEAD -o snap.tar`; write `manifest.txt` = `git rev-parse HEAD` + `git ls-tree -r HEAD`; upload both; on the VM unpack, check every blob hash against the manifest (`git hash-object`), and `tar tf snap.tar \| grep secret` | content matches the manifest; `secret.txt` absent. (A normal `git bundle` carries history — check that too and record it.) |
| 17 | Verified download | create a 50 MB file on the VM, `sha256sum`, `colab download`, compare; interrupt a download once | checksum match; what an interrupted download leaves behind |
| 18 | GPU facts | `nvidia-smi --query-gpu=index,name,memory.total,driver_version,clocks.max.sm,power.limit,clocks_throttle_reasons.active --format=csv` | which fields work; CUDA version |
| 19 | Release, twice | `colab stop -s …` · inventory · `colab stop -s …` again | gone? second stop: error or no-op (idempotency)? |

## Results

CLI version: … · Date (UTC): … · GPU / driver / CUDA: … · Budget used: … session hours

| Capability (DESIGN §9) | PASS / FAIL / UNKNOWN | Observation or guarantee? | Evidence (scenario, file, timestamp) |
|---|---|---|---|
| sign-in checkable without side effects | | | 2 |
| acquire a GPU by type | | | 3 |
| idempotent acquire (same name) | | | 4 |
| job survives client loss | | | 6 |
| find the session after client loss | | | 7 |
| observe a running job after reconnect | | | 7 |
| re-attach to its output stream | | | 7 |
| confirmed cancel (ack tied to identity) | | | 8 |
| external kill distinguishable from cancel | | | 9 |
| stale evidence detected | | | 10 |
| exec timeout semantics (idle / wall-clock) | | | 11 |
| session expiry when idle | | observation | 12 |
| session expiry when the client is gone | | observation | 13 |
| server-side TTL / max runtime | | guarantee? | 14 |
| arbitrary bash via Python | | | 15 |
| history-free snapshot verified | | | 16 |
| verified download | | | 17 |
| telemetry fields available | | | 18 |
| idempotent release | | | 19 |

## Cleanup

| Session name | Created (UTC) | Released (UTC) | How confirmed |
|---|---|---|---|
| | | | |

Final inventory (must show no `meet-spike-*` session): …

## Conclusions for the adapter

(to fill after the spike: what the Colab adapter may promise, what it reports as best-effort, what
is unsupported. Nothing that stayed UNKNOWN is claimed.)
