# MeetProxy product

**Why it should exist, for whom, and what it must do.** This document comes first:
[DESIGN.md](DESIGN.md) explains *how* each requirement below is met, [ROADMAP.md](../ROADMAP.md)
*when*. Requirements are numbered `PR-NN`; the design and the roadmap refer to these numbers.

```mermaid
flowchart LR
    P["📗 PRODUCT<br/>why · for whom<br/>requirements PR-NN"]
    D["📘 DESIGN<br/>how<br/>sections §N cite PR-NN"]
    R["🗺️ ROADMAP<br/>when<br/>milestones cite §N and PR-NN"]
    P --> D --> R
    classDef p fill:#eefaf4,stroke:#1f9d6b,stroke-width:2px,color:#163b2c
    classDef d fill:#eef3fd,stroke:#3b6fd8,stroke-width:2px,color:#1f2a44
    classDef r fill:#fff6e3,stroke:#e0a020,stroke-width:2px,color:#4a3510
    class P p
    class D d
    class R r
```

A change starts here and flows down: a new or changed requirement first, then the design that meets
it, then the milestone that builds it. A test keeps the links intact (every `PR-NN` is designed and
planned, every `§N` exists).

Status: 27 Nov 2026 (rev. 4, after the third product review — refinements only, no new requirements).
Everything here is a **hypothesis to validate**, not shipped behaviour or customer research. Savings
are claimed only after they are measured (PR-20).

**The specification is frozen.** Further changes come from design partners, experiments or concrete
implementation constraints — not from more analysis.

## 1. The promise

> **Better verified GPU experiments. Less babysitting. Same budget.** — on the GPUs you already have.

A target, not a proven claim (PR-20). "Better" is the research outcome — the best verified result of
a campaign — not the number of runs; less babysitting is the second, measured benefit. One reason to
install, one thing to prove. Everything else — one skill, several GPUs, telemetry,
reports — is a means to this, not the pitch. Running a job on a GPU is not unique (provider skills
and multi-cloud tools do it, section 4); an **experiment campaign that comes back with a verified
best result and the evidence for it** is what MeetProxy must be better at than anything else.

## 2. The problem

An AI agent writes GPU code but has no GPU. The user has one — a Colab subscription, a lab server,
the card in their own machine. In repeated experiments (ten kernel variants, a parameter sweep) the
human becomes the middleware: starting runs, watching them, pasting results back, cleaning up paid
sessions. That is most of the work, and it is where results go wrong: the wrong commit ran, timings
came from different GPUs, a faster variant was silently incorrect, a failed idea was tried again a
week later, a session kept billing overnight.

## 3. Who it is for

**Initial segment — repeated CUDA experimenters.**

| | |
|---|---|
| Who | independent researchers and developers optimizing CUDA / PyTorch code |
| Frequency | several experiment sessions a week, many variants each |
| GPU access they already have | **first beta:** a local NVIDIA card and/or a Colab subscription · later (after GO): a lab or own server over SSH |
| Current workflow | an agent (Claude Code, Codex) writes code; the human runs it on the GPU and reports back |
| Switching trigger | a campaign of variants that is too tedious, error-prone or slow to babysit by hand |

**Later, only if the first segment works:** ML engineers spreading independent jobs over their own
machines; occasional users who want "run this on my GPU" (served by Quick Run, PR-04, but not the
reason the product exists).

## 4. Alternatives

Verified on 27 Nov 2026 from public documentation; to be re-checked hands-on before any public
comparison.

