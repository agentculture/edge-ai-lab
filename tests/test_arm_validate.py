"""Tests for ``lab arm validate <path>`` (docs/lab-conventions.md contract).

Fixture arms are assembled in ``tmp_path`` from the static templates under
``tests/fixtures/arms/`` (``arm.toml``, ``README.md``, ``Dockerfile.*``) so
each test only edits the one thing it means to break.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from edge_ai_lab.cli import main
from edge_ai_lab.cli._errors import CliError

_FIXTURES = Path(__file__).parent / "fixtures" / "arms"


def _build_arm(
    tmp_path: Path,
    *,
    status: str = "declared-unvalidated",
    transcripts: list[str] | None = None,
    dockerfile: str | None = "digest",
    readme_edits: dict[str, str] | None = None,
    manifest_extra: str = "",
    manifest_edits: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Build one fixture arm under ``tmp_path`` and return ``(root, arm_dir)``."""
    root = tmp_path
    (root / "pyproject.toml").write_text('[project]\nname = "fixture"\n', encoding="utf-8")

    # The directory names must agree with the manifest (arm.py path identity):
    # setup/<device_class>/<model-slug>/<configuration>/.
    arm_dir = root / "setup" / "spark" / "model" / "vllm-mtp"
    arm_dir.mkdir(parents=True)

    manifest = (_FIXTURES / "arm.toml").read_text(encoding="utf-8")
    manifest = manifest.replace('status = "declared-unvalidated"', f'status = "{status}"')
    for old, new in (manifest_edits or {}).items():
        assert old in manifest, f"fixture arm.toml no longer contains {old!r}"
        manifest = manifest.replace(old, new)
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


_DIGEST_64 = "sha256:" + "ab" * 32
_LOBES_OVERRIDE = {'format = "sparkrun-recipe"': 'format = "lobes-override"'}
_DIGEST_PIN = 'image_digest = "sha256:abc123"'
_EMPTY_DIGEST_PIN = 'image_digest = ""'
_README_DIGEST_LINE = "`image_digest`: sha256:abc123 (never a tag)"


def _dockerfile_check(payload: object) -> dict:
    checks = payload if isinstance(payload, list) else payload["checks"]  # type: ignore[index]
    return next(c for c in checks if c["id"] == "dockerfile-provenance")


