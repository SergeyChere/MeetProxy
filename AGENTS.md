# Agent instructions

An agent that drives a GPU with this tool: read `pilot/guide.md` (also printed by `pilot guide`).
An agent that develops this tool: keep `bash tests/run_all.sh` passing (pytest unit, CLI and
end-to-end tests in `tests/test_*.py`, plus `tests/roundtrip.sh` and `tests/skill_smoke.sh`; CI runs
it on every push) and add a test with every change — a bug fix starts with a test that fails. Keep
the docs in sync — `skill/colab-pilot/SKILL.md` is a standalone copy of `pilot/guide.md` for skill
marketplaces; change both. `scripts/build_skill.sh` builds the upload zip in `dist/`.
