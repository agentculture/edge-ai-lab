"""``lab arm run <path>`` — the box-side experiment wrapper.

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
2. Take the **box-wide** lock (section 4, rule 5: one arm per box at a time).
   The lock path is deliberately independent of ``--deploy-dir`` so a second
   run cannot slip past the guard by naming a different deploy dir: it is
   ``$LAB_BOX_LOCK`` when set, else ``/var/tmp/edge-ai-lab/arm.lock``, else
   (when that directory is not writable) ``~/.edge-ai-lab/arm.lock`` — and the
   fallback is recorded in the transcript as a warning, because two runs
   whose fallbacks differ can no longer see each other. Acquisition is atomic
   (``O_CREAT|O_EXCL``); an existing lock is a refusal whose ``hint:`` names
   the running arm. A lock whose recorded pid is dead is reported as *stale*
   and still refused — the operator removes it, the tool never does.
   Release is owner-checked (only a lock whose pid is ours is unlinked).
3. Capture a best-effort "before" snapshot: ``docker ps``, ``docker system
   df``, ``df -h /``, ``nvpmodel -q``, GPU devfreq frequencies, ``free -g``,
   thermal-zone temperatures. A missing tool records ``"unavailable"``
   instead of failing the run.
4. Launch: ``uvx sparkrun==<pins.sparkrun_version> run <recipe>`` with
   ``SPARKRUN_NO_TELEMETRY=1`` (section 8), or each ``[run].commands`` entry
   for a lobes-override arm. The child is started in its **own session**
   (``start_new_session=True``) so a ``SIGTERM``/``SIGINT`` to this process
   can forward to the whole child process group rather than orphaning it.
   ``--dry-run`` performs everything except this step and reports the
   argv/env it would have used.
5. Capture the "after" snapshot the same way, then probe the gateway's
   ``GET /capabilities`` (section 4, rule 4) — a non-200 reply is recorded
   and printed as a warning, never raised as a failure. Steps 4-6 all run
   **inside the lock**: it is released only after the transcript is on disk.
6. Write a transcript skeleton under ``docs/evidence/`` (section 3 naming),
   never overwriting an existing file, with a ``## measurements`` section
   whose value lines are left empty — a run never fabricates a number.
   Alongside it, a sidecar directory of the same stem holds verbatim copies
   of the arm definition (``arm.toml`` plus the driving ``recipe.yaml`` /
   ``profile-override.toml``) and a ``run.json``, so the transcript is
   reproducible without re-deriving flags from a since-edited arm.

A non-zero launch exit is an **environment error**: the transcript is still
written and the lock still released, then the command exits 2.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edge_ai_lab.cli._commands import arm as _arm
from edge_ai_lab.cli._errors import EXIT_ENV_ERROR, EXIT_USER_ERROR, CliError
from edge_ai_lab.cli._output import emit_diagnostic, emit_result

_DEFAULT_GATEWAY_URL = "http://127.0.0.1:8001"
_FORBIDDEN_PORTS = {8000, 8001}
_MARKER_NAME = "arm.lock"
_BOX_LOCK_ENV = "LAB_BOX_LOCK"
# Box-wide default: one lock for the whole machine, independent of --deploy-dir.
_SYSTEM_LOCK_DIR = Path("/var/tmp/edge-ai-lab")  # nosec B108 - deliberate box-wide, per-box path
_CAPTURE_TIMEOUT = 30
_GATEWAY_TIMEOUT = 5
_CHILD_GRACE = 10
_LOG_CAP_LINES = 50
_DEVFREQ_GPU = Path("/sys/class/devfreq/17000000.gpu")
_THERMAL_ROOT = Path("/sys/class/thermal")
_EMPTY = "(empty)"
_UTF8 = "utf-8"
_RECIPE_DEFAULT = "recipe.yaml"
_OVERRIDE_DEFAULT = "profile-override.toml"
_K_ARGV = "argv"
_K_EXIT = "exit_code"
_K_STDOUT = "stdout"
_K_STDERR = "stderr"
_K_LAUNCH_EXIT = "launch_exit_code"
_K_ARM_PATH = "arm_path"
_CAPABILITIES = "/capabilities"

# Process-wide state the signal handler needs. Only one arm run per process.
_ACTIVE_LOCK: Path | None = None
_ACTIVE_CHILD: subprocess.Popen[str] | None = None


# --- deploy dir / box lock ---------------------------------------------------


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


def _resolve_lock_path() -> tuple[Path, str | None]:
    """Box-wide lock path plus an optional warning when the fallback was used.

    Deliberately ignores ``--deploy-dir``: the lock protects the *box*, and a
    per-deploy-dir lock would let a second run bypass the one-arm-at-a-time
    rule simply by naming another directory.
    """
    env = os.environ.get(_BOX_LOCK_ENV)
    if env:
        return Path(env).expanduser(), None
    reason = ""
    try:
        os.makedirs(_SYSTEM_LOCK_DIR, exist_ok=True)
    except OSError as exc:
        reason = f"could not create it ({exc})"
    if not reason and os.access(_SYSTEM_LOCK_DIR, os.W_OK):
        return _SYSTEM_LOCK_DIR / _MARKER_NAME, None
    reason = reason or "it is not writable"
    fallback = Path.home() / ".edge-ai-lab" / _MARKER_NAME
    warning = (
        f"box lock fell back to {fallback} because {_SYSTEM_LOCK_DIR} is unusable: {reason}. "
        "A concurrent arm holding the system lock will NOT be seen by this run."
    )
    return fallback, warning


def _read_marker(marker_path: Path) -> dict[str, Any] | None:
    try:
        data = jsonlib.loads(marker_path.read_text(encoding=_UTF8))
    except (OSError, jsonlib.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _pid_alive(pid: int) -> bool:
    """True unless the pid is provably gone (a pid we may not signal counts as live)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _busy_error(marker_path: Path) -> CliError:
    existing = _read_marker(marker_path) or {}
    arm_path = existing.get(_K_ARM_PATH, "unknown")
    pid = existing.get("pid")
    if isinstance(pid, int) and not _pid_alive(pid):
        return CliError(
            code=EXIT_USER_ERROR,
            message=f"a stale box lock is present (pid {pid} of arm {arm_path} is not running)",
            remediation=(
                f"arm {arm_path} crashed without cleanup — remove {marker_path} and retry "
                "(arm run never deletes another run's lock for you)"
            ),
        )
    return CliError(
        code=EXIT_USER_ERROR,
        message="an arm is already running on this box",
        remediation=(
            f"arm {arm_path} is running (pid {pid}, lock {marker_path}) "
            "— wait for it to finish before starting another arm"
        ),
    )


