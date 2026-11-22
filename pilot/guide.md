# colab-pilot guide for the AI agent

You can run code on the human's Colab GPU. You and the notebook share the branch `pilot` of the
project repository: you write jobs to `cmd/`, the notebook writes logs and results to `out/`.
Before every job the notebook checks out the **latest pushed commit of the branch you are on**
(`pilot send` adds `# branch: <your branch>` to the job; it warns about unpushed commits).

## Start (once per session)

```bash
pip install -q git+https://github.com/SergeyChere/colab-pilot || \
  pip install -q --break-system-packages git+https://github.com/SergeyChere/colab-pilot
cd <project repo> && pilot init && pilot status
```

If `pilot status` says no runner is connected, tell the human exactly this, then keep working
(write the benchmark) while you wait:

> Open https://colab.research.google.com/github/SergeyChere/colab-pilot/blob/main/examples/colab_runner.ipynb,
> pick a GPU runtime, put `<owner/repo>` in the form, Run all.
> First time only: add a Colab secret `GH_TOKEN` — a GitHub fine-grained token for this repo,
> Contents: read and write.

## Each experiment

1. Commit and **push** the code you want to run; uncommitted or unpushed changes do not reach the GPU.
2. `pilot run <job> script.sh` — sends it and streams the log until it ends; the exit code is the
   job's exit code. For a long run: `pilot send`, keep working, `pilot wait <job> --follow` later.
3. Read the log and `.pilot/out/<job>.done` (GPU name, commit, seconds, exit, error).

## Rules

1. **Check the GPU** in `pilot status` before trusting timings; never compare runs from different
   GPUs. Put `# gpu: A100` (or L4, T4, …) into jobs whose numbers matter.
2. **Jobs are self-contained bash scripts** run in the project directory: build what they need,
   append one CSV line per measurement to `$PILOT_OUT/results.csv` (pushed during the run).
3. **Bound everything**: `# timeout: <seconds>` in each job. Estimate time first.
4. **Read, don't guess.** A result that looks too good (0.2 s, identical times) usually means
   caching, a skipped step or a wrong input.
5. **Measure fairly**: same GPU and input, repeat runs, `nvidia-smi` shows no other process,
   verify correctness of every variant, not only speed.
6. **Job names are unique and sortable** (`s01_build`, `s02_bench`); a name runs once.
7. **When the human is away**, send one long session script that runs every planned variant and
   records each result as it finishes.
8. **Never** print secrets, open network services or tunnels, try to stop or delete the runtime,
   or merge the `pilot` branch. `pilot stop` ends the runner.
9. Tell the human in one line when they must act (reconnect, pick another GPU, add the secret).
