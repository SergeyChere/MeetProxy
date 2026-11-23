---
name: colab-pilot
description: Run GPU experiments (CUDA kernels, PyTorch training, benchmarks) on the user's Google Colab GPU from a coding agent, through a git branch used as a mailbox. Use when the user wants code run "on my Colab", "on the GPU", or asks to benchmark or test something that needs a GPU the agent does not have.
---

# colab-pilot

You have no GPU, the user has a Colab runtime. You exchange work through the branch `pilot` of the
user's project repository: you push jobs (bash scripts) to `cmd/`, a loop in the Colab notebook runs
them and pushes logs and results to `out/`. No ports, tunnels or shells are opened.

## 1. Set up (once per session)

From the root of the user's project repository (it must have a GitHub `origin` you can push to):

```bash
bash <skill-dir>/scripts/setup.sh
```

It installs the `pilot` command (`pip install git+https://github.com/SergeyChere/colab-pilot`),
opens the mailbox in `.pilot/` (git-excluded) and prints the runner status.

If it says **no runner is connected**, tell the user this, filling in `<owner/repo>`, then keep
working on the experiment while you wait:

> Open https://colab.research.google.com/github/SergeyChere/colab-pilot/blob/main/colab_runner.ipynb,
> choose *Runtime → Change runtime type → GPU*, type `<owner/repo>` in the REPO field, *Run all*.
> First time only: in Colab's key icon add a secret `GH_TOKEN` — a GitHub fine-grained token for
> this one repository with *Contents: Read and write*.

Check again with `pilot status` until it shows `runner: idle | gpu: <name>`.

## 2. Run an experiment

1. **Commit and push** the code. The GPU runs the latest *pushed* commit of your current branch;
   uncommitted or unpushed changes never reach it (`pilot send` warns about them).
2. Write a job script. Start from `templates/job.sh` in this skill: it has the header lines and the
   results CSV already set up.
3. Run it:
   - short job: `pilot run s01_bench job.sh` — sends, streams the log, exits with the job's exit code;
   - long job: `pilot send s01_bench job.sh`, keep working, later `pilot wait s01_bench` (without
     `--follow`: it would stream the whole log into your context), then `pilot logs s01_bench --tail 50`.
4. Read the result: the log, `.pilot/out/<job>.done` (exit code, seconds, GPU, commit) and
   `.pilot/out/<job>/results.csv`.
5. Read the **`gpu ...` line** at the end of the log (also `gpu_check` in the `wait` output). The
   runner samples the GPU during every job and reports only what was off:
   - `gpu ok: util 97%, mem 41%, 68°C` — nothing to worry about;
   - `idle N%` / `util avg N%` — the GPU waits for CPU, data loading or copies, not for your kernel;
   - `thermal throttle`, `hw slowdown`, `SM clock unstable` — timings are distorted, do not compare;
   - `mem peak N%` — close to out-of-memory;
   - `other GPU procs` / `GPU busy at start` — the GPU was shared.
   Full numbers are in `gpu_stats` in `.done`, every sample in `.pilot/out/<job>/gpu.csv`.
   `# telemetry: off` in a job disables it.
6. **Compare runs** with `pilot history` — one line per finished job (GPU, commit, seconds, exit,
   util, flags) — instead of reopening old logs.

Other commands: `pilot logs <job> --tail 50`, `pilot status`, `pilot stop` (ends the runner).

## For the human, not for you

- When the user asks for charts or a report: add `# charts: on` to the job, or run
  `pilot report <job>` / `pilot report history`, and give them the printed path. On GitHub the
  reports are in branch `pilot`, folder `out/`, and render with their charts.
- **Never open, read or summarize** `report.md`, `history.md` or `charts/*.svg`: they are drawn
  for people, cost you tokens, and hold nothing that `.done` and `history.csv` do not.
- `pilot export [job…|--all]` copies results into `pilot-runs/` of the project; it commits
  nothing. Commit only if the user asks.

## 3. Job script rules

- Header lines: `# timeout: <seconds>` (always), `# gpu: any` (or `T4`, `L4`, `A100` when numbers
  matter — the job is refused on another GPU).
- Self-contained bash, run from the project root: install and build what it needs.
- Append one CSV line per measurement to `$PILOT_OUT/results.csv`; it is pushed during the run, so
  a job that dies halfway still leaves data.
- Job names are unique and sortable (`s01_build`, `s02_bench`). A name runs only once.
- When the user is away, send one longer script that runs every planned variant instead of many
  small jobs.

## 4. Reading results honestly

- Compare timings only from the same GPU — check the GPU in `.done`.
- A result that looks too good (identical times, 0.2 s for a big job) usually means caching, a
  skipped step or wrong input. Read the log before reporting.
- Check that each variant gives correct output, not only that it is fast.

## 5. Never

Print secrets, open network services or tunnels, try to stop or delete the Colab runtime, or merge
the `pilot` branch into anything. Tell the user in one line whenever they must act (reconnect, pick
a GPU, add the secret). If `pilot status` says the runner went silent, the runtime was probably
disconnected: ask them to reconnect and run the notebook again.

See `reference/troubleshooting.md` when something does not work.

## What this skill does on the network

Installs a Python package from GitHub, and runs `git fetch/pull/push` against the user's own
repository (branch `pilot`). Nothing else. The Colab side executes whatever is pushed to
`cmd/`, so only trusted people should have write access to the repository.