def test_no_dockerfile_fails_for_sparkrun_recipe(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sparkrun-recipe arm builds its own image — a missing Dockerfile is a FAIL."""
    _root, arm_dir = _build_arm(tmp_path, dockerfile=None)
    rc = main(_run(arm_dir))
    assert rc == 1
    check = _dockerfile_check(json.loads(capsys.readouterr().err))
    assert check["passed"] is False
    assert "sparkrun-recipe" in check["message"]


def test_no_dockerfile_passes_for_lobes_override_with_pinned_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        dockerfile=None,
        manifest_edits={
            **_LOBES_OVERRIDE,
            _DIGEST_PIN: f'image_digest = "{_DIGEST_64}"',
        },
        readme_edits={"`image_digest`: sha256:abc123": f"`image_digest`: {_DIGEST_64}"},
    )
    rc = main(_run(arm_dir))
    assert rc == 0
    check = _dockerfile_check(json.loads(capsys.readouterr().out))
    assert check["passed"] is True
    assert _DIGEST_64 in check["message"]


def test_no_dockerfile_passes_for_lobes_override_with_explained_empty_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        dockerfile=None,
        manifest_edits={**_LOBES_OVERRIDE, _DIGEST_PIN: _EMPTY_DIGEST_PIN},
        readme_edits={
            _README_DIGEST_LINE: (
                "`image_digest`: empty — no sm_87 image is pinned by digest anywhere yet"
            )
        },
    )
    rc = main(_run(arm_dir))
    assert rc == 0
    check = _dockerfile_check(json.loads(capsys.readouterr().out))
    assert check["passed"] is True
    assert "empty image_digest" in check["message"]


def test_no_dockerfile_fails_for_lobes_override_with_unexplained_empty_digest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(
        tmp_path,
        dockerfile=None,
        manifest_edits={**_LOBES_OVERRIDE, _DIGEST_PIN: _EMPTY_DIGEST_PIN},
        readme_edits={_README_DIGEST_LINE: "`image_digest`:"},
    )
    rc = main(_run(arm_dir))
    assert rc == 1
    check = _dockerfile_check(json.loads(capsys.readouterr().err))
    assert check["passed"] is False


def test_real_setup_arms_validate() -> None:
    """Both checked-in arms under setup/ still pass the whole contract."""
    repo = Path(__file__).resolve().parent.parent
    arms = sorted((repo / "setup").glob("*/*/*/arm.toml"))
    assert arms, "no arms found under setup/"
    for manifest in arms:
        assert main(["arm", "validate", str(manifest), "--json"]) == 0, manifest


# --- transcript containment (must stay inside docs/evidence/) -----------------------

_TOKEN = "hf_abcdefghijklmnopqrstuvwxyz123456"


def _measured_arm(tmp_path: Path, transcript: str) -> Path:
    _root, arm_dir = _build_arm(tmp_path, status="measured", transcripts=[transcript])
    return arm_dir


def _status_message(err: str) -> str:
    payload = json.loads(err)
    return next(c for c in payload["checks"] if c["id"] == "status-marker")["message"]


def test_absolute_transcript_path_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = tmp_path / "elsewhere.txt"
    secret.write_text("data\n", encoding="utf-8")
    arm_dir = _measured_arm(tmp_path, str(secret))
    assert main(_run(arm_dir)) == 1
    assert "absolute path" in _status_message(capsys.readouterr().err)


def test_dotdot_transcript_path_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    arm_dir = _measured_arm(tmp_path, "docs/evidence/../../etc/passwd")
    assert main(_run(arm_dir)) == 1
    assert "'..'" in _status_message(capsys.readouterr().err)


def test_transcript_outside_evidence_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = tmp_path / "docs" / "notes"
    other.mkdir(parents=True)
    (other / "run.txt").write_text("data\n", encoding="utf-8")
    arm_dir = _measured_arm(tmp_path, "docs/notes/run.txt")
    assert main(_run(arm_dir)) == 1
    assert "outside docs/evidence/" in _status_message(capsys.readouterr().err)


def test_transcript_symlink_escaping_evidence_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("data\n", encoding="utf-8")
    evidence = tmp_path / "docs" / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "link.txt").symlink_to(outside)
    arm_dir = _measured_arm(tmp_path, "docs/evidence/link.txt")
    assert main(_run(arm_dir)) == 1
    assert "outside docs/evidence/" in _status_message(capsys.readouterr().err)


# --- secrets -----------------------------------------------------------------------


def test_no_secrets_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    (arm_dir / "leaked.env").write_text(f"HF_TOKEN={_TOKEN}\n", encoding="utf-8")
    rc = main(_run(arm_dir, json_mode=False))
    assert rc == 1
    err = capsys.readouterr().err
    assert "no-secrets" in err


def _secrets_message(err: str) -> str:
    payload = json.loads(err)
    return next(c for c in payload["checks"] if c["id"] == "no-secrets")["message"]


def test_secret_at_end_of_large_file_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 2 MiB file used to be skipped wholesale by the 1 MiB size bound."""
    _root, arm_dir = _build_arm(tmp_path)
    big = arm_dir / "big.log"
    big.write_bytes(b"x" * (2 * 1024 * 1024) + f"\nHF_TOKEN={_TOKEN}\n".encode())
    assert main(_run(arm_dir)) == 1
    assert "big.log" in _secrets_message(capsys.readouterr().err)


def test_secret_in_undecodable_file_is_caught(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A latin-1 (non-UTF-8) file used to be skipped as a 'binary'."""
    _root, arm_dir = _build_arm(tmp_path)
    (arm_dir / "notes.txt").write_bytes("café\n".encode("latin-1") + f"token={_TOKEN}\n".encode())
    assert main(_run(arm_dir)) == 1
    assert "notes.txt" in _secrets_message(capsys.readouterr().err)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read a chmod-000 file")
def test_unreadable_file_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    locked = arm_dir / "locked.env"
    locked.write_text("nothing here\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        assert main(_run(arm_dir)) == 1
        assert "could not scan locked.env" in _secrets_message(capsys.readouterr().err)
    finally:
        locked.chmod(0o600)


# --- JSON error contract (exactly one payload) --------------------------------------


def test_json_failure_emits_one_object_on_stderr_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path, readme_edits={"## Rollback\n": "## Rollback Removed\n"})
    rc = main(_run(arm_dir))
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)  # a single object, not a stream of two
    assert set(payload) == {"code", "message", "remediation", "checks"}
    assert payload["code"] == 1
    assert "readme-rollback" in payload["message"]
    assert "readme-rollback" in payload["remediation"]
    assert any(c["id"] == "readme-rollback" and c["passed"] is False for c in payload["checks"])
    assert any(c["passed"] is True for c in payload["checks"])


def test_json_success_emits_one_object_on_stdout_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _root, arm_dir = _build_arm(tmp_path)
    assert main(_run(arm_dir)) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert isinstance(json.loads(captured.out), list)


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


def test_cli_error_to_dict_keeps_the_three_contract_keys() -> None:
    """`details` adds keys; it can never rename or drop the contract's three."""
    err = CliError(
        code=1,
        message="m",
        remediation="r",
        details={"checks": [{"id": "x"}], "code": "hijacked", "message": "hijacked"},
    )
    payload = err.to_dict()
    assert payload["code"] == 1
    assert payload["message"] == "m"
    assert payload["remediation"] == "r"
    assert payload["checks"] == [{"id": "x"}]
    assert set(payload) == {"code", "message", "remediation", "checks"}


def test_cli_error_without_details_is_exactly_the_contract() -> None:
    assert CliError(code=2, message="m").to_dict() == {
        "code": 2,
        "message": "m",
        "remediation": "",
    }


# --- catalog completeness -----------------------------------------------------


def test_arm_validate_catalog_path_resolves(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["explain", "arm", "validate"])
    assert rc == 0
    capsys.readouterr()
