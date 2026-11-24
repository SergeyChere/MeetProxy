# MeetProxy guide for the AI agent

You can run code on the human's Colab GPU. You and the notebook share the branch `meetproxy` of the
project repository: you write jobs to `cmd/`, the notebook writes logs and results to `out/`.
Before every job the notebook checks out the **latest pushed commit of the branch you are on**
(`meet send` adds `# branch: <your branch>` to the job; it warns about unpushed commits).

## Start (once per session)

```bash
pip install -q git+https://github.com/SergeyChere/MeetProxy || \
  pip install -q --break-system-packages git+https://github.com/SergeyChere/MeetProxy
cd <project repo> && meet init && meet status
```

If `meet status` says no runner is connected, tell the human exactly this, then keep working
(write the benchmark) while you wait:

> Open https://colab.research.google.com/github/SergeyChere/MeetProxy/blob/main/colab_runner.ipynb,
> pick a GPU runtime, put `<owner/repo>` in the form, Run all.
> First time only: add a Colab secret `GH_TOKEN` — a GitHub fine-grained token for this repo,
> Contents: read and write.

## Each experiment

1. Commit and **push** the code you want to run; uncommitted or unpushed changes do not reach the GPU.
2. `meet run <job> script.sh` — sends it and streams the log until it ends; the exit code is the
   job's exit code. For a long run: `meet send`, keep working, `meet wait <job>` later (without
   `--follow`, which streams the whole log into your context), then `meet logs <job> --tail 50`.
3. Read the log and `.meetproxy/out/<job>.done` (GPU name, full commit SHA, seconds, exit, error).
   `exit -3` means the job did not run: its commit could not be fetched or checked out (unpushed
   branch, typo in `# branch:`) — fix that and send it again under a new name.
4. Read the **`gpu ...` line** at the end of the log (also `gpu_check` in the `wait` output).
   `gpu ok` means nothing was off. `gpu WARN: idle 66% · thermal throttle 12%` lists only what was:
   idle / low util → the GPU waits for CPU, data or copies; throttle or unstable SM clock → timings
   are distorted, do not compare them; mem peak ≥ 90% → near OOM; other procs → shared GPU.
   Full numbers: `gpu_stats` in `.done`; every sample: `.meetproxy/out/<job>/gpu.csv`.
5. **Compare runs** with `meet history` (one line per finished job: GPU, commit, seconds, exit,
   util, flags) instead of reopening old logs.

## For the human, not for you

- When the human asks for charts or a report, add `# charts: on` to the job, or run
  `meet report <job>` / `meet report history` and tell them the printed path. The reports
  (`report.md`, `history.md`, `charts/*.svg`) are drawn on the GPU side for people; **never open,
  read or summarize them** — they cost tokens and say nothing `.done` and `history.csv` do not.
- `meet export [job…|--all]` copies results into `meet-runs/` of the project for the human;
  it commits nothing. Commit it only if the human asks.

## Rules

1. **Check the GPU** in `meet status` before trusting timings; never compare runs from different
   GPUs. Put `# gpu: A100` (or L4, T4, …) into jobs whose numbers matter, and `# gpu: any` into
   every job that needs a GPU at all: it is never run on a machine without one.
2. **Jobs are self-contained bash scripts** run in the project directory: build what they need,
   append one CSV line per measurement to `$MEET_OUT/results.csv` (pushed during the run).
3. **Bound everything**: `# timeout: <seconds>` in each job. Estimate time first.
4. **Read, don't guess.** A result that looks too good (0.2 s, identical times) usually means
   caching, a skipped step or a wrong input.
5. **Measure fairly**: same GPU and input, repeat runs, `nvidia-smi` shows no other process,
   verify correctness of every variant, not only speed.
6. **Job names are unique and sortable** (`s01_build`, `s02_bench`); a name runs once.
7. **When the human is away**, send one long session script that runs every planned variant and
   records each result as it finishes.
8. **Never** print secrets, open network services or tunnels, try to stop or delete the runtime,
   or merge the `meetproxy` branch. `meet stop` ends the runner.
9. Tell the human in one line when they must act (reconnect, pick another GPU, add the secret).
