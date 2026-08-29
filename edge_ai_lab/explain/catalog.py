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

- `lab whoami` — identity probe from `culture.yaml`.
- `lab learn` — structured self-teaching prompt.
- `lab explain <path>` — markdown docs for any noun/verb.
- `lab overview` — descriptive snapshot of the agent.
- `lab doctor` — check the agent-identity invariants.
- `lab cli overview` — describe the CLI surface.

## Exit-code policy

- `0` success
- `1` user-input error
- `2` environment / setup error
- `3+` reserved

## See also

- `lab explain whoami`
- `lab explain doctor`
"""

_WHOAMI = """\
# edge-ai-lab whoami

Reports the agent's identity from `culture.yaml`: nick (`suffix`), backend,
served model, and the package version. Read-only.

## Usage

    lab whoami
    lab whoami --json
"""

_LEARN = """\
# edge-ai-lab learn

Prints a structured self-teaching prompt covering purpose, command map,
exit-code policy, `--json` support, and the `explain` pointer.

## Usage

    lab learn
    lab learn --json
"""

_EXPLAIN = """\
# edge-ai-lab explain <path>

Prints markdown documentation for any noun/verb path. Unlike `--help` (terse,
positional), `explain` is global and addressable by path.

## Usage

    lab explain edge-ai-lab
    lab explain whoami
    lab explain --json <path>
"""

_OVERVIEW = """\
# edge-ai-lab overview

Read-only descriptive snapshot of the agent: identity (from `culture.yaml`), the
verb surface, and the sibling-pattern artifacts the template carries. Accepts an
ignored `target` so a stray path never hard-fails.

## Usage

    lab overview
    lab overview --json
"""

_DOCTOR = """\
# edge-ai-lab doctor

Checks the agent-identity invariants `steward doctor` verifies:
prompt-file-present and backend-consistency (`colleague` → `AGENTS.colleague.md`), plus a
skills-present check. Exits 1 when unhealthy.

## Usage

    lab doctor
    lab doctor --json
"""

_CLI = """\
# edge-ai-lab cli

Noun group for CLI-surface introspection. `cli overview` describes the CLI
itself (distinct from the global `overview`, which describes the agent).

## Usage

    lab cli overview
    lab cli overview --json
"""

_ARM = """\
# edge-ai-lab arm

Noun group for **arms** — experiment directories at
`setup/<device-class>/<model>/<configuration>/`, each described by an
`arm.toml` manifest (parsed with the standard library's `tomllib`; see
`docs/lab-conventions.md` section 2 for the full schema). Read-only today:
`list` and `show`. Later verbs (`validate`, `run`, `export`) land as their own
`arm_<verb>.py` modules.

## Manifest fields

`device_class`, `model`, `configuration`, `format`
(`sparkrun-recipe`|`lobes-override`), `engine`, `box`, `status`
(`measured`|`declared-unvalidated`|`virtual-32gb-capacity-only`), `[pins]`
table, `transcripts` (paths under `docs/evidence/`).

## Usage

    lab arm overview
    lab arm list [--root PATH] [--json]
    lab arm show <path> [--json]

## See also

    lab explain arm overview
    lab explain arm list
    lab explain arm show
"""

_ARM_OVERVIEW = """\
# edge-ai-lab arm overview

Describes the `arm` noun: its verbs and the `arm.toml` manifest schema.

## Usage

    lab arm overview
    lab arm overview --json
"""

_ARM_LIST = """\
# edge-ai-lab arm list

