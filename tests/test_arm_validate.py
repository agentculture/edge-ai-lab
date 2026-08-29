"""Tests for ``lab arm validate <path>`` (docs/lab-conventions.md contract).

Fixture arms are assembled in ``tmp_path`` from the static templates under
``tests/fixtures/arms/`` (``arm.toml``, ``README.md``, ``Dockerfile.*``) so
each test only edits the one thing it means to break.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge_ai_lab.cli import main

_FIXTURES = Path(__file__).parent / "fixtures" / "arms"


def _build_arm(
    tmp_path: Path,
    *,
    status: str = "declared-unvalidated",
    transcripts: list[str] | None = None,
    dockerfile: str | None = "digest",
    readme_edits: dict[str, str] | None = None,
    manifest_extra: str = "",
) -> tuple[Path, Path]:
    """Build one fixture arm under ``tmp_path`` and return ``(root, arm_dir)``."""
    root = tmp_path
    (root / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")

    arm_dir = root / "setup" / "spark" / "model" / "cfg"
    arm_dir.mkdir(parents=True)

    manifest = (_FIXTURES / "arm.toml").read_text(encoding="utf-8")
    manifest = manifest.replace('status = "declared-unvalidated"', f'status = "{status}"')
    transcripts = transcripts if transcripts is not None else []
    transcripts_toml = "[" + ", ".join(f'"{t}"' for t in transcripts) + "]"
    manifest = manifest.replace("transcripts = []", f"transcripts = {transcripts_toml}")
    if manifest_extra:
        manifest = manifest.replace("[pins]", f"{manifest_extra}\n\n[pins]")
    (arm_dir / "arm.toml").write_text(manifest, encoding="utf-8")

    readme = (_FIXTURES / "README.md").read_text(encoding="utf-8")
    for old, new in (readme_edits or {}).items():
        assert old in readme, f"fixture README no longer contains {old!r}"
        readme = readme.replace(old, new)
    (arm_dir / "README.md").write_text(readme, encoding="utf-8")

    if dockerfile is not None:
        docker_text = (_FIXTURES / f"Dockerfile.{dockerfile}").read_text(encoding="utf-8")
        (arm_dir / "Dockerfile").write_text(docker_text, encoding="utf-8")

    return root, arm_dir


def _run(arm_dir: Path, *, json_mode: bool = True, root: Path | None = None) -> list[str]:
    argv = ["arm", "validate", str(arm_dir)]
    if root is not None:
        argv += ["--root", str(root)]
    if json_mode:
        argv.append("--json")
    return argv


# --- full fixture -------------------------------------------------------------


def test_full_fixture_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    rc = main(_run(arm_dir))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload
    for check in payload:
        assert check["passed"] is True, check


def test_full_fixture_text_mode_one_line_per_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 0
    out = capsys.readouterr().out
    assert "manifest" in out
    assert "readme-rollback" in out
    assert "readme-build-footprint" in out
    assert "readme-pins" in out
    assert "status-marker" in out
    assert "dockerfile-provenance" in out
    assert "no-secrets" in out


# --- section removal ------------------------------------------------------------


def test_missing_rollback_section_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path, readme_edits={"## Rollback\n": "## Rollback Removed\n"})
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "readme-rollback" in err
    assert "hint:" in err


def test_missing_build_footprint_section_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path, readme_edits={"## Build footprint\n": "## Build footprint Removed\n"}
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "readme-build-footprint" in err


def test_missing_pins_section_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path, readme_edits={"## Pins\n": "## Pins Removed\n"})
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "readme-pins" in err


# --- placeholder detection ------------------------------------------------------


def test_build_time_tbd_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        readme_edits={
            "Build time: 42m18s (build log 2026-08-01)": "Build time: TBD",
        },
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "readme-build-footprint" in err


# --- status marker ---------------------------------------------------------------


def test_status_measured_nonexistent_transcript_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        status="measured",
        transcripts=["docs/evidence/2026-08-29-measure-model-spark.txt"],
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "status-marker" in err


def test_status_measured_existing_transcript_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, arm_dir = _build_arm(
        tmp_path,
        status="measured",
        transcripts=["docs/evidence/2026-08-29-measure-model-spark.txt"],
    )
    evidence_dir = root / "docs" / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "2026-08-29-measure-model-spark.txt").write_text(
        "usage.completion_tokens=123\n", encoding="utf-8"
    )
    rc = main(_run(arm_dir))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for check in payload:
        assert check["passed"] is True, check


def test_declared_unvalidated_without_marker_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        readme_edits={"DECLARED, UNVALIDATED": "declared but not officially marked"},
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "status-marker" in err


def test_virtual_32gb_without_capacity_only_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, status="virtual-32gb-capacity-only")
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "status-marker" in err


def test_virtual_32gb_with_capacity_only_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        status="virtual-32gb-capacity-only",
        manifest_extra='note = "budget capped to 32GB — capacity-only"',
        readme_edits={
            "marker DECLARED, UNVALIDATED until a transcript lands.": (
                "marker DECLARED, UNVALIDATED until a transcript lands. This arm is "
                "capacity-only: throughput was measured on 64GB hardware and is not a "
                "32GB figure."
            )
        },
    )
    rc = main(_run(arm_dir))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for check in payload:
        assert check["passed"] is True, check


# --- Dockerfile provenance --------------------------------------------------------


def test_dockerfile_no_digest_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path, dockerfile="no-digest")
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "dockerfile-provenance" in err


def test_dockerfile_jetson_containers_header_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, dockerfile="jetson-containers")
    rc = main(_run(arm_dir))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    for check in payload:
        assert check["passed"] is True, check


def test_no_dockerfile_passes_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, dockerfile=None)
    rc = main(_run(arm_dir))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    dockerfile_check = next(c for c in payload if c["id"] == "dockerfile-provenance")
    assert dockerfile_check["passed"] is True
    assert "lobes-override" in dockerfile_check["message"]


# --- secrets -----------------------------------------------------------------------


def test_no_secrets_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    (arm_dir / "leaked.env").write_text(
        "HF_TOKEN=hf_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8"
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "no-secrets" in err


# --- manifest --------------------------------------------------------------------


def test_bad_manifest_fails_naming_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    (arm_dir / "arm.toml").write_text(
        (arm_dir / "arm.toml")
        .read_text(encoding="utf-8")
        .replace('status = "declared-unvalidated"\n', ""),
        encoding="utf-8",
    )
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "manifest" in err


def test_accepts_manifest_path_directly(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    rc = main(_run(arm_dir / "arm.toml"))
    assert rc == 0


# --- catalog completeness -----------------------------------------------------


def test_arm_validate_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "arm", "validate"])
    assert rc == 0
    capsys.readouterr()
