# MeetProxy skill

Lets your coding agent (Claude Code, Codex, Cursor, … — any agent that reads SKILL.md) run GPU
experiment campaigns on a GPU you already have and bring back the best verified variant with its
evidence.

## Install

Unzip this folder into your agent's skills directory, for example:

- Claude Code, one project: `<project>/.claude/skills/meetproxy/`
- Claude Code, all projects: `~/.claude/skills/meetproxy/`

## Routes

| Route | Status | You need |
|---|---|---|
| Your local NVIDIA card | instructions only | a CUDA project |
| Colab via the official Colab CLI / skill | instructions only, not yet tried | the official tool signed in |
| Colab via the MeetProxy mailbox | working and tested | a GitHub repo the agent can push to, paid Colab, one Colab secret `GH_TOKEN` (fine-grained token for this repo, *Contents: Read and write*), Python 3.8+ and git |

The agent uses only the GPU and the route you approve and asks before using another route.

## Use

Tell the agent: *"Find a faster correct version of my kernel on my GPU, using our tests as the
check."* or *"Run our benchmark on my Colab GPU."*

## Safety

Mailbox route: the notebook runs whatever is pushed to the repo's `meetproxy` branch, and the Colab
runtime is yours to shut down: give write access only to people
and agents you trust; job code runs as the same user as the runner. In a public repository the logs
are public too. Secrets in environment variables are masked in logs; a result file containing one is
not pushed.

Source and docs: https://github.com/SergeyChere/MeetProxy · MIT