Walks `<root>/setup/**/arm.toml` (root defaults to this checkout's repo root)
and prints one row per arm: `device_class`, `model`, `configuration`,
`format`, `status`, `path`. A manifest that fails to parse or validate is
skipped with a diagnostic on stderr rather than aborting the whole listing.

## Usage

    lab arm list
    lab arm list --root /path/to/checkout
    lab arm list --json
"""

_ARM_SHOW = """\
# edge-ai-lab arm show <path>

Prints one arm's manifest. `<path>` is either the arm's directory or its
`arm.toml` file directly. Parsed and validated with `tomllib`: a missing
required field, an invalid `format`/`status` enum value, or a missing file
raises a structured error (exit 1) naming the problem field.

## Usage

    lab arm show setup/spark/qwen3.8-27b-fp8/vllm-mtp/
    lab arm show setup/spark/qwen3.8-27b-fp8/vllm-mtp/arm.toml --json
"""

_ARM_VALIDATE = """\
# edge-ai-lab arm validate <path>

Checks an arm against `docs/lab-conventions.md`: the manifest loads
(`arm.py`'s helpers), the README carries `## Rollback` (a fenced,
non-placeholder command), `## Build footprint` (measured `Build time:`,
`Disk delta:`, `Retention:`), and `## Pins` (every manifest `[pins]` key,
empty pins explained with `empty`/`n/a`); the honesty status marker matches
`status` (`measured` transcripts exist on disk, `declared-unvalidated` README
carries `DECLARED, UNVALIDATED`, `virtual-32gb-capacity-only` README and
manifest carry `capacity-only` and README carries `measured on 64GB
hardware`); the `Dockerfile` (if present) pins a `FROM ...@sha256:` digest or
carries a jetson-containers header (commit + `L4T_VERSION`/`CUDA_VERSION`/
`CUDA_ARCH`); and no secret-like pattern appears under the arm directory.
Each check reports `{id, passed, message}`; exit 0 only if every check
passes, else a structured error naming the first failing check.

## Usage

    lab arm validate setup/spark/qwen3.8-27b-fp8/vllm-mtp/
    lab arm validate setup/spark/qwen3.8-27b-fp8/vllm-mtp/arm.toml --json
    lab arm validate <path> --root /path/to/checkout
"""


_ARM_EXPORT = """\
# edge-ai-lab arm export <path> --format arena

Hands an arm's result to a downstream store. The only target is jetson-arena,
and its ingest shape is **not yet agreed** — the proposal is
<https://github.com/agentculture/jetson-arena/issues/8>. Until that thread
records agreement this verb validates the manifest and then refuses with
`arena-format-not-agreed` (exit 1), pointing at the issue. It never posts
anywhere: the lab emits, jetson-arena stores and publishes
(`docs/lab-conventions.md` section 9).

## Usage

    lab arm export setup/spark/qwen3.8-27b-fp8/vllm-mtp/ --format arena
    lab arm export setup/spark/qwen3.8-27b-fp8/vllm-mtp/ --format arena --json
"""


_ARM_RUN = """\
# edge-ai-lab arm run <path>

Runs one arm on the box it names (`docs/lab-conventions.md` sections 3-5, 8,
10). Refuses if a box marker (`<deploy-dir>/arm.lock`, default
`$LAB_DEPLOY_DIR` or `~/.edge-ai-lab`) already names a running arm — the
`hint:` line names its path. Otherwise: captures a best-effort before
snapshot (`docker ps`, `docker system df`, `df -h /`, `nvpmodel -q`, GPU
devfreq, `free -g`, thermals — a missing tool records `unavailable`, never
fails the run); writes the marker; launches `uvx
sparkrun==<pins.sparkrun_version> run <recipe>` (`SPARKRUN_NO_TELEMETRY=1`)
for a `sparkrun-recipe` arm or each `[run].commands` entry for a
`lobes-override` arm; removes the marker in a `finally:` and on `SIGTERM` so
an abnormal exit still clears it; captures an after snapshot; probes the
gateway's `GET /capabilities` (a non-200 reply is reported as a warning, not
a failure); and writes a transcript skeleton under `docs/evidence/` (never
overwriting — `-2`, `-3`, ...) with empty `## measurements` value lines,
since a run never fabricates a number. `[run].port` must not be 8000/8001
(the fleet's own ports). `--dry-run` does everything except the launch and
reports the argv/env it would have used.

## Usage

    lab arm run setup/spark/qwen3.8-27b-fp8/vllm-mtp/
    lab arm run setup/spark/qwen3.8-27b-fp8/vllm-mtp/ --dry-run --json
    lab arm run <path> --deploy-dir /var/lib/edge-ai-lab
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
    ("arm",): _ARM,
    ("arm", "overview"): _ARM_OVERVIEW,
    ("arm", "list"): _ARM_LIST,
    ("arm", "show"): _ARM_SHOW,
    ("arm", "validate"): _ARM_VALIDATE,
    ("arm", "export"): _ARM_EXPORT,
    ("arm", "run"): _ARM_RUN,
}
