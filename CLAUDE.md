# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`edge-ai-lab` is the AgentCulture mesh's **lab for edge AI** — the exploration
engine for edge and local-model work. It designs, runs, and compares
experiments across edge hardware and model stacks, then hands **proven**
configurations to the runtime that serves them. It explores; it does not serve.

It sits between two kinds of sibling:

- **[`lobes-cli`](../lobes-cli)** (binary `lobes`) — the **runtime** and the
  consumer of this lab's output. `lobes` runs, assesses, and switches the
  local OpenAI-compatible vLLM fleet the mesh consumes (roles `cortex`,
  `senses`, `worker`, `hand`, `embedder`, `reranker`, …), tuned per card by
  **machine profiles** (`lobes/profiles/builtin/*.toml`) and composed per box
  by **deployment shapes** (`lobes/profiles/builtin_shapes/*.toml`). A
  configuration this lab proves lands there — as a profile/shape value, a
  catalog entry, a `docs/<model>.md` page, or an evidence transcript.
- **[`sparkrun`](https://github.com/agentculture/sparkrun)** — a recipe-driven
  launcher for LLM inference workloads on one or more NVIDIA DGX Sparks
  (vLLM / SGLang / llama.cpp, multi-node tensor parallelism where `--tp N` =
  N hosts, `sparkrun show <recipe>` VRAM estimation, git-based recipe
  registries benchmarked via Spark Arena). It is the natural **experiment
  runner** for Spark-class hardware: an experiment arm is a recipe YAML
  (`model`, `runtime`, `container`, `defaults`, `env`). It is **not cloned in
  this workspace** — install with `uvx sparkrun setup` / read its `RECIPES.md`
  upstream. The hardware-operator siblings `../dgx-spark-cli` and
  `../rtx-spark-cli` cover device setup and health for the boxes themselves.

**Honesty about the current state:** the checked-in code is the mesh-agent
scaffold (identity, agent-first CLI, skill kit, CI). There is no experiment
harness, results store, or `experiment` noun in the CLI yet. Anything below
that describes how experiments *should* flow is guidance for building that
surface, not a description of code that exists — keep it that way when you
edit this file (mark unbuilt things `(planned)` or put them under `## Roadmap`).

## Identity

Declared in `culture.yaml`:

```yaml
agents:
- suffix: edge-ai-lab
  backend: colleague
  model: sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP
```

`backend: colleague` fixes the resident prompt file to **`AGENTS.colleague.md`**
(the mesh runtime reads that; this `CLAUDE.md` is Claude Code guidance only).
The two `steward doctor` invariants — **prompt-file-present** and
**backend-consistency** (`colleague` ↔ `AGENTS.colleague.md`) — are the same
ones `lab doctor` checks locally. The mesh daemon does **not** load this file
or the user's global Claude Code instructions; behavior the resident must
follow belongs in `AGENTS.colleague.md`.

Known drift to resolve deliberately, not silently: `culture.yaml` still pins
the Qwen3.6 text-only checkpoint, while `CHANGELOG.md` 0.7.0 records that the
colleague default moved to `unsloth/Qwen3.8-27B-NVFP4` because the lobes
gateway on `:8001` no longer serves 3.6 (and `lobes-cli` lists 3.6-Text as a
demoted candidate). `tests/test_cli.py` only asserts `model:` is present, so
changing the pin is safe test-wise.

## Commands

```bash
uv sync                                   # dev env (Python >=3.12; runtime deps are empty)

# CLI — the console script is `lab` (pyproject [project.scripts]), NOT `edge-ai-lab`.
uv run lab whoami                         # identity from culture.yaml (add --json anywhere)
uv run lab learn                          # other verbs: explain <path>, overview, doctor, cli overview
uv run python -m edge_ai_lab whoami       # equivalent

# Tests
uv run pytest -n auto                     # full suite (what CI runs, minus coverage)
uv run pytest tests/test_cli.py::test_whoami_text -v        # single test
bash .claude/skills/run-tests/scripts/test.sh --ci          # CI-identical: xdist + coverage.xml
uv run pytest --cov --cov-report=term     # coverage; fail_under = 60 (pyproject)

# Lint (all of these gate CI in .github/workflows/tests.yml)
uv run black --check edge_ai_lab tests    # line length 100
uv run isort --check-only edge_ai_lab tests
uv run flake8 edge_ai_lab tests           # .flake8: max-line-length 100, ignores E203/W503
uv run bandit -c pyproject.toml -r edge_ai_lab
markdownlint-cli2 "**/*.md" "#node_modules" "#.local" "#.claude/skills" "#.teken"
uv run teken cli doctor . --strict        # agent-first rubric gate

# Version (required on every PR — the version-check CI job blocks merge otherwise)
python3 .claude/skills/version-bump/scripts/bump.py show
echo '{"added":["..."],"changed":["..."],"fixed":["..."]}' \
  | python3 .claude/skills/version-bump/scripts/bump.py patch   # exactly one of: patch, minor, major

# PR lifecycle (cicd skill → devex pr + SonarCloud gate)
bash .claude/skills/cicd/scripts/workflow.sh help   # verbs: lint, open, read, reply, delta, status, await
```

The `prog` string, `learn` text, README, and test assertions all say
`edge-ai-lab`, but the installed binary is `lab` (the `explain` catalog even
registers `("lab",)` as a root alias). If you rename one side, rename both.

## Architecture

### The CLI (`edge_ai_lab/`)

Cited (cite-don't-import) from teken's `python-cli` reference, so the runtime
package has **no third-party dependencies**; `teken` is a dev dependency only.
The shape matters more than the current verbs, because every future lab noun
(e.g. an `experiment` group) must follow it to keep passing the rubric gate:

- **Registration:** `cli/__init__.py::_build_parser()` builds a
  `_CliArgumentParser` and calls each `cli/_commands/<verb>.py::register(sub)`.
  A noun group (see `_commands/cli.py`) adds its own sub-subparsers with
  `parser_class=type(p)` so parse errors keep the structured contract. Any
  noun that has action verbs **must** also expose `<noun> overview`
  (rubric check `overview_cli_noun_exists`).
- **Error contract:** handlers raise `cli/_errors.py::CliError(code, message,
  remediation)`; `_dispatch()` catches it (and wraps any other exception) so no
  traceback ever reaches stderr. Text mode prints `error: …` + `hint: …`; JSON
  mode prints `{code, message, remediation}`. Argparse errors are routed the
  same way — `main()` pre-scans argv for `--json` into
  `_CliArgumentParser._json_hint` because parse-time errors happen before
  `args.json` exists.
- **Output contract (`cli/_output.py`):** results → stdout, diagnostics/errors
  → stderr, never mixed; every verb takes `--json`. Exit codes: `0` success,
  `1` user error, `2` environment error, `3+` reserved.
- **Identity resolution:** `_commands/whoami.py::find_culture_yaml()` walks up
  from `__file__`, not from CWD, so the agent reports *its own* identity from
  any working directory; a wheel install (no `culture.yaml`) falls back to
  literal defaults and `doctor` reports a single info check. `culture.yaml` is
  parsed by hand (first agent block only) to keep deps empty.
- **Explain catalog (`explain/catalog.py::ENTRIES`):** markdown keyed by
  command-path tuples. `tests/test_cli.py::test_every_catalog_path_resolves`
  iterates every key, so a new verb without a catalog entry — or a catalog
  entry without a verb — fails tests.

### Tests

`tests/test_cli.py` (smoke: version, help, structured errors, every global
verb in text + JSON) and `tests/test_cli_introspection.py` (`overview`,
`cli overview`, `doctor` shapes). They call `main([...])` in-process with
`capsys`; there is no subprocess spawning and no fixture setup, so a single
test runs in milliseconds.

### CI / deploy

- `tests.yml`: `test` (xdist + coverage.xml → SonarCloud scan, skipped when
  `SONAR_TOKEN` is absent, e.g. fork PRs; `sonar.qualitygate.wait=true` makes
  a red gate fail the job), `lint` (black/isort/flake8/bandit/markdownlint +
  `teken cli doctor --strict`), and `version-check` (PR-only; fails if
  `pyproject.toml` version equals `origin/main`'s and leaves a marker comment).
- `publish.yml`: **same-repo** PRs touching `pyproject.toml` or
  `edge_ai_lab/**` publish a `.dev<run>` build to TestPyPI (fork PRs skip
  `test-publish` — no OIDC/environment context); push to `main` publishes to
  PyPI via Trusted Publishing (needs the `pypi`/`testpypi` GitHub environments
  configured).
- `.markdownlint-cli2.yaml` is repo-local because markdownlint stops walking
  at the git root; it ignores `.claude/skills/**` on purpose (vendored,
  verbatim).

## How lab work should flow (planned surface; conventions apply now)

The runtime's evidence discipline is the contract this lab exists to feed, so
adopt it from day one even before there is code for it:

- **Nothing reads as validated without a transcript.** `lobes-cli` (#108) will
  not let a number appear in a doc, support table, or `lobes capabilities`
  output unless a raw measurement transcript from a physical box sits under
  its `docs/evidence/` (`YYYY-MM-DD-{spike,accept}-<what>-<box>.txt`).
  Declared-but-unmeasured values are labelled **UNVALIDATED**. Every number
  states where it came from (a published card, or a measurement on a *named*
  model and window). Never back-fill a value a run did not capture.
- **Benchmark the incumbent first, on today's engine** — that baseline is
  unrecoverable once the model is swapped. Measure decode throughput from
  `usage.completion_tokens`, never by counting stream chunks (speculative
  decoding emits several tokens per chunk; the playbook records a >2× error
  from that trap). Run short/medium/long-generation shapes; record TTFT,
  prompt tokens, MTP/draft acceptance, KV pool and the `max_model_len` in
  force. See `../lobes-cli/docs/model-switch-playbook.md` and
  `docs/measuring-lane-performance.md` there.
- **Experiments that are not adopted keep their record.** lobes-cli's
  `docs/experiments/` answers *what it is, why we wanted it, why it is not
  running*; a graduated experiment keeps its file. Mirror that here
  (cite-don't-delete).
- **Hand-off is a PR or issue on the sibling, never an edit from here.** A
  proven configuration becomes a change to lobes-cli's profile/shape TOML,
  `catalog.py`, `docs/<model>.md`, or `docs/evidence/` — filed with the
  `communicate` skill (`post-issue.sh`, auto-signed `- edge-ai-lab (Claude)`)
  or opened as a PR in that checkout. Remember that swapping a served
  checkpoint id 404s every consumer that pins the raw id (the playbook's §2).
- **Spark-class arms run as sparkrun recipes**; Thor/Orin-class arms run
  through lobes' own profiles/shapes (`thor`, `orin-small`, …). Keep the arm
  definition (recipe or shape override) next to its transcript so a result is
  reproducible without re-deriving flags.

## Skills (`.claude/skills/`)

The canonical guildmaster skill kit, vendored cite-don't-import — provenance
and the re-sync procedure live in `docs/skill-sources.md`. Skill copies are
**cited verbatim**: do not reformat or edit their scripts; re-sync from the
upstream named in the ledger. Two tracked divergences: `ask-colleague` is
vendored directly from `../colleague` (guildmaster still re-broadcasts the old
`outsource` name) and `scope`/`challenge`/`deviate`/`summarize-delivery` come
directly from `../devague` (guildmaster's copies carry an extra `scripts/`
wrapper). Every `SKILL.md` carries `type: command` — load-bearing, the culture
skill loader silently skips skills without it.

Tooling on PATH: **`devex`** (>=0.21; `cicd` delegates the PR lifecycle to
`devex pr`), **`agtag`** (`communicate` wraps `agtag issue`), **`teken`** (dev
dep; rubric gate), **`eidetic`** (`remember`/`recall`), and optionally
**`colleague`** (`ask-colleague` exits with an install hint if absent).
Per-machine sibling paths go in `.claude/skills.local.yaml` (git-ignored; see
the committed `.example`).

## Conventions

- **Every PR bumps the version** — even docs/config/CI-only changes. Use the
  `version-bump` skill; CI blocks merge otherwise. `pyproject.toml` is the
  single source of truth (`edge_ai_lab.__version__` reads package metadata).
- **PRs go through the `cicd` skill** (`devex pr` + SonarCloud gating via
  `status`/`await`). Sign online posts as `- edge-ai-lab (Claude)`; the
  `cicd`/`communicate` scripts resolve the nick from `culture.yaml` and append
  it themselves — don't sign the body manually when they author the post.
- **Reach for `ask-colleague` reflexively.** Its value is a *different* mind
  (the local Qwen backend), not a stronger one. `review` before presenting or
  opening a PR on a non-trivial committed diff; `explore` for a fresh read of
  an unfamiliar area. Both are read-only (throwaway worktree under
  `${TMPDIR:-/tmp}`, reaped on exit). `write --apply` / `write --pr` need the
  user's go-ahead. Treat its output as a second opinion to verify, never
  authority.
- **Worktrees you create live in `../.worktrees.edge-ai-lab/<name>/`** —
  `git worktree add ../.worktrees.edge-ai-lab/<name> -b <prefix>/<name>`.
  Never a shared `../worktrees/` folder (this workspace holds many sibling
  repos and orphaned trees become indistinguishable). Scope the branch prefix
  to the work (`retire/t2`, not `agent/t2` — plain `agent/*` collides with
  earlier fan-out leftovers). The vendored `assign-to-workforce` skill's
  example uses both the shared path and `agent/<id>` branches; it is verbatim
  and must not be edited, so override both when following it. Remove with
  `git worktree remove <path>` (`prune` only clears metadata for already-gone
  directories). `ask-colleague`'s tool-managed temp worktrees are exempt.
- **Memory discipline — `/recall` before, `/remember` after.** Search the
  eidetic store before non-trivial work; capture non-obvious decisions,
  constraints, fix-and-why, and gotchas as they surface. Note the wrappers
  here default records to the agent's **private** `edge-ai-lab` scope
  (`$HOME/.eidetic/memory`, never committed; the scope suffix is read from
  `culture.yaml`, so Claude and the colleague backend share it). Pass
  `--visibility public` to land a record in the committed
  `<repo-root>/.eidetic/memory` pool (no such directory exists yet). Don't
  store what the repo already records.
- **The description string is duplicated** in `pyproject.toml`, `README.md`,
  and this file; the CLI's `prog`/`learn`/`overview` prose still describes the
  generic template. Update them together when the lab's own surface lands.

## Layout

```text
edge_ai_lab/              agent-first CLI (cited from teken's python-cli reference)
  cli/                    parser + error/output contract; _commands/ = one module per verb
  explain/                markdown catalog for `lab explain <path>`
tests/                    in-process pytest smoke + introspection tests
.claude/skills/           vendored skill kit (verbatim; see docs/skill-sources.md)
docs/skill-sources.md     skill provenance ledger + re-sync procedure
culture.yaml              mesh identity (suffix + backend + model)
AGENTS.colleague.md       resident prompt the mesh runtime actually loads
.github/workflows/        tests.yml (test/lint/version-check) + publish.yml (TestPyPI/PyPI)
```

This file describes the repository **as it exists on disk today**. Keep claims
grounded in checked-in reality; if a section drifts ahead of it, mark it
`(planned)` or move it under a `## Roadmap` heading.
