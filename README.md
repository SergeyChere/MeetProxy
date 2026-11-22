# colab-pilot

**Let an AI agent run your GPU experiments. You press one button.**

Your coding agent (Claude Code, Codex, Aider…) writes a benchmark, sends it to a GPU notebook,
watches the log stream in, reads the numbers, fixes the code and sends the next variant — for hours,
while you are away. The only thing you do is open the notebook and run one cell.

There is no SSH, no tunnel, no open port: the agent and the notebook exchange jobs and results
through **a git branch used as a mailbox**. Every command and every result is a commit you can review.

```
agent:   pilot send bench1 bench.sh  →  git push cmd/bench1.sh
notebook (runner.py):  git pull → run → stream out/bench1.log → out/bench1.done
agent:   pilot wait bench1 --follow  →  reads the log, decides the next step
```

Born in a real project: an AI agent tuned a CUDA kernel on Colab GPUs over several unattended
multi-hour sessions — profiling, A/B variants, comparing against a competitor's code — while the
human only restarted runtimes.

## Quick start

1. Create a **private** GitHub repo for the mailbox with a branch `pilot`
   (`cmd/` and `out/` folders). Create a fine-grained token: *only this repository*,
   *Contents: read and write*.
2. In Colab: add the token as secret `PILOT_TOKEN`, pick a GPU runtime, open
   [`examples/colab_runner.ipynb`](examples/colab_runner.ipynb), set your repo names, run all.
3. On the agent side:
   ```bash
   git clone https://github.com/SergeyChere/colab-pilot && cd colab-pilot
   git clone -b pilot https://x-access-token:$GITHUB_TOKEN@github.com/you/mailbox .pilot
   echo 'nvidia-smi; python bench.py' | python pilot/cli.py send first -
   python pilot/cli.py wait first --follow
   ```
   Give your agent [`AGENTS.md`](AGENTS.md) and let it drive.

Commands: `send`, `wait [--follow]`, `logs [--tail N]`, `status`, `stop`.
Job headers: `# timeout: 3600`, `# gpu: A100`.

## What the runner guarantees

- one job at a time, each at most once, in name order;
- log pushed every 45 s, results in `$PILOT_OUT` pushed with it;
- the whole process group killed on timeout or stop — no stray GPU processes skew the next run;
- secrets (`*TOKEN*`, `*KEY*`, …) redacted from logs;
- exits after `IDLE_MIN` (120) idle minutes or `MAX_HOURS` (12); **never shuts down your runtime**.

## Rules of the road

Colab restricts remote control (SSH shells, remote desktops) on free-of-charge runtimes and disallows
proxies and unrelated web services everywhere. colab-pilot is a loop inside your notebook, not a
remote shell — but use it on **paid runtimes (compute units), Colab Enterprise, Kaggle or your own
machine**, and follow each platform's terms. It is not a tool for getting around free-tier limits.

The runner executes whatever lands in `cmd/`. Keep the mailbox private, the token scoped to it.

Design: [ARCHITECTURE.md](ARCHITECTURE.md). Test: `bash tests/roundtrip.sh` (local bare repo, no GPU).

License: MIT.
