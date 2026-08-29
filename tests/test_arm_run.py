"""Tests for ``lab arm run <path>`` (box marker, capture, launch, transcript).

Everything here is isolated from the real machine: fake ``uvx``/``docker``
binaries live on a temporary ``PATH`` under ``tmp_path``, the box marker goes
under a ``--deploy-dir``/``LAB_DEPLOY_DIR`` inside ``tmp_path``, the gateway
probe hits a local ``http.server`` thread instead of the real fleet gateway,
and the fixture arm's checkout root is its own ``tmp_path`` tree (never the
real edge-ai-lab checkout this test runs from). No real ``docker``/``uvx``/
``nvidia-smi``/``nvpmodel`` is ever invoked.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from edge_ai_lab.cli import main

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


# --- (a) marker already present -----------------------------------------------


def test_second_run_while_marker_exists_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, commands=["true"])
    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir()
    marker = deploy_dir / "arm.lock"
    marker.write_text(
        json.dumps({"arm_path": "/some/other/arm", "pid": 999999, "started": "now"}),
        encoding="utf-8",
    )

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err
    assert "/some/other/arm" in err
    # the pre-existing marker is left alone (this run never launched)
    assert marker.is_file()


# --- (b) launch failure still clears the marker and writes a transcript ------


def test_launch_failure_clears_marker_and_writes_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml")
    bin_dir = _make_fake_bin(tmp_path, "uvx", "exit 3")
    monkeypatch.setenv("PATH", str(bin_dir))
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["launch_exit_code"] == 3
    assert payload["marker_cleared"] is True
    assert not (deploy_dir / "arm.lock").exists()

    transcript = Path(payload["transcript"])
    assert transcript.is_file()
    text = transcript.read_text(encoding="utf-8")
    assert "launch_exit_code: 3" in text
    assert "## before" in text
    assert "## after" in text
    assert "## measurements" in text


# --- (c) SIGTERM clears the marker --------------------------------------------


def test_sigterm_clears_marker(tmp_path: Path) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override", commands=["sleepbin"])
    bin_dir = _make_fake_bin(tmp_path, "sleepbin", "sleep 30")
    deploy_dir = tmp_path / "deploy"
    marker = deploy_dir / "arm.lock"

    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = subprocess.Popen(  # noqa: S603 - fixed argv, test-only fake binaries
        [
            sys.executable,
            "-m",
            "edge_ai_lab",
            "arm",
            "run",
            str(arm_dir),
            "--deploy-dir",
            str(deploy_dir),
        ],
        env=env,
    )
    try:
        deadline = time.time() + 10
        while not marker.is_file() and time.time() < deadline:
            time.sleep(0.05)
        assert marker.is_file(), "marker was never created before the deadline"

        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    assert not marker.exists()


# --- (d) transcript + gateway probe -------------------------------------------


class _CapabilitiesHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/capabilities":
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args: object) -> None:  # silence stderr noise
        pass


@pytest.fixture()
def capabilities_server() -> object:
    server = HTTPServer(("127.0.0.1", 0), _CapabilitiesHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


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
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--json"]))
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


# --- (e) fleet dir is never touched -------------------------------------------


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
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--json"]))
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


# --- (f) reserved ports ---------------------------------------------------------


@pytest.mark.parametrize("port", [8000, 8001])
def test_reserved_port_refuses(
    tmp_path: Path, port: int, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override", commands=["truebin"], port=port)
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir)]))
    assert rc == 1
    err = capsys.readouterr().err
    assert str(port) in err
    assert not (deploy_dir / "arm.lock").exists()


# --- (g) --dry-run ---------------------------------------------------------------


def test_dry_run_json_shows_argv_and_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version="0.3.6"
    )
    # No uvx on PATH at all — --dry-run must never try to invoke it.
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    (tmp_path / "empty-bin").mkdir()
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--dry-run", "--json"]))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert any("sparkrun==0.3.6" in arg for argv in payload["argv"] for arg in argv)
    assert payload["env"]["SPARKRUN_NO_TELEMETRY"] == "1"
    assert payload["marker_cleared"] is True
    assert not (deploy_dir / "arm.lock").exists()
    assert Path(payload["transcript"]).is_file()


def test_dry_run_text_mode_prints_argv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version="0.3.6"
    )
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--dry-run"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "sparkrun==0.3.6" in out
    assert "SPARKRUN_NO_TELEMETRY" in out
    assert "transcript:" in out


# --- missing pins / commands --------------------------------------------------


def test_missing_sparkrun_version_pin_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, fmt="sparkrun-recipe", recipe="recipe.yaml", sparkrun_version=""
    )
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--dry-run"]))
    assert rc == 1
    err = capsys.readouterr().err
    assert "sparkrun_version" in err


def test_missing_run_commands_for_lobes_override_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, fmt="lobes-override")
    deploy_dir = tmp_path / "deploy"

    rc = main(_run([str(arm_dir), "--deploy-dir", str(deploy_dir), "--dry-run"]))
    assert rc == 1
    err = capsys.readouterr().err
    assert "[run].commands" in err


# --- (h) catalog completeness -----------------------------------------------


def test_arm_run_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "arm", "run"])
    assert rc == 0
    capsys.readouterr()
