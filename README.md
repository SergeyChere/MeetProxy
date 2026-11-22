# colab-pilot

**Your AI agent runs the GPU experiments. You press one button.**

Claude Code (or another coding agent) writes a benchmark, runs it on your Colab GPU, watches the log
stream in, reads the numbers, fixes the code and runs the next variant — for hours, while you are
away. No SSH, no tunnels, no open ports: the agent and the notebook talk through a branch `pilot`
of your own GitHub repository. Every job and every result is a commit you can read later.

## Start in two steps

**1. Colab** — [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/SergeyChere/colab-pilot/blob/main/examples/colab_runner.ipynb)
pick a GPU runtime, type your repo (`owner/repo`), **Run all**.
First time only: add a Colab secret `GH_TOKEN` — a GitHub
[fine-grained token](https://github.com/settings/personal-access-tokens/new) for that one repo,
*Repository permissions → Contents: Read and write*.

**2. Claude** — open Claude Code in the same repo and say:

> Use https://github.com/SergeyChere/colab-pilot to run our benchmarks on my Colab GPU.

The agent installs the tool, reads its guide, and takes it from there. You can do step 2 first:
the agent prepares everything and tells you when to press Run all.

That's all. Close the laptop; come back to results, logs and a summary.

## What happens

```
agent:  git push (code)          pilot run bench1 bench.sh → commit cmd/bench1.sh on branch pilot
Colab:  pull → git pull project → run bench1 → push out/bench1.log every 45 s → out/bench1.done
agent:  reads the log, decides the next step
```

- One job at a time, each at most once; the notebook always runs your newest pushed code.
- Results a job writes to `$PILOT_OUT` are pushed with the log, so partial sessions still count.
- Timeout or stop kills the job's whole process group — no stray GPU processes skew the next run.
- Tokens and secrets are masked in logs.
- The runner exits after 2 idle hours or 12 hours total; **it never shuts down your runtime**.

Agent commands: `pilot init | run | send | wait --follow | logs | status | stop | guide`.
Job headers: `# timeout: 3600`, `# gpu: A100`.

## Rules of the road

Colab restricts remote control (SSH shells, remote desktops) on free-of-charge runtimes and
disallows proxies and unrelated web services everywhere. colab-pilot is a loop inside your
notebook, not a remote shell — still, use it with **Colab compute units (paid) or Colab Enterprise**
and follow Colab's terms. It is not a way around free-tier limits.

The notebook runs whatever is pushed to the `pilot` branch: only people and agents you trust
should have write access to the repository. In a public repository the logs are public too.

Design: [ARCHITECTURE.md](ARCHITECTURE.md). Test without a GPU: `bash tests/roundtrip.sh`.
License: MIT.