def _acquire_marker(marker_path: Path, arm_path: Path, started: str) -> None:
    """Create the lock atomically, or raise the refusal describing its owner."""
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {_K_ARM_PATH: str(arm_path), "pid": os.getpid(), "started": started}
    try:
        fd = os.open(marker_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError as exc:
        raise _busy_error(marker_path) from exc
    except OSError as exc:
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"cannot create the box lock {marker_path}: {exc}",
            remediation=f"make {marker_path.parent} writable, or set {_BOX_LOCK_ENV} to a path"
            " this user can write",
        ) from exc
    with os.fdopen(fd, "w", encoding=_UTF8) as fh:
        fh.write(jsonlib.dumps(payload))


def _release_marker(marker_path: Path) -> None:
    """Remove the lock only if *we* own it (its recorded pid is this process)."""
    data = _read_marker(marker_path)
    if data is None or data.get("pid") != os.getpid():
        return
    try:
        marker_path.unlink()
    except OSError:
        pass


# --- signals -------------------------------------------------------------------


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except OSError:
        pass


def _stop_child(child: subprocess.Popen[str]) -> None:
    """SIGTERM the child's process group, then SIGKILL it if it outlives the grace."""
    try:
        pgid = os.getpgid(child.pid)
    except OSError:
        pgid = None
    if pgid is not None:
        _signal_group(pgid, signal.SIGTERM)
    else:
        child.terminate()
    try:
        child.wait(timeout=_CHILD_GRACE)
        return
    except subprocess.TimeoutExpired:
        pass
    if pgid is not None:
        _signal_group(pgid, signal.SIGKILL)
    else:
        child.kill()
    try:
        child.wait(timeout=_CHILD_GRACE)
    except subprocess.TimeoutExpired:
        pass


