"""Tests for ``lab arm run <path>`` (box lock, capture, launch, transcript).

Everything here is isolated from the real machine: fake ``uvx``/``docker``
binaries live on a temporary ``PATH`` under ``tmp_path``, the box lock is
redirected into ``tmp_path`` via ``$LAB_BOX_LOCK`` (an autouse fixture, so no
test can ever touch the real ``/var/tmp/edge-ai-lab/arm.lock`` this box's
production fleet shares), the gateway probe hits a local ``http.server``
thread instead of the real fleet gateway, and the fixture arm's checkout root
is its own ``tmp_path`` tree (never the real edge-ai-lab checkout this test
runs from). No real ``docker``/``uvx``/``nvidia-smi``/``nvpmodel`` is ever
invoked, and the SIGTERM test drives the installed handler in-process rather
than spawning the CLI.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from edge_ai_lab.cli import main
from edge_ai_lab.cli._commands import arm_run

_MANIFEST_LINES = [
    'device_class = "{box}"',
    'model = "Test/Model-1B"',
    'configuration = "cfg"',
    'format = "{fmt}"',
    'engine = "vllm"',
    'box = "{box}"',
    'status = "declared-unvalidated"',
    "transcripts = []",
    "",
    "[pins]",
    'image_digest = "sha256:abc123"',
    'model_revision = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"',
    'sparkrun_version = "{sparkrun_version}"',
    'jetson_containers_commit = ""',
    'jetson_containers_packages = ""',
    'model_gear_version = ""',
]

_LOCK_ENV = "LAB_BOX_LOCK"


@pytest.fixture(autouse=True)
def box_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the box-wide lock into ``tmp_path`` for every test in this module."""
    lock = tmp_path / "lock" / "arm.lock"
    monkeypatch.setenv(_LOCK_ENV, str(lock))
    return lock


