"""``lab arm export`` — hand an arm's result to a downstream store.

The only downstream today is jetson-arena, and the shape it ingests is **not
yet agreed**: the proposal lives in :data:`ARENA_CONTRACT_ISSUE`
(``docs/lab-conventions.md`` section 9). Honesty condition h9 of the spec
binds this verb — *the lab never commits to an export shape before that
thread records agreement, and the lab never posts statistics itself*. So this
module deliberately implements a **refusing stub**: it resolves and validates
the manifest through :mod:`edge_ai_lab.cli._commands.arm` (so a bad path or
manifest fails the same way everywhere), then exits with a structured error
pointing at the issue. There is no network code here and no path that writes
to arena or the site; agreement is recorded in the issue before anything is
emitted.

Wired in through the plug-in contract in ``arm.py`` (``_VERB_MODULES``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from edge_ai_lab.cli._commands.arm import _manifest_path, load_manifest
from edge_ai_lab.cli._errors import EXIT_USER_ERROR, CliError

#: The jetson-arena issue where the ingest contract is proposed and agreed.
ARENA_CONTRACT_ISSUE = "https://github.com/agentculture/jetson-arena/issues/8"

#: The stable identifier for the refusal (appears in the error message so
#: callers — and ``--json`` consumers — can match on it).
NOT_AGREED = "arena-format-not-agreed"

_FORMATS = ("arena",)


def cmd_arm_export(args: argparse.Namespace) -> int:
    fmt = args.format
    if fmt not in _FORMATS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"unknown export format '{fmt}'",
            remediation=f"pass --format one of: {', '.join(_FORMATS)}",
        )
    # Validate the arm first so a bad path/manifest is reported as such,
    # not masked by the contract refusal.
    load_manifest(_manifest_path(Path(args.path)))
    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"{NOT_AGREED}: the jetson-arena ingest format is not yet agreed",
        remediation=(
            f"see {ARENA_CONTRACT_ISSUE} — agreement is recorded there before this "
            "verb emits anything"
        ),
    )


def register(sub: argparse._SubParsersAction) -> None:
    ex = sub.add_parser(
        "export",
        help="Hand an arm's result to a downstream store (refuses until the contract is agreed).",
    )
    ex.add_argument("path", help="Arm directory or arm.toml path.")
    ex.add_argument(
        "--format",
        required=True,
        help="Target format; only 'arena' is known, and it is not yet agreed.",
    )
    ex.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ex.set_defaults(func=cmd_arm_export)
