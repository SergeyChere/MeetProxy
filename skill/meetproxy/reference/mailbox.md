# Mailbox route

Read this only after the user chose and approved this route (SKILL.md section 1). It pushes
code and jobs to the user's GitHub repository.

Today's Colab route without the official tool: you push jobs (bash scripts) to `cmd/` on the branch
`meetproxy` of the user's repository; a loop in a Colab notebook runs them and pushes logs and
results to `out/`. No ports, tunnels or shells are opened. Needs a GitHub `origin` you can push to.

### Set up (once per session, only for this route)

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
2. Write a job script from `../templates/job.sh`. Headers: `# timeout: <seconds>` (always),
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
reconnect and run the notebook again. Never merge the `meetproxy` branch.

**The runtime is borrowed.** The user opened it, so only the user shuts it down. `meet stop` stops
the runner, not the runtime: report *runner stopped — cleanup still required by the user: shut the
Colab runtime down (Runtime → Disconnect and delete runtime)*. Never try to stop or delete the
runtime yourself.

### For the human, not for you

- Charts or a report on request: `# charts: on` in the job, or `meet report <job>` /
  `meet report history`; give the user the printed path. **Never open, read or summarize**
  `report.md`, `history.md` or `charts/*.svg` — they cost tokens and hold nothing `.done` and
  `history.csv` do not.
- `meet export [job…|--all]` copies results into `meet-runs/`; it commits nothing.

See `troubleshooting.md` (next to this file) when something does not work.

### What this route does on the network

Installs a pinned release of a Python package from GitHub (only with consent), and runs
`git fetch/pull/push` against the user's own repository (branch `meetproxy`). Nothing else. The
runner does not hand the GitHub token to jobs, masks secrets in logs and does not push a result file
that contains one. Jobs run as the same user as the runner, so only trusted people should have write
access to the repository.
