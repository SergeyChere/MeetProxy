# Instructions for an AI agent driving a GPU through colab-pilot

You have a GPU notebook reachable only through a git mailbox (`PILOT_DIR`, default `.pilot`).
The human started the runner and may be away for hours. Work like a careful experimenter.

1. **Check the machine first.** `pilot status` — is the heartbeat fresh, which GPU? Never compare
   timings from different GPUs. Put `# gpu: <name>` into jobs whose numbers matter.
2. **Write self-contained jobs.** A job is a bash script run in the project directory. It must
   install/build what it needs, and append one CSV line per measurement to
   `$PILOT_OUT/results.csv` — the runner pushes it during the run, so partial sessions still count.
3. **Bound everything.** Add `# timeout: N`. Estimate time before sending; prefer many short
   steps inside one session script over one step that may run all night.
4. **Read, don't guess.** `pilot wait <job> --follow`, then read the log and `.done`. If a result
   looks too good (finished in 0.2 s, identical times), suspect caching or a skipped step.
5. **Measure fairly.** Same GPU, same input, repeat runs, check that no other process uses the GPU
   (`nvidia-smi`) before timing. Verify correctness of every variant, not only speed.
6. **Job names are unique and sortable**: `s07_01_build`, `s07_02_bench`… A name runs once.
7. **When the human is away**, send one long session script that runs every planned variant and
   records each result as it finishes, rather than waiting for them to press buttons.
8. **Never**: print secrets, open network services or tunnels from a job, try to stop or delete
   the runtime, or merge the mailbox branch into code branches. `pilot stop` ends the runner.
9. Tell the human in one line when they must act (restart the runtime, pick another GPU).
