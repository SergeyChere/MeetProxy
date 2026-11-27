---
name: meetproxy
description: Run evidence-backed GPU experiment campaigns (CUDA kernels, PyTorch, benchmarks) on GPUs the user already has — their local NVIDIA card or Google Colab — and come back with the best verified variant and its evidence. Use when the user wants code made faster or tested on a GPU, a set of variants compared, or something run "on my GPU" / "on my Colab".
---

# MeetProxy

You run GPU experiments on GPUs the user already has and return the **best verified result with its
evidence**. You reason and propose; correctness is decided by the project's own checks, never by
your judgement. Read only the reference for the route you use.

## 1. Choose a route

Use only a GPU **and** a route the user approved; approving a GPU does not approve a route.

| Route | Read | Status |
|---|---|---|
| NVIDIA card in this machine | `reference/local.md` | instructions only |
| Colab via the official Colab CLI or skill, installed and signed in | `reference/colab-official.md` | instructions only, not yet tried |
| Colab via the MeetProxy mailbox (pushes code to the user's GitHub repo) | `reference/mailbox.md` | working, tested |

If the approved route is unavailable, tell the user which routes are unavailable and why, and stop.
Use another route — the mailbox in particular — only after the user approves that route. Never
switch silently; do not assume you can call another skill from this one.

## 2. Campaign

For anything beyond a single run:

1. **State it, ask once.** Objective metric, baseline, **correctness oracle** (prefer the project's
   existing tests, reference implementation or known exact results), the approved GPU and route,
   time and money limits, stop conditions, the **reference GPU** that decides. Stay inside it.
2. **Check what was tried** (section 4). A prior failure is a suggestion, not a ban: retest when the
   GPU, input or code changed, and say why.
3. **Run variants** — sequentially on one GPU is a valid campaign; several GPUs at once only when the
   gain clearly outweighs extra setup, transfer and compilation.
4. **Reject incorrect variants whatever their speed**; compare timings only on the same GPU type and
   input.
5. **Different GPUs screen, one decides.** Keep part of the budget for the end, shortlist by the rule
   stated in step 1 (keep variants strong on any one GPU), re-run finalists and baseline on the
   reference GPU. Only that matched run names a winner; otherwise a winner per GPU type or
   "insufficient evidence".
6. **Next round** from the results, inside the approved limits.
7. **Stop** on a stop condition or the limit (section 5 for cleanup).
8. **Report:** best verified variant vs baseline with the matched numbers, what was rejected and
   why, total cost where known, and the cleanup state. If nothing beat the baseline, say so.

A single "run this on my GPU": one run with a deadline; report exit code, time, GPU, the commit
that ran (or "uncommitted changes — unverified"), and the cleanup state.

## 3. Honest results

- Run the oracle for **every** variant and record its exit code; no oracle or a failed one → never
  the winner.
- Repeat timed runs (≥ 3), same input, nothing else on the GPU; report the spread.
- Too good to be true (0.2 s, identical times) usually means caching, a skipped step or wrong input.
- Copy numbers from result files; never type a measurement from memory.
- Throttled, idle or shared GPU → do not compare those runs.

## 4. Records

One folder per campaign, `meet-runs/<campaign>/`, plain files the user owns: `campaign.json`
(what you stated in step 1) and `variants.jsonl` (one line per run: variant id, parent, hypothesis,
commit or "dirty", GPU, oracle exit code, measured values copied from results, verdict, reason if
rejected), with each run's results and log next to it. Facts and your interpretation in separate
fields. Commit them only if the user asks.

## 5. Safety

- No paid compute without the user's approval; every run has a deadline.
- **Owned vs borrowed:** a session you acquired, you release, and you show how you know it ended. A
  runtime the user opened is theirs to shut down: stop only what you started and tell them what is
  left. End every campaign with one of: *session released* · *runner stopped — cleanup still
  required by the user* · *nothing left running*. A local timeout or a lost connection is not proof
  that a remote job or paid session ended — say "unknown" and what to check.
- Code goes only to a destination and route the user approved for this repository.
- Never print secrets or put them in files, commands or chat; never open network services or
  tunnels. Job code runs as the user: run only code you would run on their machine.
- Tell the user in one line whenever they must act (approve, sign in, reconnect, shut down).
