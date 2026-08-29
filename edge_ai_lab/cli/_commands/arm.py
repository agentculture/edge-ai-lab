"""``edge-ai-lab arm`` — noun group over experiment arms under ``setup/**/arm.toml``.

An **arm** is one experiment: a hardware class, a model, and one configuration
of it, addressed by the path ``setup/<device-class>/<model>/<configuration>/``
and described by that directory's ``arm.toml`` manifest. The manifest schema
(required fields, ``format``/``status`` enums, the ``[pins]`` table) is
defined in ``docs/lab-conventions.md`` section 2 — this module is the CLI's
read side of that contract: ``arm list`` and ``arm show`` only. Manifests are
parsed with the standard library's ``tomllib`` (no third-party dependency).

Plug-in layout contract
------------------------
Later verbs — ``validate`` (t5), ``run`` (t6), ``export`` (t4) — are added as
``edge_ai_lab/cli/_commands/arm_<verb>.py`` modules, each exposing a
``register(sub)`` function that adds its own sub-parser to the ``arm``
sub-subparsers action. Wiring a new verb in is exactly two edits:

1. write ``arm_<verb>.py`` with a ``register(sub)`` function;
2. add its module name to ``_VERB_MODULES`` below.

No other file in this module changes. Each name in ``_VERB_MODULES`` is
imported via :func:`importlib.import_module`, guarded by
``try/except ModuleNotFoundError`` — a name listed before its module exists
(or during incremental development) never breaks ``arm`` itself.
"""

from __future__ import annotations

import argparse
import importlib
import tomllib
from pathlib import Path

from edge_ai_lab.cli._commands.overview import emit_overview
from edge_ai_lab.cli._commands.whoami import find_culture_yaml
from edge_ai_lab.cli._errors import EXIT_USER_ERROR, CliError
from edge_ai_lab.cli._output import emit_diagnostic, emit_result

# Later tasks add their module here and nowhere else in this file.
_VERB_MODULES = ("arm_validate", "arm_run", "arm_export")

# The `arm.toml` schema (docs/lab-conventions.md section 2).
_FORMATS = {"sparkrun-recipe", "lobes-override"}
_STATUSES = {"measured", "declared-unvalidated", "virtual-32gb-capacity-only"}
_REQUIRED_FIELDS = (
    "device_class",
    "model",
    "configuration",
    "format",
    "engine",
    "box",
    "status",
    "pins",
    "transcripts",
)

_ARM_VERBS = [
    "arm overview — describe the arm noun (this command)",
    "arm list [--root PATH] — list every setup/**/arm.toml under root",
    "arm show <path> — print one arm's manifest (dir or arm.toml path)",
]


def default_root() -> Path:
    """Repo root: the parent of this agent's own ``culture.yaml``, else cwd.

    Mirrors :func:`edge_ai_lab.cli._commands.whoami.find_culture_yaml` — walks
    up from this module's own file, not the caller's working directory, so
    the root is this checkout's root regardless of where ``lab`` is invoked
    from. Falls back to the current working directory (e.g. a wheel install
    with no ``culture.yaml`` alongside the package).
    """
    cfg = find_culture_yaml()
    return cfg.parent if cfg is not None else Path.cwd()


def _manifest_path(target: Path) -> Path:
    """Resolve an arm path (directory or manifest file) to its ``arm.toml``."""
    if target.is_dir():
        return target / "arm.toml"
    return target


def find_manifests(root: Path) -> list[Path]:
    """Every ``arm.toml`` under ``<root>/setup/``, sorted for stable output."""
    setup_dir = root / "setup"
    if not setup_dir.is_dir():
        return []
    return sorted(setup_dir.glob("**/arm.toml"))


def load_manifest(manifest_path: Path) -> dict[str, object]:
    """Parse and validate one ``arm.toml``. Raises :class:`CliError` on any problem."""
    if not manifest_path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no arm.toml found at {manifest_path}",
            remediation="pass an arm directory or an arm.toml path that exists on disk",
        )
    try:
        with manifest_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as err:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: invalid TOML ({err})",
            remediation="fix the TOML syntax and retry",
        ) from err

    for field in _REQUIRED_FIELDS:
        if field not in data:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"{manifest_path}: missing required field '{field}'",
                remediation=(
                    f"add '{field}' to {manifest_path} "
                    "(see docs/lab-conventions.md section 2 for the manifest schema)"
                ),
            )

    fmt = data["format"]
    if fmt not in _FORMATS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: invalid format '{fmt}'",
            remediation=f"format must be one of: {', '.join(sorted(_FORMATS))}",
        )

    status = data["status"]
    if status not in _STATUSES:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: invalid status '{status}'",
            remediation=f"status must be one of: {', '.join(sorted(_STATUSES))}",
        )

    if not isinstance(data["pins"], dict):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: 'pins' must be a table",
            remediation="add a [pins] table (see docs/lab-conventions.md section 2)",
        )

    if not isinstance(data["transcripts"], list):
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: 'transcripts' must be a list",
            remediation="set transcripts = [] or a list of docs/evidence/ paths",
        )

    return data


