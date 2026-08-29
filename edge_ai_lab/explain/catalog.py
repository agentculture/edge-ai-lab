"""Markdown catalog for ``edge-ai-lab explain <path>``.

Each entry is verbatim markdown. Keys are command-path tuples. The empty tuple
and ``("edge-ai-lab",)`` both resolve to the root entry.

Keep bodies self-contained: an agent reading one entry should get enough
context without chaining reads.
"""

from __future__ import annotations

_ROOT = """\
# edge-ai-lab

A clonable template for AgentCulture mesh agents. It carries an agent-first CLI
(cited from the teken `python-cli` reference), a mesh identity (`culture.yaml` +
`CLAUDE.md`), the canonical guildmaster skill kit under `.claude/skills/`, and a
buildable/deployable package baseline. Clone it, rename the package, edit
`culture.yaml`, and you have a new agent.

## Verbs

- `edge-ai-lab whoami` — identity probe from `culture.yaml`.
- `edge-ai-lab learn` — structured self-teaching prompt.
- `edge-ai-lab explain <path>` — markdown docs for any noun/verb.
- `edge-ai-lab overview` — descriptive snapshot of the agent.
- `edge-ai-lab doctor` — check the agent-identity invariants.
- `edge-ai-lab cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `edge-ai-lab explain whoami`
- `edge-ai-lab explain doctor`
"""

_WHOAMI = """\
# edge-ai-lab whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    edge-ai-lab whoami
    edge-ai-lab whoami --json
"""

_LEARN = """\
# edge-ai-lab learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    edge-ai-lab learn
    edge-ai-lab learn --json
"""

_EXPLAIN = """\
# edge-ai-lab explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    edge-ai-lab explain edge-ai-lab
    edge-ai-lab explain whoami
    edge-ai-lab explain --json <path>
"""

_OVERVIEW = """\
# edge-ai-lab overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    edge-ai-lab overview
    edge-ai-lab overview --json
"""

_DOCTOR = """\
# edge-ai-lab doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    edge-ai-lab doctor
    edge-ai-lab doctor --json
"""

_CLI = """\
# edge-ai-lab cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    edge-ai-lab cli overview
    edge-ai-lab cli overview --json
"""


ENTRIES: dict[tuple[str, ...], str] = {
    (): _ROOT,
    ("edge-ai-lab",): _ROOT,
    ("lab",): _ROOT,
    ("whoami",): _WHOAMI,
    ("learn",): _LEARN,
    ("explain",): _EXPLAIN,
    ("overview",): _OVERVIEW,
    ("doctor",): _DOCTOR,
    ("cli",): _CLI,
    ("cli", "overview"): _CLI,
}