def _build_arm(
    tmp_path: Path,
    *,
    fmt: str = "lobes-override",
    box: str = "spark",
    sparkrun_version: str = "0.3.6",
    recipe: str | None = None,
    commands: list[str] | None = None,
    port: int | None = None,
    gateway_url: str | None = None,
    definition_body: str | None = None,
) -> tuple[Path, Path]:
    """Build one fixture arm (its own checkout root) under ``tmp_path``."""
    root = tmp_path / "checkout"
    root.mkdir(exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")

    arm_dir = root / "setup" / box / "model" / "cfg"
    arm_dir.mkdir(parents=True)

    lines = [
        line.format(box=box, fmt=fmt, sparkrun_version=sparkrun_version) for line in _MANIFEST_LINES
    ]

    run_lines: list[str] = []
    if recipe is not None or commands is not None or port is not None or gateway_url is not None:
        run_lines.append("")
        run_lines.append("[run]")
        if recipe is not None:
            run_lines.append(f'recipe = "{recipe}"')
        if commands is not None:
            joined = ", ".join(f'"{c}"' for c in commands)
            run_lines.append(f"commands = [{joined}]")
        if port is not None:
            run_lines.append(f"port = {port}")
        if gateway_url is not None:
            run_lines.append(f'gateway_url = "{gateway_url}"')

    (arm_dir / "arm.toml").write_text("\n".join(lines + run_lines) + "\n", encoding="utf-8")
    if definition_body is not None:
        name = (recipe or "recipe.yaml") if fmt == "sparkrun-recipe" else "profile-override.toml"
        (arm_dir / name).write_text(definition_body, encoding="utf-8")
    return root, arm_dir


def _make_fake_bin(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return bin_dir


def _hash_tree(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            hashes[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _run(argv: list[str]) -> list[str]:
    return ["arm", "run", *argv]


def _write_lock(lock: Path, arm_path: str, pid: int) -> None:
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"arm_path": arm_path, "pid": pid, "started": "now"}), encoding="utf-8"
    )


# --- (a) lock already held -----------------------------------------------------


def test_second_run_while_live_lock_exists_refuses(
    tmp_path: Path, box_lock: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, commands=["true"])
    # our own pid: provably alive, so this is a "running", not a "stale", lock
    _write_lock(box_lock, "/some/other/arm", os.getpid())

    rc = main(_run([str(arm_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "already running" in err
    assert "hint:" in err
    assert "/some/other/arm" in err
    # the pre-existing lock is left alone (this run never launched, and never owns it)
    assert box_lock.is_file()


def test_stale_lock_is_refused_and_not_deleted(
    tmp_path: Path, box_lock: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, commands=["true"])
    dead_pid = 4_000_000  # above any plausible pid_max: provably not running
    _write_lock(box_lock, "/some/other/arm", dead_pid)

    rc = main(_run([str(arm_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert "stale" in err
    assert "/some/other/arm" in err
    assert str(box_lock) in err  # the hint names the file to remove
    # arm run never removes another run's lock for the operator
    assert box_lock.is_file()


def test_deploy_dir_does_not_bypass_the_box_lock(
    tmp_path: Path, box_lock: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard is box-wide: a different --deploy-dir must not dodge it."""
    _root, arm_dir = _build_arm(tmp_path, commands=["true"])
    _write_lock(box_lock, "/some/other/arm", os.getpid())
    other_deploy = tmp_path / "elsewhere"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(other_deploy)]))
    assert rc == 1
    assert "already running" in capsys.readouterr().err


def _closed_port() -> int:
    """Return a localhost TCP port that was free a moment ago (nothing listens)."""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --- (b) launch failure: transcript written, lock cleared, exit 2 -------------


def test_launch_failure_clears_lock_writes_transcript_and_exits_2(
    tmp_path: Path,
    box_lock: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Point the gateway probe at a port nothing listens on so the result does
    # not depend on whether a real fleet gateway answers on :8001 (it does on
    # the lab's own Spark, not on CI).
    _root, arm_dir = _build_arm(
        tmp_path,
        fmt="sparkrun-recipe",
        recipe="recipe.yaml",
        gateway_url=f"http://127.0.0.1:{_closed_port()}",
    )
    bin_dir = _make_fake_bin(tmp_path, "uvx", "exit 3")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 2  # environment error — the run itself failed
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["launch_exit_code"] == 3
    assert payload["marker_cleared"] is True
    assert not box_lock.exists()
    # --json still emits exactly one JSON object on stdout; stderr carries the
    # gateway-probe warning line(s) followed by exactly one error object.
    err_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert all(line.startswith("warning:") for line in err_lines[:-1])
    assert json.loads(err_lines[-1])["code"] == 2

    transcript = Path(payload["transcript"])
    assert transcript.is_file()
    text = transcript.read_text(encoding="utf-8")
    assert "launch_exit_code: 3" in text
    assert "## before" in text
    assert "## after" in text
    assert "## measurements" in text


def test_launch_failure_text_mode_prints_error_and_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml")
    bin_dir = _make_fake_bin(tmp_path, "uvx", "exit 3")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir)]))
    assert rc == 2
    captured = capsys.readouterr()
    assert "transcript:" in captured.out
    assert "error: arm launch failed (exit 3)" in captured.err
    assert "hint:" in captured.err


# --- (c) SIGTERM stops the child and clears the lock (in-process) --------------


def test_sigterm_handler_kills_child_and_clears_lock(
    tmp_path: Path, box_lock: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the installed handler directly — no CLI subprocess, no real workload."""
    installed: dict[int, object] = {}

    def fake_signal(signum: int, handler: object) -> object:
        """Capture the handler instead of installing it in this test process."""
        installed[signum] = handler
        return signal.SIG_DFL

    monkeypatch.setattr(arm_run.signal, "signal", fake_signal)

    # A stand-in for a launched arm: `sleep` is inert, and its own session mirrors
    # how _execute_one starts the real child.
    child = subprocess.Popen(  # noqa: S603 - fixed argv, inert test workload
        ["sleep", "30"], start_new_session=True
    )
    try:
        arm_run._acquire_marker(box_lock, tmp_path / "arm", "now")
        monkeypatch.setattr(arm_run, "_ACTIVE_LOCK", box_lock)
        monkeypatch.setattr(arm_run, "_ACTIVE_CHILD", child)
        handler = arm_run._install_signal_handlers()  # captured by fake_signal
        assert signal.SIGTERM in installed
        assert installed[signal.SIGTERM] is arm_run._terminate
        assert handler == {signal.SIGTERM: signal.SIG_DFL, signal.SIGINT: signal.SIG_DFL}

        with pytest.raises(SystemExit) as excinfo:
            arm_run._terminate(int(signal.SIGTERM), None)
    finally:
        if child.poll() is None:  # pragma: no cover - handler already reaped it
            child.kill()
            child.wait(timeout=5)

    assert excinfo.value.code == 128 + int(signal.SIGTERM)
    assert child.poll() is not None, "the child process group was not stopped"
    assert not box_lock.exists(), "the lock was not released by the handler"


def test_release_marker_is_owner_checked(tmp_path: Path, box_lock: Path) -> None:
    _write_lock(box_lock, "/another/arm", 4_000_001)
    arm_run._release_marker(box_lock)
    assert box_lock.is_file(), "a lock owned by another pid must never be removed"


# --- (d) transcript + gateway probe -------------------------------------------


class _CapabilitiesHandler(BaseHTTPRequestHandler):
    status = 200

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path != "/capabilities":
            self.send_response(404)
            self.end_headers()
            return
        body = b'{"ok": true}'
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silence stderr noise
        pass


class _UnavailableHandler(_CapabilitiesHandler):
    status = 503


def _serve(handler: type[BaseHTTPRequestHandler]) -> HTTPServer:
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def capabilities_server() -> object:
    server = _serve(_CapabilitiesHandler)
    try:
        yield server
    finally:
        server.shutdown()


@pytest.fixture
def unavailable_server() -> object:
    server = _serve(_UnavailableHandler)
    try:
        yield server
    finally:
        server.shutdown()


def test_transcript_has_before_after_and_gateway_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    capabilities_server: HTTPServer,
) -> None:
    gateway_url = f"http://127.0.0.1:{capabilities_server.server_port}"
    _root, arm_dir = _build_arm(
        tmp_path,
        fmt="lobes-override",
        commands=["truebin"],
        gateway_url=gateway_url,
    )
    bin_dir = _make_fake_bin(tmp_path, "truebin", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gateway_status"] == 200
    assert payload["launch_exit_code"] == 0

    text = Path(payload["transcript"]).read_text(encoding="utf-8")
    assert "## before" in text
    assert "## after" in text
    assert "## gateway probe" in text
    assert f"{gateway_url}/capabilities -> 200" in text
    assert "docker ps" in text
    assert "nvpmodel -q" in text


def test_gateway_http_error_status_is_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unavailable_server: HTTPServer,
) -> None:
    """A 5xx reply is a status, not a transport error — it must not be discarded."""
    gateway_url = f"http://127.0.0.1:{unavailable_server.server_port}"
    _root, arm_dir = _build_arm(
        tmp_path, fmt="lobes-override", commands=["truebin"], gateway_url=gateway_url
    )
    bin_dir = _make_fake_bin(tmp_path, "truebin", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["gateway_status"] == 503
    assert "status=503" in captured.err  # warning, never a failure

    text = Path(payload["transcript"]).read_text(encoding="utf-8")
    assert f"{gateway_url}/capabilities -> 503" in text


def test_gateway_transport_error_records_no_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # port 1 on loopback: nothing listens, so the probe fails at the transport layer
    _root, arm_dir = _build_arm(
        tmp_path,
        fmt="lobes-override",
        commands=["truebin"],
        gateway_url="http://127.0.0.1:1",
    )
    bin_dir = _make_fake_bin(tmp_path, "truebin", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["gateway_status"] is None
    text = Path(payload["transcript"]).read_text(encoding="utf-8")
    assert "/capabilities -> error:" in text


# --- (e) transcript sidecar ----------------------------------------------------


def test_transcript_sidecar_copies_arm_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    recipe_body = "model: Test/Model-1B\nruntime: vllm\n"
    _root, arm_dir = _build_arm(
        tmp_path,
        fmt="sparkrun-recipe",
        recipe="recipe.yaml",
        definition_body=recipe_body,
    )
    bin_dir = _make_fake_bin(tmp_path, "uvx", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)

    sidecar = Path(payload["sidecar"])
    assert sidecar.is_dir()
    assert sidecar.name == Path(payload["transcript"]).stem
    for name in ("arm.toml", "recipe.yaml"):
        assert (sidecar / name).read_bytes() == (arm_dir / name).read_bytes()

    run_json = json.loads((sidecar / "run.json").read_text(encoding="utf-8"))
    assert run_json["arm_path"] == str(arm_dir)
    assert run_json["launch_exit_code"] == 0
    assert run_json["sparkrun_version"] == "0.3.6"
    assert run_json["lock_path"] == os.environ[_LOCK_ENV]
    assert any("sparkrun==0.3.6" in arg for argv in run_json["launch_argv"] for arg in argv)

    header = Path(payload["transcript"]).read_text(encoding="utf-8")
    assert str(sidecar) in header
    assert f"{sidecar.name}/recipe.yaml" in header


def test_sidecar_collision_gets_a_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="lobes-override", commands=["truebin"], definition_body="x = 1\n"
    )
    bin_dir = _make_fake_bin(tmp_path, "truebin", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    one = json.loads(capsys.readouterr().out)
    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    two = json.loads(capsys.readouterr().out)

    assert one["transcript"] != two["transcript"]
    assert one["sidecar"] != two["sidecar"]
    assert Path(two["transcript"]).stem.endswith("-2")
    assert (Path(two["sidecar"]) / "profile-override.toml").read_bytes() == (
        arm_dir / "profile-override.toml"
    ).read_bytes()


# --- (f) fleet dir is never touched -------------------------------------------


def test_fleet_dir_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()
    (fleet_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (fleet_dir / ".env").write_text("MODEL_GEAR_VERSION=1\n", encoding="utf-8")
    before_hashes = _hash_tree(fleet_dir)

    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override", commands=["truebin"])
    bin_dir = _make_fake_bin(tmp_path, "truebin", "exit 0")
    monkeypatch.setenv("PATH", str(bin_dir))

    rc = main(_run([str(arm_dir), "--json"]))
    assert rc == 0
    capsys.readouterr()

    assert _hash_tree(fleet_dir) == before_hashes


def test_refuses_deploy_dir_inside_lobes_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override", commands=["truebin"])
    deploy_dir = fake_home / ".lobes" / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert ".lobes" in err


# --- (g) reserved ports ---------------------------------------------------------


@pytest.mark.parametrize("port", [8000, 8001])
def test_reserved_port_refuses(
    tmp_path: Path, box_lock: Path, port: int, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override", commands=["truebin"], port=port)

    rc = main(_run([str(arm_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert str(port) in err
    assert not box_lock.exists()


# --- (h) --dry-run ---------------------------------------------------------------


def test_dry_run_json_shows_argv_and_env(
    tmp_path: Path,
    box_lock: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version="0.3.6"
    )
    # No uvx on PATH at all — --dry-run must never try to invoke it.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()

    rc = main(_run([str(arm_dir), "--dry-run", "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert any("sparkrun==0.3.6" in arg for argv in payload["argv"] for arg in argv)
    assert payload["env"]["SPARKRUN_NO_TELEMETRY"] == "1"
    assert payload["marker_cleared"] is True
    assert not box_lock.exists()
    assert Path(payload["transcript"]).is_file()


def test_dry_run_text_mode_prints_argv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version="0.3.6"
    )

    rc = main(_run([str(arm_dir), "--dry-run"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "sparkrun==0.3.6" in out
    assert "SPARKRUN_NO_TELEMETRY" in out
    assert "transcript:" in out
    assert "sidecar:" in out


# --- missing pins / commands --------------------------------------------------


def test_missing_sparkrun_version_pin_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version=""
    )

    rc = main(_run([str(arm_dir), "--dry-run"]))
    assert rc == 1
    err = capsys.readouterr().err
    assert "sparkrun_version" in err


def test_missing_run_commands_for_lobes_override_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override")

    rc = main(_run([str(arm_dir), "--dry-run"]))
    assert rc == 1
    err = capsys.readouterr().err
    assert "[run].commands" in err


# --- (i) lock-path resolution ----------------------------------------------------


def test_lock_path_falls_back_to_home_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_LOCK_ENV, raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    unwritable = tmp_path / "nope"
    unwritable.mkdir(mode=0o500)
    monkeypatch.setattr(arm_run, "_SYSTEM_LOCK_DIR", unwritable)

    lock_path, warning = arm_run._resolve_lock_path()
    assert lock_path == fake_home / ".edge-ai-lab" / "arm.lock"
    assert warning is not None
    assert str(unwritable) in warning


def test_lock_path_prefers_the_system_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_LOCK_ENV, raising=False)
    system_dir = tmp_path / "var-tmp" / "edge-ai-lab"
    monkeypatch.setattr(arm_run, "_SYSTEM_LOCK_DIR", system_dir)

    lock_path, warning = arm_run._resolve_lock_path()
    assert lock_path == system_dir / "arm.lock"
    assert warning is None
    assert system_dir.is_dir()


# --- (j) catalog completeness -----------------------------------------------


def test_arm_run_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "arm", "run"])
    assert rc == 0
    capsys.readouterr()