def _arm_sections() -> list[dict[str, object]]:
    return [
        {"title": "Verbs", "items": list(_ARM_VERBS)},
        {
            "title": "Manifest (arm.toml) schema",
            "items": [
                f"required fields: {', '.join(_REQUIRED_FIELDS)}",
                f"format: {', '.join(sorted(_FORMATS))}",
                f"status: {', '.join(sorted(_STATUSES))}",
                "path scheme: setup/<device-class>/<model>/<configuration>/",
            ],
        },
        {
            "title": "See also",
            "items": ["docs/lab-conventions.md — sections 1 and 2 define this contract"],
        },
    ]


def cmd_arm_overview(args: argparse.Namespace) -> int:
    emit_overview(
        "edge-ai-lab arm",
        _arm_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )
    return 0


def _no_verb(args: argparse.Namespace) -> int:
    # `edge-ai-lab arm` with no sub-verb prints the noun's overview.
    return cmd_arm_overview(args)


def cmd_arm_list(args: argparse.Namespace) -> int:
    root_arg = getattr(args, "root", None)
    root = Path(root_arg).resolve() if root_arg else default_root()
    json_mode = bool(getattr(args, "json", False))

    rows: list[dict[str, object]] = []
    for manifest_path in find_manifests(root):
        try:
            data = load_manifest(manifest_path)
        except CliError as err:
            emit_diagnostic(f"skipping {manifest_path}: {err.message}")
            continue
        rows.append(
            {
                "device_class": data["device_class"],
                "model": data["model"],
                "configuration": data["configuration"],
                "format": data["format"],
                "status": data["status"],
                "path": str(manifest_path),
            }
        )

    if json_mode:
        emit_result(rows, json_mode=True)
        return 0

    if not rows:
        emit_result(f"no arms found under {root / 'setup'}", json_mode=False)
        return 0

    lines = [
        f"{r['device_class']}/{r['model']}/{r['configuration']}"
        f"  format={r['format']}  status={r['status']}  {r['path']}"
        for r in rows
    ]
    emit_result("\n".join(lines), json_mode=False)
    return 0


def cmd_arm_show(args: argparse.Namespace) -> int:
    manifest_path = _manifest_path(Path(args.path))
    data = load_manifest(manifest_path)
    json_mode = bool(getattr(args, "json", False))

    if json_mode:
        emit_result(data, json_mode=True)
        return 0

    lines = [
        f"device_class: {data['device_class']}",
        f"model: {data['model']}",
        f"configuration: {data['configuration']}",
        f"format: {data['format']}",
        f"engine: {data['engine']}",
        f"box: {data['box']}",
        f"status: {data['status']}",
        "pins:",
    ]
    pins = data["pins"]
    assert isinstance(pins, dict)
    for key, value in pins.items():
        lines.append(f"  {key}: {value}")
    lines.append("transcripts:")
    transcripts = data["transcripts"]
    assert isinstance(transcripts, list)
    if transcripts:
        for transcript in transcripts:
            lines.append(f"  {transcript}")
    else:
        lines.append("  (none)")
    emit_result("\n".join(lines), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "arm",
        help="Experiment arms under setup/**/arm.toml (see 'edge-ai-lab arm overview').",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=_no_verb, json=False)
    # `p` is a _CliArgumentParser (top-level subparsers use that parser_class);
    # propagate it so every arm sub-verb's parse errors route through the
    # structured error contract instead of argparse's default stderr/exit 2.
    arm_sub = p.add_subparsers(dest="arm_command", parser_class=type(p))

    ov = arm_sub.add_parser("overview", help="Describe the arm noun.")
    ov.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ov.set_defaults(func=cmd_arm_overview)

    ls = arm_sub.add_parser("list", help="List every setup/**/arm.toml under root.")
    ls.add_argument(
        "--root",
        help="Root directory to search under (default: this checkout's repo root).",
    )
    ls.add_argument("--json", action="store_true", help="Emit structured JSON.")
    ls.set_defaults(func=cmd_arm_list)

    sh = arm_sub.add_parser("show", help="Print one arm's manifest.")
    sh.add_argument("path", help="Arm directory or arm.toml path.")
    sh.add_argument("--json", action="store_true", help="Emit structured JSON.")
    sh.set_defaults(func=cmd_arm_show)

    for name in _VERB_MODULES:
        try:
            module = importlib.import_module(f"edge_ai_lab.cli._commands.{name}")
        except ModuleNotFoundError:
            continue
        module.register(arm_sub)
