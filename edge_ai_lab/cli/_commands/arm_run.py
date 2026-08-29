"""``edge-ai-lab arm run <path>`` — the box-side experiment wrapper.

Runs one arm on the box it names, following ``docs/lab-conventions.md``
sections 3 (evidence), 4 (shared-box budget), 5 (pins), 8 (telemetry) and 10
(sparkrun via uvx only). Stdlib only — no third-party imports, everything is
shelled out to ``subprocess``/``urllib``. This module is a plug-in registered
by ``edge_ai_lab/cli/_commands/arm.py`` (see that module's docstring for the
plug-in contract): it reuses ``arm.py``'s manifest resolution/loading instead
of re-parsing ``arm.toml``.

What one run does, in order:

1. Resolve the manifest and an optional ``[run]`` table (``recipe`` for a
   ``sparkrun-recipe`` arm, ``commands`` for a ``lobes-override`` arm,
   ``gateway_url`` defaulting to ``http://127.0.0.1:8001``, ``port`` — which
   must not be 8000 or 8001, the fleet's own ports).
2. Refuse if a box marker already exists (section 4, rule 5: one arm per box
   at a time) — the ``CliError`` remediation names the running arm's path so
   the ``hint:`` line an agent reads is actionable. The marker is written
   before the launch and removed in a ``finally:`` and a ``SIGTERM`` handler,
   so an abnormal exit still clears it.
3. Capture a best-effort "before" snapshot: ``docker ps``, ``docker system
   df``, ``df -h /``, ``nvpmodel -q``, GPU devfreq frequencies, ``free -g``,
   thermal-zone temperatures. A missing tool records ``"unavailable"``
   instead of failing the run.
4. Launch: ``uvx sparkrun==<pins.sparkrun_version> run <recipe>`` with
   ``SPARKRUN_NO_TELEMETRY=1`` (section 8), or each ``[run].commands`` entry
   for a lobes-override arm. ``--dry-run`` performs everything except this
   step and reports the argv/env it would have used.
5. Capture the "after" snapshot the same way, then probe the gateway's
   ``GET /capabilities`` (section 4, rule 4) — a non-200 reply is recorded
   and printed as a warning, never raised as a failure.
6. Write a transcript skeleton under ``docs/evidence/`` (section 3 naming),
   never overwriting an existing file, with a ``## measurements`` section
   whose value lines are left empty — a run never fabricates a number.

Wired in through the plug-in contract in ``arm.py`` (``_VERB_MODULES``).
"""

from __future__ import annotations

import argparse
import atexit
import json as jsonlib
import os
import re
import shlex
import shutil
import signal
import subprocess  # nosec B404 - fixed manifest-pinned/declared argv, never shell=True
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge_ai_lab.cli._commands import arm as _arm
from edge_ai_lab.cli._errors import EXIT_USER_ERROR, CliError
from edge_ai_lab.cli._output import emit_diagnostic, emit_result

_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
_FORBIDDEN_PORTS = {8000, 8001}
_MARKER_NAME = "arm.lock"
_CAPTURE_TIMEOUT = 30
_GATEWAY_TIMEOUT = 5
_LOG_CAP_LINES = 50
_DEVFREQ_GPU = Path("/sys/class/devfreq/17000000.gpu")
_THERMAL_ROOT = Path("/sys/class/thermal")


# --- deploy dir / marker -----------------------------------------------------


def _default_deploy_dir() -> Path:
    env = os.environ.get("LAB_DEPLOY_DIR")
    if env:
        return Path(env)
    return Path.home() / ".edge-ai-lab"


def _guard_not_lobes(deploy_dir: Path) -> None:
    """Refuse a deploy dir that resolves inside ``~/.lobes`` (never touch the fleet)."""
    lobes_dir = (Path.home() / ".lobes").resolve()
    resolved = deploy_dir.resolve()
    if resolved == lobes_dir or lobes_dir in resolved.parents:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"--deploy-dir {resolved} resolves inside ~/.lobes",
            remediation="pass a --deploy-dir outside ~/.lobes — arm run never writes fleet files",
        )


