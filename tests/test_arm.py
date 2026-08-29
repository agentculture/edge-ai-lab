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
    manifest = _write_manifest(tmp_path, "spark", "broken", "vllm-mtp", body)
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
    manifest = _write_manifest(tmp_path, "spark", "broken2", "vllm-mtp", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "status" in err
    assert "hint:" in err


# --- manifest contract: closed vocabularies ------------------------------------


@pytest.mark.parametrize(
    ("field", "old", "bad"),
    [
        ("device_class", 'device_class = "spark"', 'device_class = "orin"'),
        ("engine", 'engine = "vllm"', 'engine = "tensorrt"'),
        ("box", 'box = "spark"', 'box = "orin-nano-8"'),
        ("format", 'format = "sparkrun-recipe"', 'format = "docker-compose"'),
    ],
)
def test_out_of_vocabulary_value_names_field_and_allowed_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: str, old: str, bad: str
) -> None:
    body = _MANIFEST_A.replace(old, bad)
    # Keep the directory names agreeing with whatever the manifest still says,
    # so the vocabulary error is the only thing that can fire.
    device_class = bad.split('"')[1] if field == "device_class" else "spark"
    manifest = _write_manifest(tmp_path, device_class, "model", "vllm-mtp", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert field in err
    assert "must be one of" in err


def test_valid_vocabulary_combination_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = (
        _MANIFEST_A.replace('device_class = "spark"', 'device_class = "orin-nano-8"')
        .replace('engine = "vllm"', 'engine = "llama.cpp"')
        .replace('box = "spark"', 'box = "nano"')
    )
    manifest = _write_manifest(tmp_path, "orin-nano-8", "model", "vllm-mtp", body)
    rc = main(["arm", "show", str(manifest), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["engine"] == "llama.cpp"


# --- manifest contract: scalar types --------------------------------------------


@pytest.mark.parametrize(
    ("old", "bad", "needle"),
    [
        ('model = "Qwen/Qwen3.8-27B-FP8"', "model = 27", "'model' must be a string"),
        ("transcripts = []", "transcripts = [1]", "transcript entries must be strings"),
        ("transcripts = []", 'transcripts = "one.txt"', "'transcripts' must be a list"),
        ('sparkrun_version = "0.3.6"', "sparkrun_version = 0.36", "pin 'sparkrun_version'"),
    ],
)
def test_non_scalar_field_is_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], old: str, bad: str, needle: str
) -> None:
    body = _MANIFEST_A.replace(old, bad)
    manifest = _write_manifest(tmp_path, "spark", "model", "vllm-mtp", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    assert needle in capsys.readouterr().err


def test_pins_must_be_a_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    body = _MANIFEST_A.split("[pins]")[0] + 'pins = "none"\n'
    manifest = _write_manifest(tmp_path, "spark", "model", "vllm-mtp", body)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    assert "'pins' must be a table" in capsys.readouterr().err


# --- manifest contract: path identity --------------------------------------------


def test_device_class_must_equal_its_path_segment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest(tmp_path, "thor", "model", "vllm-mtp", _MANIFEST_A)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "device_class" in err
    assert "path segment is 'thor'" in err


def test_configuration_must_equal_its_path_segment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest(tmp_path, "spark", "model", "some-other-cfg", _MANIFEST_A)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "configuration" in err
    assert "path segment is 'some-other-cfg'" in err


def test_model_segment_must_be_a_lowercase_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The model *id* is an HF id, so only the path segment is slug-checked."""
    manifest = _write_manifest(tmp_path, "spark", "Qwen3.8_27B", "vllm-mtp", _MANIFEST_A)
    rc = main(["arm", "show", str(manifest)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not a lowercase slug" in err
    # The HF-style `model` field itself is never compared to the segment.
    assert "Qwen/Qwen3.8-27B-FP8" not in err


def test_hf_style_model_id_is_not_compared_to_the_segment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _write_manifest(tmp_path, "spark", "totally-unrelated-slug", "vllm-mtp", _MANIFEST_A)
    rc = main(["arm", "show", str(manifest), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["model"] == "Qwen/Qwen3.8-27B-FP8"


def test_manifest_outside_a_setup_tree_skips_path_identity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    loose = tmp_path / "scratch" / "arm.toml"
    loose.parent.mkdir(parents=True)
    loose.write_text(_MANIFEST_A, encoding="utf-8")
    rc = main(["arm", "show", str(loose), "--json"])
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["configuration"] == "vllm-mtp"


def test_real_setup_arms_load(capsys: pytest.CaptureFixture[str]) -> None:
    """The two checked-in arms under setup/ still satisfy the whole contract."""
    repo_root = Path(__file__).resolve().parent.parent
    rc = main(["arm", "list", "--root", str(repo_root), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    assert len(rows) == len(sorted((repo_root / "setup").glob("*/*/*/arm.toml")))
    assert "skipping" not in captured.err


# --- catalog completeness -----------------------------------------------------


def test_arm_catalog_paths_resolve(capsys: pytest.CaptureFixture[str]) -> None:
    for path in (("arm",), ("arm", "overview"), ("arm", "list"), ("arm", "show")):
        rc = main(["explain", *path])
        assert rc == 0, f"explain {' '.join(path)} failed"
        capsys.readouterr()
