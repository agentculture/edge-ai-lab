# edge-ai-lab

A lab for edge AI — the exploration engine for the mesh's edge and local-model work: designs, runs and compares experiments across edge hardware and model stacks, then hands proven configurations to lobes-cli, which is the runtime that serves them.

## Where it sits

- **[`lobes-cli`](https://github.com/agentculture/lobes-cli)** (binary `lobes`)
  is the **runtime** this lab feeds. `lobes` runs, assesses, and switches the
  local vLLM fleet the Culture mesh consumes, tuned per card by machine
  profiles and composed per box by deployment shapes. A configuration this lab
  proves lands there — as a profile/shape value, a catalog entry, a per-model
  doc, or an evidence transcript — via a PR or issue on that repo.
- **[`sparkrun`](https://github.com/agentculture/sparkrun)** is the
  recipe-driven launcher for inference workloads on one or more NVIDIA DGX
  Sparks (vLLM / SGLang / llama.cpp, multi-node tensor parallelism). It is the
  natural experiment runner for Spark-class arms: an arm is a recipe YAML.
- `dgx-spark-cli` / `rtx-spark-cli` operate the boxes themselves (setup,
  health, monitoring).

**Current state:** this repository is the mesh-agent scaffold — identity,
agent-first CLI, vendored skill kit, CI/publish baseline. The experiment
harness and results store are not built yet; the conventions they must follow
(evidence-before-claims, benchmark-the-incumbent-first, keep unadopted
experiments on record) are documented in [`CLAUDE.md`](CLAUDE.md).

## What you get

- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken)
  (`afi-cli`) — the runtime package has no third-party dependencies.
- **A mesh identity** — `culture.yaml` (`suffix: edge-ai-lab`, `backend:
  colleague`) and the matching resident prompt file `AGENTS.colleague.md`.
- **The canonical guildmaster skill kit** under `.claude/skills/`, vendored
  cite-don't-import. See [`docs/skill-sources.md`](docs/skill-sources.md).
- **A build + deploy baseline** — pytest, lint, the agent-first rubric gate, and
  PyPI Trusted Publishing wired into GitHub Actions.

## Quickstart

```bash
uv sync
uv run pytest -n auto                 # run the test suite
uv run lab whoami                     # identity from culture.yaml
uv run lab learn                      # self-teaching prompt (add --json)
uv run teken cli doctor . --strict    # the agent-first rubric gate CI runs
```

The console script is **`lab`** (`python -m edge_ai_lab` is equivalent).

## CLI

| Verb | What it does |
|------|--------------|
| `whoami` | Report this agent's nick, version, backend, and model from `culture.yaml`. |
| `learn` | Print a structured self-teaching prompt. |
| `explain <path>` | Markdown docs for any noun/verb path. |
| `overview` | Read-only descriptive snapshot of the agent. |
| `doctor` | Check the agent-identity invariants (prompt-file-present, backend-consistency). |
| `cli overview` | Describe the CLI surface itself. |

Every command supports `--json`. Results go to stdout, errors/diagnostics to
stderr (never mixed). Exit codes: `0` success, `1` user error, `2` environment
error, `3+` reserved.

## Contributing

Every PR bumps the version (`python3 .claude/skills/version-bump/scripts/bump.py
<patch|minor|major>` — one bump type per run; CI blocks merge otherwise) and goes through the `cicd`
skill (`devex pr` + SonarCloud gate). Lint is black / isort / flake8 (line
length 100) / bandit / markdownlint plus `teken cli doctor . --strict`. Full
conventions — worktree placement, memory discipline, the `ask-colleague`
reflex, the hand-off contract to lobes-cli — are in [`CLAUDE.md`](CLAUDE.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
