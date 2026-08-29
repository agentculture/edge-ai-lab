# edge-ai-lab

A lab for edge AI — the exploration engine for the mesh's edge and local-model work: designs, runs and compares experiments across edge hardware and model stacks, then hands proven configurations to lobes-cli, which is the runtime that serves them.

## Where it sits

- **[`lobes-cli`](https://github.com/agentculture/lobes-cli)** (binary `lobes`)
  is the **runtime** this lab feeds. `lobes` runs, assesses, and switches the
  local vLLM fleet the Culture mesh consumes, tuned per card by machine
  profiles and composed per box by deployment shapes. A configuration this lab
  proves lands there — as a profile/shape value, a catalog entry, a per-model
  doc, a deployment lock, or an evidence transcript — via a PR or issue on that
  repo.
- **[`sparkrun`](https://github.com/agentculture/sparkrun)** is the
  recipe-driven launcher for inference workloads on one or more NVIDIA DGX
  Sparks (vLLM / SGLang / llama.cpp, multi-node tensor parallelism). It is the
  experiment runner for Spark-class arms: an arm is a recipe YAML. Jetson-class
  arms (Thor, AGX Orin, Orin NX, Orin Nano) run through lobes profile/shape
  overrides instead.
- `dgx-spark-cli` / `rtx-spark-cli` operate the boxes themselves (setup,
  health, monitoring).

## Why it matters

- **Baselines are lost the moment a model is swapped.** lobes' own playbook
  (`../lobes-cli/docs/model-switch-playbook.md`, rule 1) opens with it:
  benchmark the incumbent first, on today's engine, because that number is
  unrecoverable once the checkpoint is gone. Without a lab that owns the arms,
  the Dockerfiles and the transcripts, every new box or checkpoint is re-derived
  ad hoc and the incumbent's number goes with it.
- **Experiments and serving are separate layers.** The lab is where things are
  allowed to break, be re-flagged and re-measured; lobes is where only proven
  configurations run. Keeping them apart means an experiment can never
  destabilise the fleet the mesh depends on, and every served configuration
  has a traceable experiment behind it.

## Who consumes the lab

| Consumer | The one path in |
|----------|-----------------|
| `lobes-cli` | A PR or issue on lobes-cli carrying a profile/shape TOML, a deployment lock (`deployments/<variation-id>/VARIATION.md`), or an evidence transcript — never an edit from this checkout. |
| `jetson-arena` | Statistics exported in the ingest format agreed with jetson-arena (as an issue there); the lab emits, arena stores and publishes — the lab never posts results itself. |
| sparkrun users | `sparkrun registry add <this repo>` — the lab publishes a sparkrun registry so Spark arms resolve as `@edge-ai-lab/<recipe>`. |

## Current state (as of 2026-08-29)

This is the before-state the spec was written against, and it is still true
until the plan's tasks land:

- This repository holds the mesh-agent scaffold — identity, agent-first CLI,
  vendored skill kit, CI/publish baseline — plus the rulebook
  [`docs/lab-conventions.md`](docs/lab-conventions.md). There is **no
  `setup/` tree, no `docs/evidence/`, and no Dockerfile** yet; the `arm` noun
  is being built.
- `lobes-cli`'s built-in profiles are exactly `spark`, `thor`, `orin` (AGX
  64GB) and `base`; Orin NX, Orin Nano and AGX Orin 32GB have none. Its
  `deployments/` variation catalog holds no real variation — capture needs
  physical hardware.
- `jetson-arena` is a scaffold with a scope sketch, not a running store.

The converged spec and build plan live at
[`docs/specs/2026-08-29-edge-arms-across-nvidia-boxes.md`](docs/specs/2026-08-29-edge-arms-across-nvidia-boxes.md)
and
[`docs/plans/2026-08-29-edge-arms-across-nvidia-boxes.md`](docs/plans/2026-08-29-edge-arms-across-nvidia-boxes.md).

## What you get

- **An agent-first CLI** cited from [teken](https://github.com/agentculture/teken)
  (`afi-cli`) — the runtime package has no third-party dependencies.
- **A mesh identity** — `culture.yaml` (`suffix: edge-ai-lab`, `backend:
  colleague`) and the matching resident prompt file `AGENTS.colleague.md`.
- **The lab rulebook** — [`docs/lab-conventions.md`](docs/lab-conventions.md):
  arm layout, evidence discipline, the shared-box budget rule, pins, rollback,
  secrets, hand-off.
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
reflex, the hand-off contract to lobes-cli — are in [`CLAUDE.md`](CLAUDE.md);
the lab's own rules are in [`docs/lab-conventions.md`](docs/lab-conventions.md).

## License

Apache 2.0 — see [`LICENSE`](LICENSE).
