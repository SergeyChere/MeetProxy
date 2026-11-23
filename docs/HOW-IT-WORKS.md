# How colab-pilot works

Your agent has no GPU, your notebook has one. They never talk directly: a branch of **your own
repository**, `pilot`, carries jobs one way and results the other.

```mermaid
flowchart LR
    subgraph AGENT["🤖 AI agent · Claude Code, Codex… (no GPU)"]
        direction TB
        A1["git push — your code"]
        A2["pilot send job.sh"]
        A3["pilot wait --follow"]
        A1 --> A2 --> A3
    end

    subgraph REPO["📦 GitHub · your repo · branch pilot"]
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
    HIST --> HA["pilot history<br/>compact table for the agent"]
    HIST -. "charts: on" .-> HM["history.md<br/>trends across commits"]

    classDef agent fill:#eef3fd,stroke:#3b6fd8,color:#1f2a44
    classDef human fill:#fff6e3,stroke:#e0a020,color:#4a3510
    classDef data fill:#f6f4ef,stroke:#b8b2a6,color:#2b2925
    class FLAG,HA agent
    class REP,HM human
    class S,RAW,SUM,DONE,HIST data
```

| Level | Where | Who reads it |
|---|---|---|
| Flags | last line of the log, `gpu_check` in `pilot wait` | the agent, always |
| Summary | `gpu_stats` in `out/<job>.done` | the agent, when a flag needs a closer look |
| Raw | `out/<job>/gpu.csv` | anyone digging |
| History | `out/history.csv`, `pilot history` | the agent, to compare runs |
| Reports | `out/<job>/report.md`, `out/history.md` | **the human only** — made on the GPU side, the agent never opens them, they cost no tokens |

## Where to look on GitHub

Everything lives in branch `pilot` of your repository: switch the branch selector to `pilot` and
open `out/`. `report.md` and `history.md` render with their charts right there, on a phone too.

To keep results next to your code: `pilot export <job>` copies them to `pilot-runs/<job>/` in your
working tree. Nothing is committed for you.

![colab-pilot overview](how-it-works.svg)

More detail: [ARCHITECTURE.md](../ARCHITECTURE.md).
