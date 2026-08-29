"""``lab arm`` — noun group over experiment arms under ``setup/**/arm.toml``.

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
import re
import tomllib
from pathlib import Path

from edge_ai_lab.cli._commands.overview import emit_overview
from edge_ai_lab.cli._commands.whoami import find_culture_yaml
from edge_ai_lab.cli._errors import EXIT_USER_ERROR, CliError
from edge_ai_lab.cli._output import emit_diagnostic, emit_result

# Later tasks add their module here and nowhere else in this file.
_VERB_MODULES = ("arm_validate", "arm_run", "arm_export")

# Shared across every `--json` flag registered in this module (S1192).
_JSON_HELP = "Emit structured JSON."

# The `arm.toml` schema (docs/lab-conventions.md sections 1 and 2). Every
# vocabulary below is *closed*: a value outside it needs a rulebook edit (and,
# for `engine`, a lobes-cli issue first) rather than a manifest that quietly
# means something the CLI cannot act on.
_FORMATS = {"sparkrun-recipe", "lobes-override"}
_STATUSES = {"measured", "declared-unvalidated", "virtual-32gb-capacity-only"}
_DEVICE_CLASSES = {
    "spark",
    "thor",
    "orin-agx-64",
    "orin-agx-32-virtual",
    "orin-nx-16",
    "orin-nano-8",
}
_ENGINES = {"vllm", "llama.cpp", "sglang"}
_BOXES = {"spark", "thor", "orin", "nano", "nx"}

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

# Fields that must be plain TOML strings.
_STRING_FIELDS = (
    "device_class",
    "model",
    "configuration",
    "format",
    "engine",
    "box",
    "status",
)

# Checked in this order so the narrower `format`/`status` errors keep naming
# themselves first, as they did before the vocabularies were closed.
_ENUM_FIELDS: tuple[tuple[str, set[str]], ...] = (
    ("format", _FORMATS),
    ("status", _STATUSES),
    ("device_class", _DEVICE_CLASSES),
    ("engine", _ENGINES),
    ("box", _BOXES),
)

# The `<model>` path segment is a lowercase slug (the model id itself is a
# Hugging Face id with a `/` and mixed case, so it is never compared to it).
_SLUG_RE = re.compile(r"^[a-z0-9.-]+$")

_SCHEMA_DOC = "docs/lab-conventions.md section 2"
_PATH_SCHEME_DOC = "docs/lab-conventions.md section 1"

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


def _manifest_error(manifest_path: Path, message: str, remediation: str) -> CliError:
    """One CliError shape for every manifest problem: ``<path>: <what>``."""
    return CliError(
        code=EXIT_USER_ERROR,
        message=f"{manifest_path}: {message}",
        remediation=remediation,
    )


def _parse_toml(manifest_path: Path) -> dict[str, object]:
    if not manifest_path.is_file():
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"no arm.toml found at {manifest_path}",
            remediation="pass an arm directory or an arm.toml path that exists on disk",
        )
    try:
        with manifest_path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as err:
        raise _manifest_error(
            manifest_path, f"invalid TOML ({err})", "fix the TOML syntax and retry"
        ) from err


def _check_required(manifest_path: Path, data: dict[str, object]) -> None:
    for field in _REQUIRED_FIELDS:
        if field not in data:
            raise _manifest_error(
                manifest_path,
                f"missing required field '{field}'",
                f"add '{field}' to {manifest_path} (see {_SCHEMA_DOC} for the manifest schema)",
            )


def _check_scalar_types(manifest_path: Path, data: dict[str, object]) -> None:
    """String fields are strings, ``transcripts`` a list of strings, ``pins`` a
    table of strings — so no consumer has to defend against a TOML integer."""
    for field in _STRING_FIELDS:
        if not isinstance(data[field], str):
            raise _manifest_error(
                manifest_path,
                f"'{field}' must be a string, not {type(data[field]).__name__}",
                f"quote the value of '{field}' (see {_SCHEMA_DOC})",
            )

    pins = data["pins"]
    if not isinstance(pins, dict):
        raise _manifest_error(
            manifest_path, "'pins' must be a table", f"add a [pins] table (see {_SCHEMA_DOC})"
        )
    for key, value in pins.items():
        if not isinstance(value, str):
            raise _manifest_error(
                manifest_path,
                f"pin '{key}' must be a string, not {type(value).__name__}",
                f"quote every value in the [pins] table (see {_SCHEMA_DOC})",
            )

    transcripts = data["transcripts"]
    if not isinstance(transcripts, list):
        raise _manifest_error(
            manifest_path,
            "'transcripts' must be a list",
            "set transcripts = [] or a list of docs/evidence/ paths",
        )
    for entry in transcripts:
        if not isinstance(entry, str):
            raise _manifest_error(
                manifest_path,
                f"transcript entries must be strings, not {type(entry).__name__}",
                "list transcripts as quoted docs/evidence/ paths",
            )


def _check_vocabularies(manifest_path: Path, data: dict[str, object]) -> None:
    for field, allowed in _ENUM_FIELDS:
        value = data[field]
        if value not in allowed:
            raise _manifest_error(
                manifest_path,
                f"invalid {field} '{value}'",
                f"{field} must be one of: {', '.join(sorted(allowed))}",
            )


def _check_path_identity(manifest_path: Path, data: dict[str, object]) -> None:
    """``setup/<a>/<b>/<c>/arm.toml`` must agree with the manifest it holds.

    ``<a>`` is the device class and ``<c>`` the configuration; ``<b>`` is only
    required to be a lowercase slug — the ``model`` field is a Hugging Face id
    (``Org/Name``), so it is deliberately *not* compared to the segment.
    Manifests outside a ``setup/`` tree (ad-hoc paths, wheel installs) are
    skipped: there is no path scheme to check them against.
    """
    arm_dir = manifest_path.resolve().parent
    model_dir = arm_dir.parent
    device_dir = model_dir.parent
    if device_dir.parent.name != "setup":
        return

    expectations = (
        ("device_class", data["device_class"], device_dir.name),
        ("configuration", data["configuration"], arm_dir.name),
    )
    for field, value, segment in expectations:
        if value != segment:
            raise _manifest_error(
                manifest_path,
                f"'{field}' is '{value}' but its path segment is '{segment}'",
                f"rename the directory or the field so they agree (see {_PATH_SCHEME_DOC})",
            )

    if not _SLUG_RE.match(model_dir.name):
        raise _manifest_error(
            manifest_path,
            f"model path segment '{model_dir.name}' is not a lowercase slug",
            f"use only [a-z0-9.-] in the <model> path segment (see {_PATH_SCHEME_DOC})",
        )


def load_manifest(manifest_path: Path) -> dict[str, object]:
    """Parse and validate one ``arm.toml``. Raises :class:`CliError` on any problem."""
    data = _parse_toml(manifest_path)
    _check_required(manifest_path, data)
    _check_scalar_types(manifest_path, data)
    _check_vocabularies(manifest_path, data)
    _check_path_identity(manifest_path, data)
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
                f"device_class: {', '.join(sorted(_DEVICE_CLASSES))}",
                f"engine: {', '.join(sorted(_ENGINES))}",
                f"box: {', '.join(sorted(_BOXES))}",
                "path scheme: setup/<device-class>/<model>/<configuration>/ — "
                "device_class and configuration must equal their path segments",
            ],
        },
        {
            "title": "See also",
            "items": ["docs/lab-conventions.md — sections 1 and 2 define this contract"],
        },
    ]


def cmd_arm_overview(args: argparse.Namespace) -> None:
    # Handler contract (cli/__init__.py::_dispatch): success is `None` (exit
    # 0 by default); failures raise CliError. No branch here needs a
    # different exit code, so there is nothing to vary a return value on.
    emit_overview(
        "lab arm",
        _arm_sections(),
        json_mode=bool(getattr(args, "json", False)),
    )


def _no_verb(args: argparse.Namespace) -> None:
    # `lab arm` with no sub-verb prints the noun's overview.
    cmd_arm_overview(args)


def cmd_arm_list(args: argparse.Namespace) -> None:
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
        return

    if not rows:
        emit_result(f"no arms found under {root / 'setup'}", json_mode=False)
        return

    lines = [
        f"{r['device_class']}/{r['model']}/{r['configuration']}"
        f"  format={r['format']}  status={r['status']}  {r['path']}"
        for r in rows
    ]
    emit_result("\n".join(lines), json_mode=False)


def cmd_arm_show(args: argparse.Namespace) -> None:
    manifest_path = _manifest_path(Path(args.path))
    data = load_manifest(manifest_path)
    json_mode = bool(getattr(args, "json", False))

    if json_mode:
        emit_result(data, json_mode=True)
        return

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


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "arm",
        help="Experiment arms under setup/**/arm.toml (see 'lab arm overview').",
    )
    p.add_argument("--json", action="store_true", help=_JSON_HELP)
    p.set_defaults(func=_no_verb, json=False)
    # `p` is a _CliArgumentParser (top-level subparsers use that parser_class);
    # propagate it so every arm sub-verb's parse errors route through the
    # structured error contract instead of argparse's default stderr/exit 2.
    arm_sub = p.add_subparsers(dest="arm_command", parser_class=type(p))

    ov = arm_sub.add_parser("overview", help="Describe the arm noun.")
    ov.add_argument("--json", action="store_true", help=_JSON_HELP)
    ov.set_defaults(func=cmd_arm_overview)

    ls = arm_sub.add_parser("list", help="List every setup/**/arm.toml under root.")
    ls.add_argument(
        "--root",
        help="Root directory to search under (default: this checkout's repo root).",
    )
    ls.add_argument("--json", action="store_true", help=_JSON_HELP)
    ls.set_defaults(func=cmd_arm_list)

    sh = arm_sub.add_parser("show", help="Print one arm's manifest.")
    sh.add_argument("path", help="Arm directory or arm.toml path.")
    sh.add_argument("--json", action="store_true", help=_JSON_HELP)
    sh.set_defaults(func=cmd_arm_show)

    for name in _VERB_MODULES:
        try:
            module = importlib.import_module(f"edge_ai_lab.cli._commands.{name}")
        except ModuleNotFoundError:
            continue
        module.register(arm_sub)
