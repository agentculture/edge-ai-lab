"""Tests for ``arm export`` — the refusing stub gated on the jetson-arena contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge_ai_lab.cli import main
from edge_ai_lab.cli._commands.arm_export import ARENA_CONTRACT_ISSUE, NOT_AGREED
from edge_ai_lab.explain.catalog import ENTRIES

_MANIFEST = """\
device_class = "spark"
model = "Qwen/Qwen3.8-27B-FP8"
configuration = "vllm-mtp"
format = "sparkrun-recipe"
engine = "vllm"
box = "spark"
status = "declared-unvalidated"
transcripts = []

[pins]
image_digest = "sha256:abc"
model_revision = "deadbeef"
sparkrun_version = "0.3.6"
jetson_containers_commit = ""
jetson_containers_packages = ""
model_gear_version = ""
"""


@pytest.fixture
def arm_dir(tmp_path: Path) -> Path:
    d = tmp_path / "setup" / "spark" / "qwen3.8-27b-fp8" / "vllm-mtp"
    d.mkdir(parents=True)
    (d / "arm.toml").write_text(_MANIFEST)
    return d


def test_export_arena_refuses_until_agreed_json(
    arm_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "export", str(arm_dir), "--format", "arena", "--json"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert NOT_AGREED in payload["message"]
    assert ARENA_CONTRACT_ISSUE in payload["remediation"]


def test_export_arena_refuses_text(arm_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["arm", "export", str(arm_dir), "--format", "arena"])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert NOT_AGREED in err
    assert "hint:" in err and ARENA_CONTRACT_ISSUE in err


def test_export_unknown_format_is_cli_error(
    arm_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "export", str(arm_dir), "--format", "csv"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unknown export format" in err
    assert NOT_AGREED not in err


def test_export_missing_manifest_is_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "export", str(tmp_path / "nope"), "--format", "arena"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "no arm.toml" in err
    assert NOT_AGREED not in err


def test_export_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    assert ("arm", "export") in ENTRIES
    rc = main(["explain", "arm", "export"])
    assert rc == 0
    assert ARENA_CONTRACT_ISSUE in capsys.readouterr().out