def _terminate(signum: int, _frame: object) -> None:
    """SIGTERM/SIGINT handler: stop the child, drop our lock, then exit.

    Module-level (rather than a closure) so tests can invoke it directly, and
    so :func:`_install_signal_handlers` is a seam a test can monkeypatch.
    """
    child = _ACTIVE_CHILD
    if child is not None:
        _stop_child(child)
    if _ACTIVE_LOCK is not None:
        _release_marker(_ACTIVE_LOCK)
    raise SystemExit(128 + signum)


def _install_signal_handlers() -> dict[int, Any]:
    previous: dict[int, Any] = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            previous[sig] = signal.signal(sig, _terminate)
        except (ValueError, OSError):  # not the main thread — nothing to install
            pass
    return previous


def _restore_signal_handlers(previous: dict[int, Any]) -> None:
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
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
    return output.strip() or _EMPTY


def _read_sysfs(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding=_UTF8).strip()
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


def _pins(data: dict[str, Any]) -> dict[str, Any]:
    pins = data.get("pins")
    return pins if isinstance(pins, dict) else {}


def _sparkrun_version(data: dict[str, Any], manifest_path: Path) -> str:
    version = _pins(data).get("sparkrun_version")
    if not version:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: [pins].sparkrun_version is required to launch",
            remediation=(
                "add sparkrun_version to [pins] in arm.toml (docs/lab-conventions.md section 5)"
            ),
        )
    return str(version)


def _build_launch(
    data: dict[str, Any], run_table: dict[str, Any], manifest_path: Path
) -> tuple[list[list[str]], dict[str, str]]:
    env_additions = {"SPARKRUN_NO_TELEMETRY": "1"}
    fmt = data["format"]

    if fmt == "sparkrun-recipe":
        version = _sparkrun_version(data, manifest_path)
        recipe = run_table.get("recipe") or _RECIPE_DEFAULT
        recipe_path = manifest_path.parent / str(recipe)
        argv = ["uvx", f"sparkrun=={version}", "run", str(recipe_path)]
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


def _execute_one(argv: list[str], env: dict[str, str]) -> dict[str, Any]:
    global _ACTIVE_CHILD  # noqa: PLW0603 - the signal handler needs the live child

    if shutil.which(argv[0]) is None:
        return {_K_ARGV: argv, _K_EXIT: 127, _K_STDOUT: "", _K_STDERR: f"{argv[0]}: not found"}
    try:
        # start_new_session: own process group, so a SIGTERM to us can be
        # forwarded to the whole child tree instead of orphaning it.
        child = subprocess.Popen(  # nosec B603 - argv built only from pinned/manifest fields
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        return {_K_ARGV: argv, _K_EXIT: 1, _K_STDOUT: "", _K_STDERR: str(exc)}
    _ACTIVE_CHILD = child
    try:
        out, err = child.communicate()
    finally:
        _ACTIVE_CHILD = None
    return {
        _K_ARGV: argv,
        _K_EXIT: child.returncode,
        _K_STDOUT: out or "",
        _K_STDERR: err or "",
    }


def _execute(
    argv_steps: list[list[str]], env_additions: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    env = dict(os.environ)
    env.update(env_additions)
    results: list[dict[str, Any]] = []
    exit_code = 0
    for argv in argv_steps:
        step = _execute_one(argv, env)
        results.append(step)
        if step[_K_EXIT] != 0:
            exit_code = int(step[_K_EXIT])
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
                argv=shlex.join(step[_K_ARGV]),
                exit_code=step[_K_EXIT],
                n=_LOG_CAP_LINES,
                stdout=_cap_lines(step[_K_STDOUT]) or _EMPTY,
                stderr=_cap_lines(step[_K_STDERR]) or _EMPTY,
            )
        )
    return "\n\n".join(blocks)


