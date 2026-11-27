---
name: meetproxy
description: Run evidence-backed GPU experiment campaigns (CUDA kernels, PyTorch, benchmarks) on GPUs the user already has — their local NVIDIA card or Google Colab — and come back with the best verified variant and its evidence. Use when the user wants code made faster or tested on a GPU, a set of variants compared, or something run "on my GPU" / "on my Colab".
---

# MeetProxy

You run GPU experiments for the user on GPUs they already have and return the **best verified
result with its evidence**, not just numbers. You reason and propose; correctness is decided by the
project's own checks, never by your judgement. The user chooses the GPU; you never switch it.

## 1. Campaign

For anything beyond a single run, work as a campaign:

1. **State it, then ask once.** Objective metric (e.g. kernel time), baseline, **correctness
   oracle** (prefer the project's existing tests, reference implementation or known exact results),
   the approved GPU(s), a time and money limit, stop conditions, and the **reference GPU** that will
   decide the winner. Get the user's approval of this once; stay inside it.
2. **Check what was tried.** Read the campaign records (section 4) for earlier variants and why they
   were rejected. A prior failure is a suggestion, not a ban: retest when the GPU, input or code
   changed, and say why.
3. **Run variants** — sequentially on one GPU is a valid campaign. Use several GPUs at once only
   when the gain clearly outweighs extra setup, transfer and compilation.
4. **Reject incorrect variants whatever their speed.** Compare timings only on the same GPU type
   with the same input.
5. **Different GPUs screen, one decides.** If you screened on several GPUs, keep part of the budget
   for the end, shortlist by a rule you stated in step 1 (keep variants strong on any one GPU), and
   re-run finalists and the baseline on the reference GPU. Only that matched run names a winner;
   otherwise report a winner per GPU type or "insufficient evidence".
6. **Propose the next round** from the results, inside the approved limits.
7. **Stop** on a stop condition or the limit. Release anything you started.
8. **Report:** best verified variant vs baseline (with the matched numbers), what was rejected and
   why, total cost where known (GPU time, paid sessions, your own tokens if the host shows them).
   If nothing beat the baseline, say so.

For a single "run this on my GPU": run it once with a timeout, report exit code, time, GPU and the
commit that ran, in one or two lines.

## 2. Where the GPU is

Use only the GPU the user named or approved. If a route is missing a capability (not installed,
not signed in, no network), **say which and stop** — do not fall back to another destination.

| The user has | Route |
|---|---|
| an NVIDIA card in this machine | run directly: `nvidia-smi` for the GPU name, `timeout <seconds> bash job.sh` for every run |
| Colab, and the official Colab CLI or its skill is installed and signed in | follow that tool's own instructions to run each job; the rules of sections 1, 3–5 still apply |
| Colab, and the official tool is not available | the **mailbox route** (section 6) |

Do not assume you can call another skill from this one; use command-line tools.

## 3. Honest results

- Correctness first: run the oracle for **every** variant and record its exit code. A variant
  whose oracle fails, or that has no oracle, is never called the winner.
- Repeat timed runs (≥ 3), same input, nothing else on the GPU (`nvidia-smi`); report spread.
- A result that looks too good (0.2 s, identical times) usually means caching, a skipped step or
  wrong input — read the log before reporting.
- Copy numbers from result files; never type a measurement from memory.
- Throttling, an idle or shared GPU distort timings: do not compare those runs.

## 4. Records

Keep one folder per campaign in the project, `meet-runs/<campaign>/`, plain files the user owns:

- `campaign.json` — what you stated in step 1 (objective, baseline, oracle command, approved GPUs,
  limits, reference GPU, shortlist rule).
- `variants.jsonl` — one line per run: variant id, parent, hypothesis in one sentence, commit, GPU,
  oracle exit code, measured values (copied from results), verdict, reason if rejected.
- results and logs of each run next to it.

Measured facts and your interpretation go in separate fields. Commit these files only if the user
asks.

## 5. Safety

- Never start paid compute or a new destination without the user's approval; every run has a
  timeout; release sessions you started.
- Code leaves this machine only to a destination the user approved for this repository.
- Never print secrets or tokens, never put them in files, commands or chat; never open network
  services or tunnels.
- Job code runs as the user: run only code you would run on their machine.
- Tell the user in one line whenever they must act (approve, sign in, reconnect, pick a GPU).

## 6. Mailbox route

Today's Colab route without the official tool: you push jobs (bash scripts) to `cmd/` on the branch
`meetproxy` of the user's repository; a loop in a Colab notebook runs them and pushes logs and
results to `out/`. No ports, tunnels or shells are opened. Needs a GitHub `origin` you can push to.

### Set up (once per session)

```bash
bash <skill-dir>/scripts/setup.sh
```

It uses `meet` only if `meet --version` is exactly the expected release, opens the mailbox in
`.meetproxy/` (git-excluded) and prints the runner status. If MeetProxy is missing it **exits with
code 2 and installs nothing**: ask the user, and with their consent rerun with `MEET_INSTALL=yes` —
it creates an isolated venv (`~/.meetproxy/venv-<version>`, installs
`git+https://github.com/SergeyChere/MeetProxy@v0.7.0` there; system packages are not touched) and
prints the `export PATH=…` line to run in every later shell.

If it says **no runner is connected**, tell the user this, filling in `<owner/repo>`, then keep
working on the experiment while you wait:

> Open https://colab.research.google.com/github/SergeyChere/MeetProxy/blob/main/colab_runner.ipynb,
> choose *Runtime → Change runtime type → GPU*, type `<owner/repo>` in the REPO field, *Run all*.
> First time only: in Colab's key icon add a secret `GH_TOKEN` — a GitHub fine-grained token for
> this one repository with *Contents: Read and write*.

Check again with `meet status` until it shows `runner: idle | gpu: <name>`.

### Run a job

1. **Commit and push** the code. A job runs exactly the commit you are on when you send it —
   later pushes do not change it — and only once that commit is on GitHub; uncommitted changes
   never reach the GPU (`meet send` warns about both).
2. Write a job script from `templates/job.sh`. Headers: `# timeout: <seconds>` (always),
   `# gpu: any` (or `T4`, `L4`, `A100` when numbers matter — refused on another GPU).
   Self-contained bash from the project root; append one CSV line per measurement to
   `$MEET_OUT/results.csv` (pushed during the run). Job names are unique and sortable
   (`s01_build`, `s02_bench`); a name runs once. When the user is away, send one script that runs
   every planned variant.
3. Run it: short job `meet run s01_bench job.sh` (streams the log, exits with the job's code); long
   job `meet send s01_bench job.sh`, keep working, later `meet wait s01_bench` (without `--follow`:
   it would stream the whole log into your context), then `meet logs s01_bench --tail 50`.
4. Read `.meetproxy/out/<job>.done` (exit, seconds, GPU, full commit SHA) and
   `.meetproxy/out/<job>/results.csv`. `exit -3`: the commit could not be found or checked out (not
   pushed, typo in `# branch:` / `# commit:`) — fix it, resend under a new name. `exit -4`: a header
   is malformed (e.g. `# timeout: abc`). `timeout_capped: true`: the runner's `MAX_HOURS` ended the
   job first. `withheld: [...]`: those result files contained a secret and were not pushed — stop
   printing the environment or tokens into `$MEET_OUT`.
5. Read the **`gpu ...` line** at the end of the log (also `gpu_check` in `wait`): `gpu ok` — fine;
   `idle` / low `util` — the GPU waits for CPU, data or copies; `thermal throttle`, `hw slowdown`,
   `SM clock unstable` — do not compare timings; `mem peak` — near OOM; `other GPU procs` /
   `GPU busy at start` — shared GPU. Full numbers in `gpu_stats` in `.done`, every sample in
   `.meetproxy/out/<job>/gpu.csv`; `# telemetry: off` disables it.
6. **Compare runs** with `meet history` (one line per job: GPU, commit, seconds, exit, util, flags)
   instead of reopening old logs.

If `meet status` says the runner went silent, the runtime was probably disconnected: ask the user to
reconnect and run the notebook again. `meet stop` ends the runner. Never try to stop or delete the
Colab runtime, or merge the `meetproxy` branch.

### For the human, not for you

- Charts or a report on request: `# charts: on` in the job, or `meet report <job>` /
  `meet report history`; give the user the printed path. **Never open, read or summarize**
  `report.md`, `history.md` or `charts/*.svg` — they cost tokens and hold nothing `.done` and
  `history.csv` do not.
- `meet export [job…|--all]` copies results into `meet-runs/`; it commits nothing.

See `reference/troubleshooting.md` when something does not work.

### What this route does on the network

Installs a pinned release of a Python package from GitHub (only with consent), and runs
`git fetch/pull/push` against the user's own repository (branch `meetproxy`). Nothing else. The
runner does not hand the GitHub token to jobs, masks secrets in logs and does not push a result file
that contains one. Jobs run as the same user as the runner, so only trusted people should have write
access to the repository.
