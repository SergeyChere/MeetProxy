# How MeetProxy works

Your agent has no GPU, your notebook has one. They never talk directly: a branch of **your own
repository**, `meetproxy`, carries jobs one way and results the other.

```mermaid
flowchart LR
    subgraph AGENT["🤖 AI agent · Claude Code, Codex… (no GPU)"]
        direction TB
        A1["git push — your code"]
        A2["meet send job.sh"]
        A3["meet wait --follow"]
        A1 --> A2 --> A3
    end

    subgraph REPO["📦 GitHub · your repo · branch meetproxy"]
        direction TB
        C["cmd/<br/>s01_build.sh<br/>s02_bench.sh<br/>STOP"]
        O["out/<br/>s02_bench.log · .done<br/>s02_bench/results.csv<br/>s02_bench/gpu.csv<br/>history.csv"]
    end

    subgraph GPU["⚡ Colab GPU · runner, a loop in the notebook"]
        direction TB
        R1["1 · pull the next job"]
        R2["2 · check out your pushed branch"]
        R3["3 · run it in its own process group"]
        R4["4 · sample the GPU every second"]
        R5["5 · push log, results, telemetry, history"]
        R1 --> R2 --> R3 --> R4 --> R5
    end

    A2 -- push --> C
    C -. pull .-> R1
    R5 -- push --> O
    O -. pull .-> A3

    classDef agent fill:#eef3fd,stroke:#3b6fd8,color:#1f2a44
    classDef repo fill:#f4f0ff,stroke:#7a5af0,color:#2a2244
    classDef gpu fill:#eefaf4,stroke:#1f9d6b,color:#163b2c
    class A1,A2,A3 agent
    class C,O repo
    class R1,R2,R3,R4,R5 gpu
    style AGENT fill:#f7f9fe,stroke:#3b6fd8,color:#23407e
    style REPO fill:#faf8ff,stroke:#7a5af0,color:#3d2e7a
    style GPU fill:#f6fcf9,stroke:#1f9d6b,color:#16704d
    linkStyle 0,1 stroke:#3b6fd8
    linkStyle 2,3,4,5 stroke:#1f9d6b
    linkStyle 6,7 stroke:#3b6fd8,stroke-width:2.5px
    linkStyle 8,9 stroke:#1f9d6b,stroke-width:2.5px
```

**You:** open the notebook, *Run all* once, shut the runtime down when finished. Everything else is
the agent's.

## What comes back, and who reads it

The rule: **collect everything, give the agent only what it needs, give the human something
pleasant to look at.**

```mermaid
flowchart TB
    S["GPU sampled every second<br/>(nvidia-smi)"] --> RAW
    RAW["out/{job}/gpu.csv<br/>every sample that changed"] --> SUM
    SUM["gpu_stats in .done<br/>averages, peaks, % throttled"] --> FLAG
    FLAG["one line for the agent<br/>gpu WARN: idle 66% · thermal 12%"]
    RAW -. "charts: on" .-> REP
    REP["report.md + SVG charts<br/>for the human only"]
    DONE["each finished job"] --> HIST["out/history.csv<br/>one line per job, forever"]
    HIST --> HA["meet history<br/>compact table for the agent"]
    HIST -. "charts: on" .-> HM["history.md<br/>trends across commits"]

    classDef agent fill:#eef3fd,stroke:#3b6fd8,color:#1f2a44
    classDef human fill:#fff6e3,stroke:#e0a020,color:#4a3510
    classDef data fill:#f6f4ef,stroke:#b8b2a6,color:#2b2925
    class FLAG,HA agent
    class REP,HM human
    class S,RAW,SUM,DONE,HIST data
    linkStyle 0,1,4 stroke:#9a948a
    linkStyle 2,5 stroke:#3b6fd8,stroke-width:2px
    linkStyle 3,6 stroke:#e0a020,stroke-width:2px
```

| Level | Where | Who reads it |
|---|---|---|
| Flags | last line of the log, `gpu_check` in `meet wait` | the agent, always |
| Summary | `gpu_stats` in `out/<job>.done` | the agent, when a flag needs a closer look |
| Raw | `out/<job>/gpu.csv` | anyone digging |
| History | `out/history.csv`, `meet history` | the agent, to compare runs |
| Reports | `out/<job>/report.md`, `out/history.md` | **the human only** — made on the GPU side, the agent never opens them, they cost no tokens |

## What the `meet` command is, and the heartbeat

`meet` is the small command-line tool from this package (`pip install
git+https://github.com/SergeyChere/MeetProxy`). The agent could drive the mailbox with plain
`git`, but every job would then cost it a dozen commands and their output. `meet` does the git
work and answers in one short line:

| Command | What it does inside |
|---|---|
| `meet init` | clones branch `meetproxy` of your repo into `.meetproxy/` (git-excluded), creates the branch if missing |
| `meet send job sh` | adds `# branch: <your branch>`, warns if the code is not pushed, writes `cmd/job.sh`, commits, pushes; if the runner pushed meanwhile — pulls and retries with backoff |
| `meet wait job` | pulls every 20 s until `out/job.done` appears; exit code = the job's; prints `.done` without the bulky stats, plus one `gpu_check` line |
| `meet status` | reads the heartbeat: alive or not, GPU, current job, queue |
| `meet history` | one line per finished job |