# --- gateway probe -------------------------------------------------------------


def _probe_gateway(gateway_url: str) -> tuple[int | None, str | None]:
    """``(status, None)`` for any HTTP reply — including 4xx/5xx — else ``(None, error)``."""
    url = gateway_url.rstrip("/") + _CAPABILITIES
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(
            req, timeout=_GATEWAY_TIMEOUT
        ) as resp:  # nosec B310 - fixed http(s) gateway_url from the arm manifest, GET only
            return resp.status, None
    except urllib.error.HTTPError as exc:
        # An error *response* still carries a status — record it, don't lose it.
        return exc.code, None
    except (OSError, ValueError) as exc:
        # Transport-level failure (URLError, DNS, refused, bad URL): no status.
        return None, str(exc)


# --- transcript + sidecar ---------------------------------------------------------


def _model_slug(model: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(model).lower()).strip("-")
    return slug or "model"


def _evidence_target(
    root: Path, model: str, box: str, today: str | None = None
) -> tuple[Path, Path]:
    """``(transcript.txt, sidecar_dir)`` sharing one stem; neither exists yet."""
    date = today or datetime.now(timezone.utc).date().isoformat()
    base = f"{date}-spike-{_model_slug(model)}-{box}"
    evidence_dir = root / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stem = base
    suffix = 2
    while (evidence_dir / f"{stem}.txt").exists() or (evidence_dir / stem).exists():
        stem = f"{base}-{suffix}"
        suffix += 1
    return evidence_dir / f"{stem}.txt", evidence_dir / stem


def _definition_name(data: dict[str, Any], run_table: dict[str, Any]) -> str:
    if data.get("format") == "sparkrun-recipe":
        return str(run_table.get("recipe") or _RECIPE_DEFAULT)
    return _OVERRIDE_DEFAULT


def _write_sidecar(sidecar_dir: Path, plan: _RunPlan, run_json: dict[str, Any]) -> list[str]:
    """Copy the arm definition verbatim next to the transcript; return the file names."""
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    arm_dir = plan.manifest_path.parent
    sources = [plan.manifest_path, arm_dir / _definition_name(plan.data, plan.run_table)]
    for source in sources:
        if not source.is_file():
            continue
        shutil.copyfile(source, sidecar_dir / source.name)
        names.append(source.name)
    (sidecar_dir / "run.json").write_text(
        jsonlib.dumps(run_json, indent=2, sort_keys=True) + "\n", encoding=_UTF8
    )
    names.append("run.json")
    return names


@dataclass
class _RunPlan:
    """Everything resolved before the lock is taken."""

    manifest_path: Path
    data: dict[str, Any]
    run_table: dict[str, Any]
    gateway_url: str
    argv_steps: list[list[str]]
    env_additions: dict[str, str]
    deploy_dir: Path
    lock_path: Path
    lock_warning: str | None
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class _RunOutcome:
    """Everything observed while the lock was held."""

    dry_run: bool
    before: dict[str, str]
    after: dict[str, str]
    launch_results: list[dict[str, Any]]
    launch_exit_code: int | None
    gateway_status: int | None
    gateway_error: str | None


