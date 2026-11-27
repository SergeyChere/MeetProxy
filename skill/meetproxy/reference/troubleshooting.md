# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No runner has connected yet` | Notebook not started, or wrong REPO in it | Ask the user to run the notebook with `<owner/repo>` of this project |
| `Runner silent for N min` | Colab runtime disconnected or went idle | Ask the user to reconnect and *Run all* again; resend unfinished jobs under new names |
| `Runner exited (stopped)` / `(idle)` | `meet stop` was sent, or no jobs for 2 h | Ask the user to run the notebook cell again |
| Notebook: secret `GH_TOKEN` not found | Secret missing or notebook access off | Key icon → add `GH_TOKEN`, toggle *Notebook access* on |
| Notebook: push denied (403) | Token for another repo, or read-only | New fine-grained token for this repo, *Contents: Read and write* |
| Job runs old code | Commit not pushed, or you are on another branch | `git push`; check `code …` line in `.done` |
| `.done` says `wrong gpu` | `# gpu:` header does not match the runtime | Ask the user to switch runtime type, or relax the header |
| `.done` says `timeout` | Job exceeded `# timeout:` | Raise it, or split the job; partial results stay in `results.csv` |
| `job <name> exists` | Names run once | Use a new name (`s02b_bench`) |
| `meet: command not found` after setup | the venv is not on PATH in this shell | Run the `export PATH="$HOME/.meetproxy/venv-<version>/bin:$PATH"` line setup printed |
| setup exits with code 2 | MeetProxy (this version) is not installed | Ask the user; with consent rerun with `MEET_INSTALL=yes` |
| `python3 -m venv failed` | the system lacks the venv module | Install `python3-venv` (Debian/Ubuntu), then rerun |
| Timings jump between runs | Different GPU, or a stray process | Compare only same-GPU runs; the template refuses to start if the GPU is busy |
