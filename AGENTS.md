# Agent instructions

An agent that drives a GPU with this tool: read `pilot/guide.md` (also printed by `pilot guide`).
An agent that develops this tool: keep `tests/roundtrip.sh` and `tests/skill_smoke.sh` passing and
the docs in sync — `skill/colab-pilot/SKILL.md` is a standalone copy of `pilot/guide.md` for skill
marketplaces; change both. `scripts/build_skill.sh` builds the upload zip in `dist/`.