def _header_lines(
    plan: _RunPlan, outcome: _RunOutcome, sidecar_dir: Path, names: list[str]
) -> list[str]:
    data = plan.data
    pins = _pins(data)
    lines = [
        f"arm: {plan.manifest_path.parent}",
        f"manifest: {plan.manifest_path}",
        f"device_class: {data.get('device_class')}",
        f"model: {data.get('model')}",
        f"configuration: {data.get('configuration')}",
        f"format: {data.get('format')}",
        f"engine: {data.get('engine')}",
        f"box: {data.get('box')}",
        f"status: {data.get('status')}",
        "pins:",
    ]
    lines.extend(f"  {key}: {value}" for key, value in pins.items())
    lines.append(f"[run]: {plan.run_table}")
    lines.append(f"dry_run: {outcome.dry_run}")
    lines.append(f"started: {plan.started}")
    lines.append(f"deploy_dir: {plan.deploy_dir}")
    lines.append(f"box lock: {plan.lock_path}")
    if plan.lock_warning:
        lines.append(f"warning: {plan.lock_warning}")
    lines.append(f"arm definition sidecar: {sidecar_dir}")
    lines.extend(f"  {sidecar_dir.name}/{name}" for name in names)
    return lines


def _render_transcript(
    plan: _RunPlan, outcome: _RunOutcome, sidecar_dir: Path, names: list[str]
) -> str:
    probe = f"GET {plan.gateway_url.rstrip('/')}{_CAPABILITIES} -> "
    gateway_line = (
        f"{probe}{outcome.gateway_status}"
        if outcome.gateway_status is not None
        else f"{probe}error: {outcome.gateway_error}"
    )
    sections = [
        "\n".join(_header_lines(plan, outcome, sidecar_dir, names)),
        "## before\n\n" + _render_capture(outcome.before),
        "## launch\n\n"
        + _render_launch(outcome.launch_results, outcome.dry_run)
        + f"\n\n{_K_LAUNCH_EXIT}: {outcome.launch_exit_code}",
        "## after\n\n" + _render_capture(outcome.after),
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


def _write_evidence(plan: _RunPlan, outcome: _RunOutcome) -> Path:
    root = _find_repo_root(plan.manifest_path.parent)
    transcript_path, sidecar_dir = _evidence_target(
        root, str(plan.data.get("model")), str(plan.data.get("box"))
    )
    run_json = {
        _K_ARM_PATH: str(plan.manifest_path.parent),
        "started": plan.started,
        "launch_argv": plan.argv_steps,
        _K_LAUNCH_EXIT: outcome.launch_exit_code,
        "sparkrun_version": _pins(plan.data).get("sparkrun_version"),
        "lock_path": str(plan.lock_path),
    }
    names = _write_sidecar(sidecar_dir, plan, run_json)
    transcript_path.write_text(
        _render_transcript(plan, outcome, sidecar_dir, names), encoding=_UTF8
    )
    return transcript_path


# --- command -------------------------------------------------------------------


def _resolve_deploy_dir(args: argparse.Namespace) -> Path:
    deploy_dir_arg = getattr(args, "deploy_dir", None)
    deploy_dir = (
        Path(deploy_dir_arg).expanduser().resolve()
        if deploy_dir_arg
        else _default_deploy_dir().expanduser().resolve()
    )
    _guard_not_lobes(deploy_dir)
    return deploy_dir


def _plan_run(args: argparse.Namespace) -> _RunPlan:
    manifest_path = _arm._manifest_path(Path(args.path))
    data = _arm.load_manifest(manifest_path)
    deploy_dir = _resolve_deploy_dir(args)

    run_table = data.get("run") if isinstance(data.get("run"), dict) else {}
    port = run_table.get("port")
    if port in _FORBIDDEN_PORTS:
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"{manifest_path}: [run].port {port} is reserved for the fleet",
            remediation="bind a port other than 8000/8001 (docs/lab-conventions.md section 4)",
        )

    argv_steps, env_additions = _build_launch(data, run_table, manifest_path)
    lock_path, lock_warning = _resolve_lock_path()
    return _RunPlan(
        manifest_path=manifest_path,
        data=data,
        run_table=run_table,
        gateway_url=str(run_table.get("gateway_url") or _DEFAULT_GATEWAY_URL),
        argv_steps=argv_steps,
        env_additions=env_additions,
        deploy_dir=deploy_dir,
        lock_path=lock_path,
        lock_warning=lock_warning,
    )


