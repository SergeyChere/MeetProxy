# colab-pilot skill

Lets your coding agent (Claude Code, Codex, Cursor, … — any agent that reads SKILL.md) run GPU
experiments on your Google Colab runtime by itself. You press one button in Colab; the agent sends
jobs and reads results through a branch of your own GitHub repository.

## Install

Unzip this folder into your agent's skills directory, for example:

- Claude Code, one project: `<project>/.claude/skills/colab-pilot/`
- Claude Code, all projects: `~/.claude/skills/colab-pilot/`

## Use

Tell the agent: *"Run our benchmark on my Colab GPU."* It will set things up and tell you what to
click. First time: you add one Colab secret (`GH_TOKEN`, a GitHub fine-grained token for this repo,
*Contents: Read and write*).

## You need

- your code in a GitHub repository the agent can push to;
- Google Colab with compute units (paid runtime) — colab-pilot is not a way around free-tier limits;
- Python 3.8+ and git on the agent side.

## Safety

The notebook runs whatever is pushed to the repo's `pilot` branch: give write access only to people
and agents you trust. In a public repository the logs are public too. Secrets in environment
variables are masked in logs.

Source and docs: https://github.com/SergeyChere/colab-pilot · MIT
