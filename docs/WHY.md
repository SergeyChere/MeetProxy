# Why colab-pilot exists

## The problem

I was optimizing a CUDA kernel with an AI coding agent. The agent was good at the work: reading
profiles, proposing variants, rewriting the kernel. But it could not touch a GPU. My GPU was a
Colab runtime, and Colab is a notebook in a browser tab.

So I became the cable between them:

- the agent wrote a variant → I copied it into Colab → ran it → waited → copied the log back;
- a run took 20 minutes to 2 hours, so I sat and watched a progress bar, or came back late and
  found it had crashed in minute 3;
- the agent could only see what I pasted, often a cut piece of the log, and drew conclusions from it;
- every idea needed my hands, so ten ideas meant an evening; ideas I had no time to try were never
  tried.

Some mistakes cost whole sessions, and none of them were the agent's or mine alone — they came from
the gap between us:

- a process from an interrupted run kept using the GPU and made every later measurement 2× slower;
- the runtime was a different GPU than last time, and nobody noticed before comparing the numbers;
- a result that looked like a breakthrough was a cached output from the previous run;
- Colab reported "you are not using the GPU" while I was away, and the runtime was gone.

The usual fix — SSH into the runtime or open a tunnel — is exactly what Colab restricts on free
runtimes, and it gives the agent a shell, not a way to run careful experiments.

## How we solved it

The agent and the notebook do not need a connection. They need a **shared, versioned place to
leave messages**, and every developer already has one: a git repository.

- The agent writes a job (a bash script) to the branch `pilot` and pushes.
- A small loop running in the notebook pulls, checks out the agent's newest pushed code, runs the
  job, and pushes the log back every 45 seconds, then the exit code, time, GPU and commit.
- The agent reads the log as it arrives and decides the next step itself.

Then each failure above became a rule in the runner, so it cannot happen again:

| what went wrong | what the runner does now |
|---|---|
| stray process slowed later runs | every job runs in its own process group; the whole group is killed at the end, on timeout or stop |
| numbers from different GPUs compared | the GPU is recorded with every result; a job can require one (`# gpu: A100`) |
| the notebook ran old code | before each job it checks out the newest pushed commit of the agent's branch and records it |
| a run died and nobody knew | heartbeat; the agent sees a silent runner and tells the human what to do |
| a crash lost a whole session | results are pushed during the run, not at the end |
| tokens in logs | secrets are masked before anything is written |
| the agent shut down the runtime to "clean up" | the runner never touches the runtime; the human decides |

The result: I press Run all once and go for a walk. The agent runs the planned variants, measures
them, reads the profiles and has a summary ready when I come back. Ideas are now limited by GPU
hours, not by my evenings.

How it is built: [ARCHITECTURE.md](../ARCHITECTURE.md).