def _run_under_lock(plan: _RunPlan, dry_run: bool) -> tuple[_RunOutcome, Path]:
    """Launch, capture, probe and write the transcript — all inside the box lock."""
    global _ACTIVE_LOCK  # noqa: PLW0603 - the signal handler needs the live lock path

    _acquire_marker(plan.lock_path, plan.manifest_path.parent, plan.started)
    _ACTIVE_LOCK = plan.lock_path
    previous = _install_signal_handlers()
    atexit.register(_release_marker, plan.lock_path)
    try:
        before = _capture_state()
        launch_results: list[dict[str, Any]] = []
        launch_exit_code: int | None = None
        if not dry_run:
            launch_results, launch_exit_code = _execute(plan.argv_steps, plan.env_additions)
        gateway_status, gateway_error = _probe_gateway(plan.gateway_url)
        outcome = _RunOutcome(
            dry_run=dry_run,
            before=before,
            after=_capture_state(),
            launch_results=launch_results,
            launch_exit_code=launch_exit_code,
            gateway_status=gateway_status,
            gateway_error=gateway_error,
        )
        transcript_path = _write_evidence(plan, outcome)
    finally:
        _restore_signal_handlers(previous)
        atexit.unregister(_release_marker)
        _release_marker(plan.lock_path)
        _ACTIVE_LOCK = None
    return outcome, transcript_path


def _emit_run_result(
    plan: _RunPlan, outcome: _RunOutcome, transcript_path: Path, json_mode: bool
) -> None:
    result: dict[str, Any] = {
        "transcript": str(transcript_path),
        "sidecar": str(transcript_path.with_suffix("")),
        "lock_path": str(plan.lock_path),
        "marker_cleared": not plan.lock_path.exists(),
        "gateway_status": outcome.gateway_status,
        _K_LAUNCH_EXIT: outcome.launch_exit_code,
    }
    if plan.lock_warning:
        result["lock_warning"] = plan.lock_warning
    if outcome.dry_run:
        result["dry_run"] = True
        result[_K_ARGV] = plan.argv_steps
        result["env"] = plan.env_additions

    if json_mode:
        emit_result(result, json_mode=True)
        return
    lines = [f"transcript: {transcript_path}", f"sidecar: {result['sidecar']}"]
    if outcome.dry_run:
        lines.extend(f"dry-run argv: {shlex.join(argv)}" for argv in plan.argv_steps)
        lines.append(f"dry-run env additions: {plan.env_additions}")
    emit_result("\n".join(lines), json_mode=False)


def cmd_arm_run(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    dry_run = bool(getattr(args, "dry_run", False))

    plan = _plan_run(args)
    if plan.lock_warning:
        emit_diagnostic(f"warning: {plan.lock_warning}")

    outcome, transcript_path = _run_under_lock(plan, dry_run)

    if outcome.gateway_status != 200:
        emit_diagnostic(
            f"warning: gateway probe to {plan.gateway_url.rstrip('/')}{_CAPABILITIES} "
            f"did not return 200 (status={outcome.gateway_status}, "
            f"error={outcome.gateway_error})"
        )

    _emit_run_result(plan, outcome, transcript_path, json_mode)

    if outcome.launch_exit_code:
        # The transcript is written and the lock released; the run itself failed.
        raise CliError(
            code=EXIT_ENV_ERROR,
            message=f"arm launch failed (exit {outcome.launch_exit_code})",
            remediation=f"read the ## launch section of {transcript_path} for the child's output",
        )
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "run",
        help="Run one arm: box lock, before/after capture, pinned launch, transcript.",
    )
    p.add_argument("path", help="Arm directory or arm.toml path.")
    p.add_argument(
        "--deploy-dir",
        dest="deploy_dir",
        help="Deploy directory recorded in the transcript (default: $LAB_DEPLOY_DIR"
        " or ~/.edge-ai-lab). The box lock is box-wide and NOT affected by this.",
    )
    p.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Capture and write the lock/transcript but do not launch.",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_arm_run)
