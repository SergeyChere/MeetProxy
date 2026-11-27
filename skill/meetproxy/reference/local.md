# Local card

Read this only for the route "NVIDIA card in this machine". Instructions only: no MeetProxy helper
checks these steps yet, so follow them exactly and say so in the report.

**Before each run**
- `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader` — the GPU; no other
  process on it (`nvidia-smi --query-compute-apps=pid --format=csv,noheader` is empty).
- `git rev-parse HEAD` — the commit; if `git status --porcelain` is not empty, the run is
  **dirty / unverified**: record that, never present it as a run of the commit.

**Run with a deadline that also stops child processes**

```bash
timeout --kill-after=30 --signal=TERM <seconds> setsid bash job.sh > run.log 2>&1; echo "exit $?"
```

Exit 124 means the deadline ended it. Afterwards check `nvidia-smi` again: if a process from this
run is still on the GPU, report it instead of starting the next run.

**After each run** — run the oracle as its own command, record its exit code, copy the measured
values from the output files into `variants.jsonl` (SKILL.md section 4).

Cleanup state at the end: *nothing left running* only if `nvidia-smi` shows no process of yours.