| Alternative | What it offers | What MeetProxy must still do better |
|---|---|---|
| **Official Colab CLI + skill** | Colab runtimes, exec, files, SSH, an agent skill | campaigns with correctness, exact source, recovery, memory |
| **Agent running CUDA directly on a local GPU** | Claude Code or Codex compiles and runs on the user's own card with normal scripting and the project's tests; no extra dependency | the strongest local baseline: MeetProxy must beat it on verified outcome or effort, not only on remote cases |
| **Agent + direct SSH** | any Linux host | durable status across disconnects, exact source, verified results |
| **SkyPilot agent skill** | an official agent skill (Claude Code plugin) over 25+ clouds, Kubernetes and Slurm, also existing machines; has shown autoresearch running in parallel on 16 GPUs | strong overlap — not competed with on breadth. Possible edge, to be proven: Colab subscriptions, lower setup friction, the evidence contract (exact source, oracle, matched comparison, memory). **Compared directly in the pilot wherever it supports the same resource and task; not integrated.** |
| **RunPod agent plugin** | official skills + MCP for Claude Code, Codex and ChatGPT | provider-specific; MeetProxy is about campaigns across the user's existing GPUs |
| **Modal auto-research skills** | research-agent skills on Modal GPUs | provider-specific; same as above |
| **Karpathy autoresearch** | the "try, compare, keep or discard" loop on one GPU with one metric | the same loop with correctness checks, exact source, several GPUs and a durable record |
| **Ad hoc script by the agent** | anything, once | a tested contract: exact source, budgets, recovery, artifacts, comparisons |
| **Slurm / Kubernetes / MLflow** | scheduling and tracking at scale | not replaced: SSH and open export into them |

If MeetProxy is not measurably better than the official Colab skill, direct SSH and direct local
execution for the initial segment's campaigns, it does not grow (PR-20).

## 5. Target workflow: an experiment campaign

> *"Find the fastest correct implementation of my CUDA kernel. Use my local GPU and my Colab.
> Budget: $10 and two hours."*

1. The agent states the campaign: objective metric, baseline, correctness oracle, the approved
   GPUs and limits, stop conditions (PR-22).
2. It checks the experiment memory: what was tried before and why it was rejected (PR-23).
3. The user approves the campaign once (PR-07).
4. Independent variants run on the approved GPUs — **sequentially on one GPU** (a valid campaign)
   or concurrently on several when the estimated gain outweighs the extra setup, transfer and
   compilation (PR-11).
5. Incorrect outputs are rejected whatever their speed; timings are compared only within compatible
   environments (PR-05). **Different GPUs screen, one GPU decides:** the reference (target) GPU is
   declared **before** screening and part of the budget and time is reserved for the final
   validation on it. Variants may be screened on several GPU types under a shortlist rule declared in
   advance that keeps architecture-sensitive candidates; finalists and the baseline are re-run on the
   reference GPU, and only that matched benchmark names the winner. Without it the result is a
   winner per GPU type, or "insufficient evidence" — never a global ranking from mixed hardware.
6. The agent proposes the next variants from the results, inside the approved limits; the core
   records each hypothesis, its lineage and outcome (PR-22, PR-23).
7. On a stop condition: results verified, owned sessions released (PR-07, PR-10).
8. The user gets the best verified variant, the evidence, what was rejected and why, and the total
   cost — compute and agent tokens, actual where known (PR-25). A campaign that finds no improvement
   says so.