def _find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the nearest ``pyproject.toml``/``culture.yaml``.

    Mirrors :func:`edge_ai_lab.cli._commands.arm_validate._find_repo_root` —
    duplicated rather than imported so a fixture arm under ``tmp_path`` (which
    has its own ``pyproject.toml`` but is not this package's own checkout)
    resolves to *its own* root, never to the real checkout this package
    happens to be installed from.
    """
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / "culture.yaml").is_file():
            return candidate
    return current


def _marker_path(deploy_dir: Path) -> Path:
    return deploy_dir / _MARKER_NAME


def _read_marker(marker_path: Path) -> dict[str, Any] | None:
    if not marker_path.is_file():
        return None
    try:
        data = jsonlib.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, jsonlib.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_marker(marker_path: Path, arm_path: Path) -> None:
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "arm_path": str(arm_path),
        "pid": os.getpid(),
        "started": datetime.now(timezone.utc).isoformat(),
    }
    marker_path.write_text(jsonlib.dumps(payload), encoding="utf-8")


def _remove_marker(marker_path: Path) -> None:
    try:
        marker_path.unlink()
    except (FileNotFoundError, OSError):
        pass


# --- best-effort capture -----------------------------------------------------


def _run_capture(argv: list[str]) -> str:
    if shutil.which(argv[0]) is None:
        return "unavailable (not on PATH)"
    try:
        proc = subprocess.run(  # nosec B603 - fixed, hard-coded argv, no shell
            argv, capture_output=True, timeout=_CAPTURE_TIMEOUT, text=True, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable ({exc})"
    output = proc.stdout or ""
    if proc.returncode != 0:
        output = (output + (proc.stderr or "")).strip()
        if not output:
            return f"unavailable (exit {proc.returncode})"
    return output.strip() or "(empty)"


def _read_sysfs(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _devfreq_snapshot() -> str:
    if not _DEVFREQ_GPU.is_dir():
        return "unavailable"
    parts = []
    for name in ("cur_freq", "min_freq", "max_freq"):
        value = _read_sysfs(_DEVFREQ_GPU / name)
        parts.append(f"{name}={value if value is not None else 'unavailable'}")
    return " ".join(parts)


def _thermal_snapshot() -> str:
    if not _THERMAL_ROOT.is_dir():
        return "unavailable"
    zones = sorted(_THERMAL_ROOT.glob("thermal_zone*/temp"))
    if not zones:
        return "unavailable"
    parts = []
    for zone in zones:
        value = _read_sysfs(zone)
        parts.append(f"{zone.parent.name}={value if value is not None else 'unavailable'}")
    return " ".join(parts)


def _capture_state() -> dict[str, str]:
    return {
        "docker ps": _run_capture(["docker", "ps", "--format", "{{.Names}}\t{{.Image}}"]),
        "docker system df": _run_capture(["docker", "system", "df"]),
        "df -h /": _run_capture(["df", "-h", "/"]),
        "nvpmodel -q": _run_capture(["nvpmodel", "-q"]),
        "devfreq gpu (cur/min/max)": _devfreq_snapshot(),
        "free -g": _run_capture(["free", "-g"]),
        "thermals": _thermal_snapshot(),
    }


def _render_capture(state: dict[str, str]) -> str:
    return "\n\n".join(f"{label}:\n{value}" for label, value in state.items())


# --- launch -------------------------------------------------------------------


def _build_launch(
    data: dict[str, Any], run_table: dict[str, Any], manifest_path: Path
) -> tuple[list[list[str]], dict[str, str]]:
    env_additions = {"SPARKRUN_NO_TELEMETRY": "1"}
    fmt = data["format"]

    if fmt == "sparkrun-recipe":
        pins = data["pins"]
        sparkrun_version = pins.get("sparkrun_version") if isinstance(pins, dict) else None
        if not sparkrun_version:
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"{manifest_path}: [pins].sparkrun_version is required to launch",
                remediation=(
                    "add sparkrun_version to [pins] in arm.toml "
                    "(docs/lab-conventions.md section 5)"
                ),
            )
        recipe = run_table.get("recipe") or "recipe.yaml"
        recipe_path = manifest_path.parent / str(recipe)
        argv = ["uvx", f"sparkrun=={sparkrun_version}", "run", str(recipe_path)]
        return [argv], env_additions

    if fmt == "lobes-override":
        commands = run_table.get("commands")
        if not commands or not isinstance(commands, list):
            raise CliError(
                code=EXIT_USER_ERROR,
                message=f"{manifest_path}: [run].commands is required for a lobes-override arm",
                remediation='add commands = ["..."] under [run] in arm.toml',
            )
        return [shlex.split(str(cmd)) for cmd in commands], env_additions

    raise CliError(
        code=EXIT_USER_ERROR,
        message=f"{manifest_path}: don't know how to launch format '{fmt}'",
        remediation=f"format must be one of: {', '.join(sorted(_arm._FORMATS))}",
    )


def _execute(
    argv_steps: list[list[str]], env_additions: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    env = dict(os.environ)
    env.update(env_additions)
    results: list[dict[str, Any]] = []
    exit_code = 0
    for argv in argv_steps:
        if shutil.which(argv[0]) is None:
            results.append(
                {"argv": argv, "exit_code": 127, "stdout": "", "stderr": f"{argv[0]}: not found"}
            )
            exit_code = 127
            break
        try:
            proc = subprocess.run(  # nosec B603 - argv built only from pinned/manifest fields
                argv, capture_output=True, text=True, env=env, check=False
            )
        except OSError as exc:
            results.append({"argv": argv, "exit_code": 1, "stdout": "", "stderr": str(exc)})
            exit_code = 1
            break
        results.append(
            {
                "argv": argv,
                "exit_code": proc.returncode,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
            }
        )
        if proc.returncode != 0:
            exit_code = proc.returncode
            break
    return results, exit_code


def _cap_lines(text: str, n: int = _LOG_CAP_LINES) -> str:
    lines = text.splitlines()
    return "\n".join(lines[:n])


def _render_launch(results: list[dict[str, Any]], dry_run: bool) -> str:
    if dry_run:
        return "dry-run — not launched"
    if not results:
        return "(no launch steps)"
    blocks = []
    for step in results:
        blocks.append(
            "argv: {argv}\nexit_code: {exit_code}\nstdout (first {n} lines):\n{stdout}\n"
            "stderr (first {n} lines):\n{stderr}".format(
                argv=shlex.join(step["argv"]),
                exit_code=step["exit_code"],
                n=_LOG_CAP_LINES,
                stdout=_cap_lines(step["stdout"]) or "(empty)",
                stderr=_cap_lines(step["stderr"]) or "(empty)",
            )
        )
    return "\n\n".join(blocks)


# --- gateway probe -------------------------------------------------------------


def _probe_gateway(gateway_url: str) -> tuple[int | None, str | None]:
    url = gateway_url.rstrip("/") + "/capabilities"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(
            req, timeout=_GATEWAY_TIMEOUT
        ) as resp:  # nosec B310 - fixed http(s) gateway_url from the arm manifest, GET only
            return resp.status, None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(exc)


# --- transcript -----------------------------------------------------------------


def _model_slug(model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(model).lower()).strip("-")
    return slug or "model"


def _transcript_path(root: Path, model: str, box: str, today: str | None = None) -> Path:
    date = today or datetime.now(timezone.utc).date().isoformat()
    base = f"{date}-spike-{_model_slug(model)}-{box}"
    evidence_dir = root / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    candidate = evidence_dir / f"{base}.txt"
    suffix = 2
    while candidate.exists():
        candidate = evidence_dir / f"{base}-{suffix}.txt"
        suffix += 1
    return candidate


def _render_transcript(
    *,
    manifest_path: Path,
    data: dict[str, Any],
    run_table: dict[str, Any],
    dry_run: bool,
    before: dict[str, str],
    after: dict[str, str],
    launch_results: list[dict[str, Any]],
    launch_exit_code: int | None,
    gateway_url: str,
    gateway_status: int | None,
    gateway_error: str | None,
) -> str:
    pins = data.get("pins") if isinstance(data.get("pins"), dict) else {}
    header_lines = [
        f"arm: {manifest_path.parent}",
        f"manifest: {manifest_path}",
        f"device_class: {data.get('device_class')}",
        f"model: {data.get('model')}",
        f"configuration: {data.get('configuration')}",
        f"format: {data.get('format')}",
        f"engine: {data.get('engine')}",
        f"box: {data.get('box')}",
        f"status: {data.get('status')}",
        "pins:",
    ]
    for key, value in pins.items():
        header_lines.append(f"  {key}: {value}")
    header_lines.append(f"[run]: {run_table}")
    header_lines.append(f"dry_run: {dry_run}")

    gateway_line = (
        f"GET {gateway_url.rstrip('/')}/capabilities -> {gateway_status}"
        if gateway_status is not None
        else f"GET {gateway_url.rstrip('/')}/capabilities -> error: {gateway_error}"
    )

    sections = [
        "\n".join(header_lines),
        "## before\n\n" + _render_capture(before),
        "## launch\n\n"
        + _render_launch(launch_results, dry_run)
        + f"\n\nlaunch_exit_code: {launch_exit_code}",
        "## after\n\n" + _render_capture(after),
        "## gateway probe\n\n" + gateway_line,
        "## measurements\n\n"
        "decode tok/s (usage.completion_tokens) - short:\n"
        "decode tok/s (usage.completion_tokens) - medium:\n"
        "decode tok/s (usage.completion_tokens) - long:\n"
        "TTFT:\n"
        "prompt_tokens:\n"
        "power mode / clocks:\n"
        "concurrency ceiling / measured saturation:\n",
    ]
    return "\n\n".join(sections) + "\n"


# --- command -------------------------------------------------------------------


def cmd_arm_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))

    manifest_path = _arm._manifest_path(Path(args.path))
    data = _arm.load_manifest(manifest_path)

    deploy_dir_arg = getattr(args, "deploy_dir", None)
    deploy_dir = (
        Path(deploy_dir_arg).expanduser().resolve()
        if deploy_dir_arg
        else _default_deploy_dir().expanduser().resolve()
    )
    _guard_not_lobes(deploy_dir)

    run_table = data.get("run") if isinstance(data.get("run"), dict) else {}

    port = run_table.get("port")
    if port in _FORBIDDEN_PORTS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: [run].port {port} is reserved for the fleet",
            remediation="bind a port other than 8000/8001 (docs/lab-conventions.md section 4)",
        )
    gateway_url = str(run_table.get("gateway_url") or _DEFAULT_GATEWAY_URL)

    marker_path = _marker_path(deploy_dir)
    existing = _read_marker(marker_path)
    if existing is not None:
        raise CliError(
            code=EXIT_USER_ERROR,
            message="an arm is already running on this box",
            remediation=(
                f"arm {existing.get('arm_path', 'unknown')} is running (marker {marker_path}) "
                "— wait for it to finish, or remove the marker if it crashed without cleanup"
            ),
        )

    argv_steps, env_additions = _build_launch(data, run_table, manifest_path)

    before = _capture_state()

    _write_marker(marker_path, manifest_path.parent)

    def _sigterm_handler(signum: int, _frame: object) -> None:
        _remove_marker(marker_path)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    previous_handler = signal.signal(signal.SIGTERM, _sigterm_handler)
    atexit.register(_remove_marker, marker_path)

    launch_results: list[dict[str, Any]] = []
    launch_exit_code: int | None = None
    try:
        if not dry_run:
            launch_results, launch_exit_code = _execute(argv_steps, env_additions)
    finally:
        _remove_marker(marker_path)
        signal.signal(signal.SIGTERM, previous_handler)

    after = _capture_state()
    gateway_status, gateway_error = _probe_gateway(gateway_url)
    if gateway_status != 200:
        emit_diagnostic(
            f"warning: gateway probe to {gateway_url.rstrip('/')}/capabilities "
            f"did not return 200 (status={gateway_status}, error={gateway_error})"
        )

    root = _find_repo_root(manifest_path.parent)
    transcript_path = _transcript_path(root, str(data.get("model")), str(data.get("box")))
    transcript_path.write_text(
        _render_transcript(
            manifest_path=manifest_path,
            data=data,
            run_table=run_table,
            dry_run=dry_run,
            before=before,
            after=after,
            launch_results=launch_results,
            launch_exit_code=launch_exit_code,
            gateway_url=gateway_url,
            gateway_status=gateway_status,
            gateway_error=gateway_error,
        ),
        encoding="utf-8",
    )

    result: dict[str, Any] = {
        "transcript": str(transcript_path),
        "marker_cleared": not marker_path.exists(),
        "gateway_status": gateway_status,
        "launch_exit_code": launch_exit_code,
    }
    if dry_run:
        result["dry_run"] = True
        result["argv"] = argv_steps
        result["env"] = env_additions

    if json_mode:
        emit_result(result, json_mode=True)
    else:
        lines = [f"transcript: {transcript_path}"]
        if dry_run:
            for argv in argv_steps:
                lines.append(f"dry-run argv: {shlex.join(argv)}")
            lines.append(f"dry-run env additions: {env_additions}")
        emit_result("\n".join(lines), json_mode=False)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run",
        help="Run one arm: box marker, before/after capture, pinned launch, transcript.",
    )
    p.add_argument("path", help="Arm directory or arm.toml path.")
    p.add_argument(
        "--deploy-dir",
        dest="deploy_dir",
        help="Box marker/deploy directory (default: $LAB_DEPLOY_DIR or ~/.edge-ai-lab).",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Capture and write the marker/transcript but do not launch.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_arm_run)
