# colab-pilot

Your AI agent runs experiments on your Colab GPU by itself. You press one button.

## You need

- a GitHub repository with your code;
- Google Colab with compute units (paid);
- Claude Code (or another coding agent) working in that repository.

## Start

**1. Colab:** click [![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/SergeyChere/colab-pilot/blob/main/colab_runner.ipynb), then:

- *Runtime → Change runtime type* → pick a GPU;
- in the notebook's `REPO` field, type **your project's** GitHub repository — the one Claude works
  in — as `owner/name`. For `https://github.com/alice/my-kernels` that is `alice/my-kernels`;
- *Runtime → Run all*.

First time only: key icon on the left → add a secret named `GH_TOKEN` with a GitHub
[fine-grained token](https://github.com/settings/personal-access-tokens/new) for that same
repository, *Contents: Read and write*.

The button opens [`colab_runner.ipynb`](colab_runner.ipynb). It is one cell; you can
also paste it into any Colab notebook yourself:

```python
REPO = "alice/my-kernels"  #@param {type:"string"}
!pip -q install git+https://github.com/SergeyChere/colab-pilot
import pilot.runner
pilot.runner.colab_start(REPO)
```

**2. Claude:** say

> Use https://github.com/SergeyChere/colab-pilot to run our benchmarks on my Colab GPU.

Done. To stop: ■ in Colab. Shut the runtime down yourself when finished.

**Or as a skill:** copy [`skill/colab-pilot`](skill/colab-pilot) into `.claude/skills/` (or your
agent's skills folder) and just say *"run our benchmark on my Colab GPU"*.

---

[Why it exists](docs/WHY.md) · [How it works](ARCHITECTURE.md) · Only people you trust should have
write access to the repository: the notebook runs what is pushed to its `pilot` branch. · MIT