**The smallest campaign that tests the promise** (the first beta's scope): one CUDA project with an
existing correctness check, a baseline and 3–5 variants, one or two GPU profiles (local, Colab, or
both), one approval, one round of screening and one matched final benchmark, verified results and
released sessions — then **one follow-up session with a fresh agent context** that must find what
was tried (and allow a justified retest when the GPU or input changed).

The everyday case stays simple: *"run this on my GPU"* → it runs, the exact commit, one line of
result (PR-04).

## 6. Requirements

Priority is for the **first beta** — the smallest campaign above, on local GPU + Colab: **Must**
(without it that campaign fails or is unsafe), **Should** (weakens it if missing), **Could** (later, on
evidence). The list is closed for now: new needs come from design partners, not from more analysis.

| ID | Requirement | Priority | How we will know |
|---|---|---|---|
| **PR-01** | **One entry point.** A natural-language skill (`/meetproxy`, `$meetproxy`); a CLI for agents and power users. No commands to memorize for the human. | Should | a first-time user gets a result without reading CLI docs |
| **PR-02** | **Official tools underneath.** Use provider CLIs and sign-ins; never re-implement vendor auth or transport; install adapters only with consent. | Must | no own auth for Colab/SSH; adapter install asks first |
| **PR-03** | **The user chooses the GPU.** Named profiles; no implicit provider or destination switch; the backend is shown on every result. | Must | contract tests: no run on an unapproved profile |
| **PR-04** | **Quick Run.** "Run this on a GPU" with minimal metadata, keeping safety and exact source. | Should | quick run needs only the script and a profile |
| **PR-05** | **Benchmark Mode.** Correctness oracle — reusing the project's existing tests, reference implementations, fixtures or known exact results where possible —, repeats, compatible environments only; heterogeneous GPUs screen, a matched benchmark on one reference GPU — declared before screening, with budget and time reserved for it — decides; incorrect outputs never "win"; no adequate oracle → no verified-winner claim. | Must | an incorrect fast variant is rejected |
| **PR-06** | **Exact source.** Every job runs the commit it was submitted with, or does not run. | Must | branch moved after submit → submitted commit runs |
| **PR-07** | **Paid compute is safe by default.** Default deny, scoped approvals, time limits, bounded session hold, estimates; best-effort vs hard limits disclosed; no monetary cap promised without provider enforcement. | Must | no paid acquire without approval; no unbounded hold |
| **PR-08** | **No new credential burden.** Reuse official sign-ins; other tokens in the OS keychain; never in chat, config or repo; minimal job environment; same-user limits documented. | Must | tokens never appear in chat or files |
| **PR-09** | **Code stays where it is by default.** Local and private profiles; consent per repository and destination; history-free snapshots. | Must | no transfer to a new destination without consent |
| **PR-10** | **Failures are visible and recoverable.** Reconnect, explicit `UNKNOWN`, no silent duplicate runs, partial results kept, a direct-provider escape hatch. | Must | disconnect, crash and interrupted transfer tests |
| **PR-11** | **Parallel independent jobs** across approved GPUs under one approved plan, recommended only when the estimated gain outweighs setup overhead; a single-GPU sequential campaign is equally supported; no distributed training or automatic parallelization of arbitrary code. | Must | two jobs on two profiles under one approval; one workload where parallel wins and one where sequential does, by total time and cost |
| **PR-12** | **Few tokens.** Compact structured verdicts and bounded log excerpts; raw evidence on request. | Should | measured token use vs direct workflows |
| **PR-13** | **Results people can read.** Optional reports and charts made outside the agent's context. | Could | reports cost the agent no tokens |
| **PR-14** | **Telemetry levels.** Simple · Standard · Deep (opt-in). | Should | quick runs default to Simple or Standard |
| **PR-15** | **Works with existing projects unchanged.** | Should | a representative existing repo runs as is |
| **PR-16** | **No lock-in.** MIT, open protocol, portable CSV/JSON, configurable retention, no mandatory hosted service. | Should | everything exports; no MeetProxy server needed |
| **PR-17** | **Minutes to first run.** Read-only discovery; ask only for what is missing. **First run** and **first verified experiment** are measured separately; oracle preparation time is reported, not hidden. | Must | both times measured (targets in section 9) |
| **PR-18** | **Honest support.** Supported means tested; support matrix with smoke tests; unsupported is explicit. | Must | every listed host/backend has a passing smoke test |
| **PR-19** | **Integrate, don't replace.** SSH and open export first; Slurm/Kubernetes/MLflow integrations only on demand; interactive work handed to provider sessions. | Could | export works into existing tools |
| **PR-20** | **Evidence before claims.** Benefits claimed only after a pre-registered comparison with the official Colab skill, direct SSH, direct local agent execution and SkyPilot wherever they support the same resource and task (and an autoresearch-style loop where relevant); supported and unsupported cases reported separately; all runs published. | Must | pilot published; decision GO / ITERATE / STOP |
| **PR-21** | **Compute cost per correct result.** Start-up, idle, failures and billing units included; unknowns disclosed; actual spend where available. | Should | estimate vs actual reported per plan |
| **PR-22** | **Experiment campaigns.** Objective, baseline, oracle, approved resource envelope, variants, stop conditions, final evidence — a first-class object. The agent reasons; the core records and enforces. | Must | a campaign ends with a best verified result and its evidence |
| **PR-23** | **Experiment memory.** Per project: structured hypothesis identities, variant lineage, workload and hardware context, results, rejection reasons, evidence; likely duplicates surfaced as **suggestions, not bans** (justified retests and new combinations allowed); measured facts kept apart from agent interpretations. | Must | a new session finds a rephrased prior hypothesis and its evidence; a changed GPU or input allows an explicit retest |
| **PR-24** | **Resource recommendations.** Suggest which approved profile fits a run (capability, availability, estimated cost per correct result); new profiles only with approval. | Could | the suggested profile is approved before use |
| **PR-25** | **Total cost includes the agent.** Agent tokens and model cost (where the host reports them) next to GPU billing, storage and failed attempts; unknown parts marked. | Should | campaign report shows compute and agent cost |
| **PR-26** | **Adoption and retention are measured — with consent.** Time to first run, activation, repeat use at 7 and 30 days, reasons for leaving; opt-in, no data leaves the machine without it. | Should | design-partner and beta metrics reported with sample sizes |
| **PR-27** | **Low overhead.** Cold-start (staging, transfer) and steady-state overhead measured separately against direct execution; Quick Run stays fast. | Should | overhead within the target in section 9 |
| **PR-28** | **Portable experiment definitions.** A campaign or run states its requirements (GPU capability, dependencies, data); moving it to another backend validates them first. | Could | a run moved between profiles is validated or refused before transfer |
| **PR-29** | **Extensible backends.** A documented backend contract with capability declarations and contract tests, so others can add one. | Could | an external backend passes the contract tests |

## 7. Objections

Plausible reasons not to install MeetProxy. Mapping to requirements is traceability, **not
evidence**: each objection is *unvalidated* until its behavioural check passes with real users.

| # | Objection | Answered by | Behavioural check | Status |
|---|---|---|---|---|
| 01 | Google already has a Colab skill. | PR-22, PR-23, PR-20 | a better verified result at the same budget than the official skill; partners prefer it | unvalidated |
| 02 | My agent already uses SSH. | PR-06, PR-10, PR-22 | fewer interventions than direct SSH on the same campaign | unvalidated |
| 03 | Setup is too complicated. | PR-17 | first useful run within target | unvalidated |
| 04 | I rarely need a GPU. | PR-04 | — (not the initial segment) | out of segment |
| 05 | I do not trust AI with paid compute. | PR-07 | partners approve a paid campaign | unvalidated |
| 06 | I will not give another tool credentials. | PR-08 | partners complete setup without new credentials for Colab/SSH | unvalidated |
| 07 | My code is proprietary. | PR-09 | partners run on local/private profiles only | unvalidated |
| 08 | I already use Slurm, Kubernetes or MLflow. | PR-19 | — | out of segment |
| 09 | I do not want to change my workflow. | PR-15 | a partner's existing repo runs unchanged | unvalidated |
| 10 | I do not want to learn commands. | PR-01 | partners never type a `meet` command | unvalidated |
| 11 | Another layer means more failures. | PR-10, PR-27 | forced-disconnect test passes; overhead within target | unvalidated |
| 12 | A small project might disappear. | PR-16 | — | design constraint |
| 13 | Token savings are unproven. | PR-12, PR-20 | measured in the pilot | unvalidated |
| 14 | Time savings are unproven. | PR-11, PR-20 | measured in the pilot | unvalidated |
| 15 | Money savings are unproven. | PR-21, PR-25 | measured in the pilot | unvalidated |
| 16 | I do not need detailed metrics. | PR-14 | — | design constraint |
| 17 | I just need to run code. | PR-04 | — | out of segment |
| 18 | My agent runs in the cloud. | PR-18 | — | later |
| 19 | My hardware or provider is unsupported. | PR-18, PR-29 | — | later |
| 20 | Official tooling changes too quickly. | PR-02, PR-18 | compatibility tests per pinned CLI version | design constraint |
| 21 | I do not want another history database. | PR-16, PR-23 | partners keep the memory after a week | unvalidated |
| 22 | I need interactive GPU access. | PR-19 | — | out of segment |
| 23 | Claude can just write a script for me. | PR-06, PR-10, PR-05, PR-22 | fewer debugging interventions than an ad hoc script | unvalidated |
| 24 | There is no convincing advantage. | PR-20 | pilot ends in GO | unvalidated |
| 25 | Setup costs more than the benefit. | PR-17, PR-26 | break-even reported from partner data | unvalidated |
| 26 | SkyPilot already gives agents GPUs everywhere. | PR-22, PR-23, PR-20 | a better verified result at the same budget than SkyPilot where both support the resource, or the same result with less effort, time or cost | unvalidated |
| 27 | My agent already runs CUDA on my local GPU. | PR-05, PR-22, PR-23, PR-20 | beats direct local execution on verified outcome, or matches it with less effort, time or cost | unvalidated |

## 8. Differentiators to prove

| Differentiator | Value | Boundary |
|---|---|---|
| **Evidence-backed campaigns** (lead) | a best *correct* result with evidence (PR-22, PR-05) | the agent reasons, the core records |
| **Experiment memory** | rejected ideas are not retried blindly (PR-23) | facts apart from interpretations |
| Resources the user already has | local card and Colab subscription in one campaign (lab servers after GO) (PR-11, PR-03) | only tested backends (PR-18) |
| Fault recovery | reattach, keep partial results (PR-10) | resume only via an explicit checkpoint contract |
| Total cost per correct result | compute + agent (PR-21, PR-25) | unknowns disclosed |
| Hardware comparison | throughput, memory, cost across GPU types (PR-05) | never read as an algorithm speed-up |
| Token compression | structured verdicts (PR-12) | raw evidence on demand |
| Compute governance | one policy for destinations, spending, expiry, data (PR-07, PR-09) | same-user trust limits stated |

## 9. Success metrics and starting targets

Proposed starting targets, **not measured outcomes**: definitions and denominators are fixed before
the pilot, and targets are recalibrated with pilot data.

| Metric | Starting target | Definition notes |
|---|---|---|
| **Verified research outcome at a fixed budget and time** (**primary**) | one of two pre-registered routes (below) | best verified improvement; same task, model, oracle, budget and wall-time cap in every arm; a campaign with no improvement reports zero |
| Verified improvement per dollar and per hour | reported | failed attempts and agent cost included |
| Correctness | never worse than baselines | constraint, not a trade-off |
| Manual interventions per campaign | absolute count, ≤ the lowest baseline | pre-registered counting rules (approvals, recoveries); if a baseline is already near zero, this is a constraint, not the goal |
| First run | ≤ 3 min (warm), cold reported separately | provider waiting time reported separately |
| First verified experiment | reported, with oracle preparation time | existing tests reused where possible |
| Agent tokens per campaign | −30% | same model, task and correctness gate |
| Memory in a fresh session | reported | retrieval accuracy, avoidable repeated work, false duplicate suggestions; context-dependent retests still possible |
| Parallel vs sequential | reported | total time and cost (setup included), not GPU time only |
| Steady-state overhead | ≤ 5% vs direct execution | staging and transfer reported separately |
| Design partners | 5 before stage A is complete | local GPU and/or Colab users of the initial segment |
| External beta | 20 users | the advertised campaign works on their supported resources |
| 30-day repeat use | ≥ 40% of activated users | sample size reported |

**Two routes to GO**, each with margins and measurement rules fixed before the first run:

1. **Better outcome** — a practically meaningful improvement in verified outcome (at least the
   pre-registered margin) under the same resource envelope; or
2. **Same outcome, less cost** — verified outcome non-inferior within the pre-registered margin,
   with a meaningful reduction (at least the pre-registered margin) in manual interventions, elapsed
   time or total cost.

Correctness never worse, real resource limits and truthful reporting are non-negotiable in both
routes; the deciding metric is named in advance, not picked after the results. Otherwise ITERATE
or STOP; publishing results alone unlocks nothing.

## 10. Reaching users

- **Design partners now** (before more infrastructure): 5 people from the initial segment who use a
  local GPU and/or Colab — never recruited into workflows the beta does not support. Watch
  their real GPU workflow, then let them try a campaign with today's tool; record interventions,
  objections and whether they repeat it.
- **Acquisition:** a real ColorSplit campaign written up with raw data, a short demo, the free
  skill, a quick start. Channels: CUDA, research and coding-agent communities. Conversion measured
  from visit to first useful run (PR-26).
- **Retention:** repeat use at 7 and 30 days, reasons for abandonment and for switching back.
- **Monetization:** the core stays free and open. Safety, exact source and correctness are never
  paid features. Possible paid value (deep profiling, team workflows) is tested only after demand
  is shown; until then there is no paid tier.

## 11. Non-goals

Competing with multi-cloud orchestrators on breadth; distributed training and tightly coupled
multi-GPU workloads; automatic parallelization of arbitrary code; a general-purpose autonomous
research agent (the agent host reasons, MeetProxy records and enforces); a hosted MeetProxy service
(until proven demand); a scheduler; universal cloud provisioning; a guaranteed monetary cap without
provider support; protection against malicious code running as the same user.
