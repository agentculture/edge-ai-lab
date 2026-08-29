"""Tests for the introspection verbs: overview, cli overview, doctor."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edge_ai_lab.cli import main
from edge_ai_lab.cli._commands.doctor import (
    _check_no_secrets,
    _check_resident_rules,
    _check_stdlib_only,
)

# --- overview -------------------------------------------------------------


def test_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# edge-ai-lab" in out
    assert "Identity" in out


def test_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "edge-ai-lab"
    assert isinstance(payload["sections"], list)
    assert payload["sections"]


def test_overview_graceful_on_bad_path(capsys: pytest.CaptureFixture[str]) -> None:
    # Rubric contract: descriptive verbs never hard-fail on a missing target.
    rc = main(["overview", "/no/such/path/here"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


# --- cli overview ---------------------------------------------------------


def test_cli_overview_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview"])
    assert rc == 0
    assert "# edge-ai-lab cli" in capsys.readouterr().out


def test_cli_overview_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli", "overview", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["subject"] == "edge-ai-lab cli"
    assert isinstance(payload["sections"], list)


def test_cli_noun_bare_is_non_empty(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["cli"])
    assert rc == 0
    assert capsys.readouterr().out.strip()


def test_cli_overview_unknown_flag_structured_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # `cli overview` parse errors must route through the structured error
    # contract (error:/hint: + exit 1), not argparse's default stderr/exit 2.
    with pytest.raises(SystemExit) as exc:
        main(["cli", "overview", "--bogus"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("error:")
    assert "hint:" in err


# --- doctor ---------------------------------------------------------------


def test_doctor_text(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor"])
    assert rc in (0, 1)
    assert "edge-ai-lab doctor" in capsys.readouterr().out


def test_doctor_json_shape(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--json"])
    assert rc in (0, 1)
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload["healthy"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    for check in payload["checks"]:
        assert {"id", "passed", "severity", "message", "remediation"} <= set(check)


def test_doctor_recognizes_declared_backend(capsys: pytest.CaptureFixture[str]) -> None:
    """The repo's own declared backend must be a known one — doctor stays healthy.

    Guards the backend-consistency invariant: a promotion that changes
    ``culture.yaml``'s backend without teaching ``doctor`` the matching prompt
    file would otherwise slip through (the shape tests above tolerate rc==1).
    """
    rc = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    messages = " ".join(str(c["message"]) for c in payload["checks"])
    assert "unknown backend" not in messages
    assert rc == 0
    assert payload["healthy"] is True


# --- doctor: new t8 checks -------------------------------------------------


_NEW_CHECK_IDS = ("resident-rules-present", "no-secrets-in-arms", "stdlib-only")


def test_doctor_json_lists_new_check_ids(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc in (0, 1)
    ids = {c["id"] for c in payload["checks"]}
    for check_id in _NEW_CHECK_IDS:
        assert check_id in ids


def test_doctor_real_repo_passes_new_checks(capsys: pytest.CaptureFixture[str]) -> None:
    """The real repo's AGENTS.colleague.md/pyproject.toml/setup/ tree is clean."""
    rc = main(["doctor", "--json"])
    payload = json.loads(capsys.readouterr().out)
    checks = {c["id"]: c for c in payload["checks"]}
    for check_id in _NEW_CHECK_IDS:
        assert checks[check_id]["passed"] is True, checks[check_id]["message"]
    assert rc == 0
    assert payload["healthy"] is True


def test_resident_rules_present_flips_to_fail_on_missing_phrase(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.colleague.md").write_text(
        "This resident prompt mentions docs/evidence/ and the shared-box budget "
        "rule, but not the arm path scheme.",
        encoding="utf-8",
    )
    result = _check_resident_rules(tmp_path)
    assert result["id"] == "resident-rules-present"
    assert result["passed"] is False
    assert "setup/<device-class>/<model>/<configuration>" in result["message"]


def test_resident_rules_present_passes_with_all_phrases(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.colleague.md").write_text(
        "Arms live at setup/<device-class>/<model>/<configuration>/. "
        "Every number needs a transcript under docs/evidence/. "
        "Respect the shared-box budget on fleet boxes.",
        encoding="utf-8",
    )
    result = _check_resident_rules(tmp_path)
    assert result["passed"] is True


def test_resident_rules_present_missing_file(tmp_path: Path) -> None:
    result = _check_resident_rules(tmp_path)
    assert result["passed"] is False


def test_no_secrets_in_arms_flips_to_fail_on_leaked_token(tmp_path: Path) -> None:
    leaf = tmp_path / "setup" / "x" / "y" / "z"
    leaf.mkdir(parents=True)
    (leaf / "README.md").write_text("token=hf_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    result = _check_no_secrets(tmp_path)
    assert result["id"] == "no-secrets-in-arms"
    assert result["passed"] is False
    assert "setup/x/y/z/README.md:1" in result["message"]


def test_no_secrets_in_arms_passes_when_clean(tmp_path: Path) -> None:
    leaf = tmp_path / "setup" / "spark" / "model" / "cfg"
    leaf.mkdir(parents=True)
    (leaf / "README.md").write_text("nothing to see here\n", encoding="utf-8")
    result = _check_no_secrets(tmp_path)
    assert result["passed"] is True


def test_no_secrets_in_arms_ok_when_no_setup_dir(tmp_path: Path) -> None:
    result = _check_no_secrets(tmp_path)
    assert result["passed"] is True
    assert "no setup/ tree" in result["message"]


def test_stdlib_only_flips_to_fail_on_yaml_import(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = []\n', encoding="utf-8"
    )
    pkg = tmp_path / "edge_ai_lab" / "sub"
    pkg.mkdir(parents=True)
    (pkg / "stub.py").write_text("import yaml\n\ndef f():\n    return yaml\n", encoding="utf-8")
    result = _check_stdlib_only(tmp_path)
    assert result["id"] == "stdlib-only"
    assert result["passed"] is False
    assert "sub/stub.py:1" in result["message"]


def test_stdlib_only_flips_to_fail_on_nonempty_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["pyyaml"]\n', encoding="utf-8"
    )
    result = _check_stdlib_only(tmp_path)
    assert result["passed"] is False
    assert "dependencies" in result["message"]


def test_stdlib_only_passes_when_clean(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = []\n', encoding="utf-8"
    )
    pkg = tmp_path / "edge_ai_lab"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("import json\n", encoding="utf-8")
    result = _check_stdlib_only(tmp_path)
    assert result["passed"] is True