Neither side ever waits on the other: both just pull and push on timers.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"actorBkg": "#ffffff", "actorBorder": "#7a5af0", "actorTextColor": "#1f1d1a", "signalColor": "#4a463f", "signalTextColor": "#1f1d1a", "noteBkgColor": "#fff6e3", "noteBorderColor": "#e0a020", "noteTextColor": "#4a3510", "sequenceNumberColor": "#ffffff", "loopTextColor": "#4a463f", "labelBoxBkgColor": "#ffffff", "labelBoxBorderColor": "#b8b2a6"}}}%%
sequenceDiagram
    autonumber
    box rgb(238,243,253) 🤖 Agent side
        participant A as Agent (meet)
    end
    box rgb(244,240,255) 📦 Your repo
        participant G as GitHub · branch meetproxy
    end
    box rgb(238,250,244) ⚡ Colab GPU
        participant R as Runner
    end

    rect rgb(238,250,244)
        loop idle: every 20 s (POLL_S)
            R->>G: pull — any new cmd/*.sh?
        end
        Note over G,R: heartbeat out/runner.json pushed every 5 min while idle
    end

    rect rgb(238,243,253)
        A->>G: meet send — push cmd/s01.sh
    end

    rect rgb(238,250,244)
        R->>G: pull — finds s01
        R->>R: check out your branch, run the job, sample the GPU
        loop while running: every 45 s (PUSH_S)
            R->>G: push log + results + heartbeat, pull (sees STOP)
        end
    end

    rect rgb(238,243,253)
        loop meet wait: every 20 s (--poll)
            A->>G: pull — s01.done yet?
        end
    end

    rect rgb(238,250,244)
        R->>G: push s01.done, history.csv, final heartbeat
    end

    rect rgb(255,246,227)
        A->>G: pull — reads .done, prints one gpu line
    end
```

**Heartbeat** is the file `out/runner.json` on branch `meetproxy`, written only by the runner:
`state` (starting / idle / running / stopped / idle-exit / budget / interrupted), current `job`,
`gpu`, `time`, `version`. It is pushed every 5 min while idle (few commits), with every log push
while a job runs, and once more on exit with the reason. The agent never reads it directly:

- `meet status` turns it into one line — `runner: idle | gpu: Tesla T4 | last seen 2 min ago` —
  or a plain instruction for the human: no runner yet → *run the notebook*; heartbeat older than
  12 min → *the runtime was probably disconnected, reconnect*; exited → *run the cell again*;
- `meet wait` checks it once if a job has produced no log for 2 minutes, so the agent learns the
  runtime is gone instead of waiting forever.

## Where the agent saves tokens

Everything the agent reads costs tokens; the design keeps that to the minimum it needs to decide.
Rough sizes (≈ 4 characters per token):

| Instead of… | the agent gets… | ≈ tokens |
|---|---|---|
| a dozen git commands and their output per job (add, commit, push, conflict, pull, retry, poll) | `meet send` / `meet wait`: one line each | ~2 000 → ~50 |
| `gpu.csv` of a one-hour job (up to 3 600 rows) | one flags line: `gpu ok: util 97%, mem 41%, 68°C` | ~40 000 → ~20 |
| the full `gpu_stats` in every `wait` | `.done` without it, plus that line; stats only when a flag needs a look | ~150 → ~20 |
| reopening old logs to compare runs | `meet history`: one line per run | ~5 000 → ~150 |
| charts and `report.md` | nothing: drawn on the GPU side for the human, the guide forbids opening them | ~30 000 → 0 |
| polling `meet status` while the human is away | `meet wait` checks the heartbeat itself after 2 min of silence | many calls → 1 line |
| many small jobs, each with its own round trip | one session script per button press, results appended to `results.csv` as they come | n round trips → 1 |

Tip for long jobs: `meet wait <job>` **without** `--follow`, then `meet logs <job> --tail 50` —
`--follow` streams the whole log into the conversation.

## Colab API: what will remove the last manual step

Today the human opens the notebook and presses *Run all*. Google now has a Colab API for managing
runtimes programmatically — **beta, by allowlist** (access is requested from the Colab team). Its
MCP server lists these tools: `list_runtime_specs`, `create_runtime` (accelerator `T4`, `L4`,
`A100`…), `get_runtime`, `list_runtimes`, `delete_runtime`, `create_session`, `list_sessions`,
`delete_session`, `execute_code`, `get_subscription`.

With access, MeetProxy could:

1. `create_runtime` with the GPU a job asks for (`# gpu: L4`);
2. `execute_code` the one-cell runner — no notebook, no button;
3. run the jobs over the same git mailbox (history and review stay in your repo);
4. `delete_runtime` after the queue is empty, so compute units are not burnt while idle;
5. `get_subscription` to warn before the compute units run out.

Until then: inside a running notebook `from google.colab import runtime; runtime.unassign()`
releases the runtime — planned as an opt-in "release after N idle minutes". **Colab Enterprise**
(Google Cloud, pay as you go) already has `gcloud colab runtimes create / start / stop / delete`.

## Where to look on GitHub

Everything lives in branch `meetproxy` of your repository: switch the branch selector to `meetproxy` and
open `out/`. `report.md` and `history.md` render with their charts right there, on a phone too.

To keep results next to your code: `meet export <job>` copies them to `meet-runs/<job>/` in your
working tree. Nothing is committed for you.

![MeetProxy overview](how-it-works.svg)

More detail: [ARCHITECTURE.md](../ARCHITECTURE.md).
