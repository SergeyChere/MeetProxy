# colab-pilot

Your AI agent runs experiments on your Colab GPU by itself. You press one button.

## You need

- a GitHub repository with your code;
- Google Colab with compute units (paid);
- Claude Code (or another coding agent) working in that repository.

## Start

**1. Colab:** [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/SergeyChere/colab-pilot/blob/main/examples/colab_runner.ipynb)
→ choose a GPU runtime → enter your repository (`owner/repo`) → **Run all**.

First time only: in Colab, key icon → add secret `GH_TOKEN` with a GitHub
[fine-grained token](https://github.com/settings/personal-access-tokens/new) for that repository,
*Contents: Read and write*.

**2. Claude:** say

> Use https://github.com/SergeyChere/colab-pilot to run our benchmarks on my Colab GPU.

Done. To stop: ■ in Colab. Shut the runtime down yourself when finished.

---

[Why it exists](docs/WHY.md) · [How it works](ARCHITECTURE.md) · Only people you trust should have
write access to the repository: the notebook runs what is pushed to its `pilot` branch. · MIT
