# colab-pilot — architecture

An AI coding agent (Claude Code, Codex, Aider, …) writes experiments on a laptop or in a cloud
sandbox. A GPU notebook (Google Colab with compute units, Kaggle, a local Jupyter runtime) runs them.
The two never talk directly: **a git branch is the mailbox**. The human's only job is to open the
notebook, run one cell, and later shut the runtime down.

```
 ┌──────────────────────┐   git push cmd/*      ┌───────────────┐   git pull     ┌──────────────────────────┐
 │ AI agent (sandbox)   │ ───────────────────▶  │ GitHub branch │ ─────────────▶ │ runner.py in the notebook │
 │  pilot send / wait   │ ◀───────────────────  │   "pilot"     │ ◀───────────── │  runs job, streams log    │
 └──────────────────────┘   git pull out/*      └───────────────┘   git push out │  heartbeat, GPU info      │
                                                                                └──────────────────────────┘
```

The mailbox is the orphan branch `pilot` **of the user's own project repository** (created by
whichever side comes first: `pilot init` or the notebook). One repository, one token, nothing else
to set up.

Why git and not a socket: no inbound ports, no tunnels, no proxy (all of these are restricted on
Colab), every command and every result is versioned and reviewable, and the agent side needs nothing
but `git` and a token that can write one private repository.

## 1. Mailbox protocol (branch `pilot`)

| path | written by | meaning |
|---|---|---|
| `cmd/<job>.sh` | client | a job: a bash script, run once |
| `cmd/STOP` | client | holds the send time; stops runners started before it (a stale STOP never blocks a new runner) |
| `out/<job>.log` | runner | stdout+stderr, pushed every `PUSH_S` seconds while running |
| `out/<job>.done` | runner | JSON: exit code, seconds, start/end time, GPU |
| `out/<job>/…` | job | any result files the job writes to `$PILOT_OUT` |
| `out/runner.json` | runner | heartbeat: state, current job, GPU, last poll, version |

Rules that make it conflict-free:
- The client writes only `cmd/`, the runner writes only `out/`. Both always `pull --rebase`
  before push; rebase never conflicts because the trees are disjoint. The runner rebases with
  autostash, because the job log is still being written while new commands arrive.
- A job is identified by its file name; it runs at most once (`out/<job>.done` exists → skip).
- Jobs run in name order, one at a time (one GPU, no contention in measurements).
- Job header lines configure it: `# branch: <name>`, `# timeout: 3600` (seconds), `# gpu: A100|L4|T4|any`
  (refuse to run on the wrong GPU and report it in `.done`).
- Nobody merges `pilot` into `main`. It is a log, not code.

## 2. Runner (`pilot/runner.py`, notebook side)

Loop: `pull → pick next job → git pull the project → run → push`, plus a heartbeat.

- **Same code as the agent.** `pilot send` adds `# branch: <agent's current branch>` to the job
  (agents such as Claude Code usually work on their own branch, not `main`) and warns about
  unpushed or uncommitted changes. Before each job the runner fetches and checks out
  `origin/<branch>` (default: the remote default branch); the commit goes into the log and `.done`.
- **Few commits while idle.** The heartbeat is pushed every `HEARTBEAT_S` (300 s) when idle and
  with every log push while a job runs. `pilot status` treats a heartbeat older than 12 minutes as
  a disconnected runtime and tells the agent what to ask the human.
- **One-call start in Colab**: `colab_start("owner/repo")` reads the token from Colab secrets,
  clones or updates the project in `/content/<repo>`, opens the mailbox, runs the loop.

- **Process isolation.** Each job runs in its own process group (`setsid`). On timeout, STOP or a
  kernel interrupt the whole group is killed — a stray GPU process silently slowing the next
  measurement is the most expensive bug we hit in practice.
- **Streaming.** Output goes to `out/<job>.log`; a background thread pushes it every `PUSH_S`
  (default 45 s), so the agent can read progress of an hour-long job.
- **Redaction.** Values of every env var whose name contains `TOKEN`, `SECRET`, `KEY` or `PASSWORD`
  are replaced by `***` before anything is written to `out/`.
- **Idle limit.** No new job for `IDLE_MIN` minutes (default 120) → exit. The runner never deletes
  or disconnects the runtime: that is the human's decision.
- **Budget limit.** `MAX_HOURS` (default 12) of wall time → finish the current job and exit.
- **Environment report.** On start and in every heartbeat: `nvidia-smi` name, memory, driver, CUDA.
- **Runs in the notebook kernel** (`%run`), visible in the cell output, interruptible with the
  stop button. It is an experiment loop driven from the notebook, not a remote shell.

## 3. Client (`pilot/cli.py`, agent side)

```
pilot init                       # open .pilot/ (branch pilot) in the current repo, create if needed
pilot run <job> <script|->      # send + wait --follow
pilot send <job> <script|->     # commit cmd/<job>.sh and push
pilot wait <job> [--follow]     # poll until out/<job>.done; --follow prints new log lines
pilot logs <job> [--tail N]
pilot status                     # heartbeat: alive?, GPU, current job, queue
pilot stop                       # write cmd/STOP
pilot guide                      # print the agent guide
```

All commands work on a local clone of the `pilot` branch (`PILOT_DIR`, default `<repo>/.pilot`,
added to `.git/info/exclude`). Installed with `pip install git+https://github.com/SergeyChere/colab-pilot`.
Exit code of `wait` = exit code of the job, so an agent can chain steps in plain shell.

## 4. AI integration

The agent only needs shell and git access to the project (Claude Code already has both).
The user says one sentence pointing at this repository; the agent installs the package and reads
`pilot/guide.md` (`pilot guide`), which tells it:
1. write the experiment as a self-contained script; every step appends a line to
   `$PILOT_OUT/results.csv` and the runner pushes it — a long session yields data even if it dies;
2. `pilot send`, then `pilot wait --follow`; read logs, not guesses;
3. check `out/<job>.done` for the GPU name before comparing timings;
4. one long "session script" per human button press is better than many small jobs when the human
   is away.

## 5. Security

- Token: GitHub fine-grained, **one repository**, Contents read/write only, stored only in Colab
  secrets (`GH_TOKEN`). Never in the notebook text. The agent side uses its own git access.
- The runner executes whatever arrives in `cmd/` — only trusted people and agents may have write
  access to the repository. In a public repository the logs are public as well.
- Redaction of secrets in logs (above); jobs get `COLAB_PILOT=1` to know where they run.

## 6. Platform policy

Google Colab's FAQ restricts remote control (SSH shells, remote desktops) on runtimes used free of
charge, and disallows proxies and unrelated web services everywhere. colab-pilot opens no shell, no
port and no tunnel; it is a loop inside the notebook. Still: **use it with compute units (paid
runtimes), Colab Enterprise, a local runtime or Kaggle under their terms.** Do not market or use it
as a way around free-tier limits.

## 7. Roadmap

- Later, after Colab is solid: Kaggle, local Jupyter runtime, plain cloud VM.
- `pilot bench`: repeat a job N times, report median and spread.
- Artifacts larger than git likes: optional upload to a GCS/HF bucket, link in `.done`.
- Several runners on one mailbox (job claiming via `out/<job>.claim` commits).
