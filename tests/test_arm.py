"""Tests for the ``arm`` noun: overview, list, show over setup/**/arm.toml."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge_ai_lab.cli import main

_MANIFEST_A = """\
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

_MANIFEST_B = """\
device_class = "thor"
model = "unsloth/Qwen3.8-27B-NVFP4"
configuration = "lobes-default"
format = "lobes-override"
engine = "vllm"
box = "thor"
status = "measured"
transcripts = ["docs/evidence/2026-08-29-measure-qwen38-nvfp4-thor.txt"]

[pins]
image_digest = "sha256:def"
model_revision = "cafebabe"
sparkrun_version = ""
jetson_containers_commit = "0123456789abcdef0123456789abcdef01234567"
jetson_containers_packages = "vllm:0.13.0"
model_gear_version = "1.2.3"
"""


def _write_manifest(
    root: Path, device_class: str, model: str, configuration: str, body: str
) -> Path:
    arm_dir = root / "setup" / device_class / model / configuration
    arm_dir.mkdir(parents=True, exist_ok=True)
    manifest = arm_dir / "arm.toml"
    manifest.write_text(body, encoding="utf-8")
    return manifest


@pytest.fixture
def two_arms(tmp_path: Path) -> Path:
    _write_manifest(tmp_path, "spark", "qwen3.8-27b-fp8", "vllm-mtp", _MANIFEST_A)
    _write_manifest(tmp_path, "thor", "qwen3.8-27b-nvfp4", "lobes-default", _MANIFEST_B)
    return tmp_path


# --- arm overview -----------------------------------------------------------


def test_arm_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["arm", "overview"])
    assert rc == 0
    assert "# edge-ai-lab arm" in capsys.readouterr().out


def test_arm_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["arm", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "edge-ai-lab arm"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_arm_noun_bare_is_overview(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["arm"])
    assert rc == 0
    assert "# edge-ai-lab arm" in capsys.readouterr().out


# --- arm list ----------------------------------------------------------------


def test_arm_list_text_lists_both(two_arms: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["arm", "list", "--root", str(two_arms)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "qwen3.8-27b-fp8" in out
    assert "qwen3.8-27b-nvfp4" in out


def test_arm_list_json_returns_two_objects(
    two_arms: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "list", "--root", str(two_arms), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert len(payload) == 2
    for row in payload:
        assert {"device_class", "model", "configuration", "format", "status", "path"} <= set(row)


def test_arm_list_empty_root_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "list", "--root", str(tmp_path), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out) == []


# --- arm show ----------------------------------------------------------------


def test_arm_show_text(two_arms: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = two_arms / "setup" / "spark" / "qwen3.8-27b-fp8" / "vllm-mtp" / "arm.toml"
    rc = main(["arm", "show", str(manifest)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "device_class: spark" in out
    assert "status: declared-unvalidated" in out
    assert "image_digest" in out


def test_arm_show_accepts_directory(two_arms: Path, capsys: pytest.CaptureFixture[str]) -> None:
    arm_dir = two_arms / "setup" / "thor" / "qwen3.8-27b-nvfp4" / "lobes-default"
    rc = main(["arm", "show", str(arm_dir)])
    assert rc == 0
    assert "engine: vllm" in capsys.readouterr().out


def test_arm_show_json_shape(two_arms: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = two_arms / "setup" / "thor" / "qwen3.8-27b-nvfp4" / "lobes-default" / "arm.toml"
    rc = main(["arm", "show", str(manifest), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["device_class"] == "thor"
    assert payload["transcripts"] == ["docs/evidence/2026-08-29-measure-qwen38-nvfp4-thor.txt"]


def test_arm_show_missing_file_is_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["arm", "show", str(tmp_path / "no-such-arm")])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


def test_arm_show_missing_required_field_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _MANIFEST_A.replace('device_class = "spark"\n', "")
    manifest = _write_manifest(tmp_path, "spark", "broken", "cfg", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "device_class" in err
    assert "hint:" in err


def test_arm_show_invalid_enum_value_is_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _MANIFEST_A.replace('status = "declared-unvalidated"', 'status = "bogus-status"')
    manifest = _write_manifest(tmp_path, "spark", "broken2", "cfg", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "status" in err
    assert "hint:" in err


# --- catalog completeness -----------------------------------------------------


def test_arm_catalog_paths_resolve(capsys: pytest.CaptureFixture[str]) -> None:
    for path in (("arm",), ("arm", "overview"), ("arm", "list"), ("arm", "show")):
        rc = main(["explain", *path])
        assert rc == 0, f"explain {' '.join(path)} failed"
        capsys.readouterr()
