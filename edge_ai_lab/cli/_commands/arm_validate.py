"""``edge-ai-lab arm validate <path>`` — the arm-directory contract checker.

Enforces the parts of ``docs/lab-conventions.md`` that ``arm list``/``arm
show`` do not: the README's required sections (Rollback, Build footprint,
Pins), the honesty status marker (§3), Dockerfile provenance (§5), and the
no-secrets rule (§8). This module is a plug-in registered by
``edge_ai_lab/cli/_commands/arm.py`` (see that module's docstring for the
plug-in contract) — it reuses :mod:`edge_ai_lab.cli._commands.arm`'s manifest
loading/validation instead of re-parsing ``arm.toml`` itself, and reuses
:mod:`edge_ai_lab.cli._commands.doctor`'s streaming secret scanner instead of
duplicating it.

Each check produces ``{id, passed, message}``. Text mode prints one line per
check to stdout, then (on any failure) ``error: … / hint: …`` to stderr via
the normal :class:`~edge_ai_lab.cli._errors.CliError` contract. ``--json``
emits exactly **one** object per run: the check list on stdout when everything
passes, otherwise a single ``{code, message, remediation, checks}`` error
object on stderr — never both. Exit 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from edge_ai_lab.cli._commands import arm as _arm
from edge_ai_lab.cli._commands.doctor import secret_hits
from edge_ai_lab.cli._errors import EXIT_USER_ERROR, CliError
from edge_ai_lab.cli._output import emit_result

# A value that reads as unfilled rather than measured (docs/lab-conventions.md
# §6, §7: "no TBD placeholders").
_PLACEHOLDER_RE = re.compile(r"(?i)\b(tbd|todo)\b|\.\.\.|<fill")

# Dockerfile provenance (§5): either a digest-pinned FROM, or the
# jetson-containers chain + build-env header.
_FROM_DIGEST_RE = re.compile(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\b", re.IGNORECASE)
_JC_HEADER_RE = re.compile(r"#\s*jetson-containers:.*\b[0-9a-f]{7,40}\b", re.IGNORECASE)
_L4T_RE = re.compile(r"^#\s*L4T_VERSION=")
_CUDA_VERSION_RE = re.compile(r"^#\s*CUDA_VERSION=")
_CUDA_ARCH_RE = re.compile(r"^#\s*CUDA_ARCH=")
_DOCKERFILE_SCAN_LINES = 30

# A digest-pinned image (§5): `sha256:` plus exactly 64 hex characters.
_IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

# How a README's Pins section is allowed to explain an *absent* image digest.
_EMPTY_DIGEST_WORDS = ("empty", "n/a")

_README_NOT_FOUND = "README.md not found"
_EVIDENCE_DIR = "docs/evidence"


def _pass(check_id: str, message: str) -> dict[str, object]:
    return {"id": check_id, "passed": True, "message": message}


def _fail(check_id: str, message: str) -> dict[str, object]:
    return {"id": check_id, "passed": False, "message": message}


def _read_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _find_section(text: str, heading: str) -> str | None:
    """Body of the level-2 section whose heading text matches ``heading``
    case-insensitively, up to (excluding) the next ``##`` heading or EOF."""
    lines = text.splitlines()
    heading_pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.IGNORECASE)
    start = None
    for i, line in enumerate(lines):
        if heading_pattern.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if re.match(r"^##\s+\S", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _find_repo_root(start: Path) -> Path:
    """Walk up from ``start`` to the nearest ``pyproject.toml``/``culture.yaml``."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / "culture.yaml").is_file():
            return candidate
    return current


def _manifest_contains(value: object, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_manifest_contains(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_manifest_contains(v, needle) for v in value)
    return False


# --- individual checks -------------------------------------------------------


def _check_rollback(readme_text: str | None) -> dict[str, object]:
    check_id = "readme-rollback"
    if readme_text is None:
        return _fail(check_id, _README_NOT_FOUND)
    section = _find_section(readme_text, "Rollback")
    if section is None:
        return _fail(check_id, "README.md has no '## Rollback' section")
    for block in re.findall(r"```[^\n]*\n(.*?)```", section, re.DOTALL):
        block = block.strip()
        if block and not _PLACEHOLDER_RE.search(block):
            return _pass(check_id, "Rollback section has a fenced, non-placeholder command")
    return _fail(
        check_id,
        "Rollback section has no fenced code block with a real command "
        "(only placeholders like TBD/TODO/.../ <fill, or none at all)",
    )


def _check_build_footprint(readme_text: str | None) -> dict[str, object]:
    check_id = "readme-build-footprint"
    if readme_text is None:
        return _fail(check_id, _README_NOT_FOUND)
    section = _find_section(readme_text, "Build footprint")
    if section is None:
        return _fail(check_id, "README.md has no '## Build footprint' section")
    missing = []
    for label in ("Build time", "Disk delta", "Retention"):
        m = re.search(rf"{re.escape(label)}:\s*(.+)", section)
        value = m.group(1).strip() if m else ""
        if not value or _PLACEHOLDER_RE.search(value):
            missing.append(label)
    if missing:
        return _fail(
            check_id,
            "missing or placeholder value(s) for: " + ", ".join(missing),
        )
    return _pass(check_id, "Build footprint has measured Build time/Disk delta/Retention")


def _explains_emptiness(text: str) -> bool:
    """Does this README line say *why* a pin is blank rather than leave it blank?"""
    lowered = text.lower()
    return any(word in lowered for word in _EMPTY_DIGEST_WORDS)


class _PinOutcome:
    """Where one manifest pin landed when checked against the Pins section."""

    OK = "ok"
    MISSING = "missing"
    UNEXPLAINED_EMPTY = "unexplained-empty"


def _check_one_pin(section: str, key: str, value: object) -> str:
    """Classify a single manifest pin's line in the README Pins section."""
    line_match = re.search(rf"^.*\b{re.escape(str(key))}\b.*$", section, re.MULTILINE)
    if line_match is None:
        return _PinOutcome.MISSING
    line = line_match.group(0)
    after = line.split(":", 1)[1].strip() if ":" in line else ""
    if value in ("", None):
        if not _explains_emptiness(after):
            return _PinOutcome.UNEXPLAINED_EMPTY
        return _PinOutcome.OK
    if not after or _PLACEHOLDER_RE.search(after):
        return _PinOutcome.MISSING
    return _PinOutcome.OK


def _check_pins(readme_text: str | None, pins: dict[str, object]) -> dict[str, object]:
    check_id = "readme-pins"
    if readme_text is None:
        return _fail(check_id, _README_NOT_FOUND)
    section = _find_section(readme_text, "Pins")
    if section is None:
        return _fail(check_id, "README.md has no '## Pins' section")

    missing: list[str] = []
    unexplained_empty: list[str] = []
    for key, value in pins.items():
        outcome = _check_one_pin(section, key, value)
        if outcome == _PinOutcome.MISSING:
            missing.append(key)
        elif outcome == _PinOutcome.UNEXPLAINED_EMPTY:
            unexplained_empty.append(key)

    problems = []
    if missing:
        problems.append("missing or placeholder value(s): " + ", ".join(missing))
    if unexplained_empty:
        problems.append(
            "empty pin(s) not explained with 'empty'/'n/a': " + ", ".join(unexplained_empty)
        )
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(check_id, "Pins section lists every manifest pin")


def _transcript_problem(root: Path, raw: str) -> str | None:
    """Why this transcript entry is not a usable piece of evidence, or ``None``.

    Containment is checked **before** existence: an absolute path, a ``..``
    segment, or a symlink whose target leaves ``docs/evidence/`` would let an
    arm cite a file the evidence tree does not actually hold (§3), so those are
    rejected on their shape, not on whether they happen to exist.
    """
    candidate = Path(raw)
    if candidate.is_absolute():
        return f"{raw} (absolute path; transcripts are relative to the repo root)"
    if ".." in candidate.parts:
        return f"{raw} (contains a '..' segment)"

    evidence_root = (root / _EVIDENCE_DIR).resolve()
    resolved = (root / candidate).resolve()
    if resolved != evidence_root and evidence_root not in resolved.parents:
        return f"{raw} (resolves outside {_EVIDENCE_DIR}/)"

    if not resolved.is_file():
        return f"{raw} (missing)"
    if resolved.stat().st_size == 0:
        return f"{raw} (empty)"
    return None


def _check_measured(check_id: str, data: dict[str, object], root: Path) -> dict[str, object]:
    transcripts = data["transcripts"]
    assert isinstance(transcripts, list)
    if not transcripts:
        return _fail(check_id, "status is 'measured' but transcripts is empty")
    broken = [
        problem
        for problem in (_transcript_problem(root, str(rel)) for rel in transcripts)
        if problem is not None
    ]
    if broken:
        return _fail(check_id, "unusable transcript path(s): " + "; ".join(broken))
    return _pass(
        check_id, f"every transcript is under {_EVIDENCE_DIR}/, exists on disk and is non-empty"
    )


def _check_declared(check_id: str, text: str) -> dict[str, object]:
    if "DECLARED, UNVALIDATED" not in text:
        return _fail(check_id, "README.md is missing the literal 'DECLARED, UNVALIDATED' marker")
    return _pass(check_id, "README carries the DECLARED, UNVALIDATED marker")


def _check_virtual32(check_id: str, data: dict[str, object], text: str) -> dict[str, object]:
    problems = []
    if "capacity-only" not in text:
        problems.append("README.md is missing the literal 'capacity-only'")
    if "measured on 64GB hardware" not in text:
        problems.append("README.md is missing the literal 'measured on 64GB hardware'")
    if not _manifest_contains(data, "capacity-only"):
        problems.append("manifest is missing the literal 'capacity-only'")
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(check_id, "virtual-32gb-capacity-only markers present in README and manifest")


def _check_status_marker(
    data: dict[str, object], readme_text: str | None, root: Path
) -> dict[str, object]:
    check_id = "status-marker"
    text = readme_text or ""
    status = data["status"]

    if status == "measured":
        return _check_measured(check_id, data, root)
    if status == "declared-unvalidated":
        return _check_declared(check_id, text)
    if status == "virtual-32gb-capacity-only":
        return _check_virtual32(check_id, data, text)
    return _fail(check_id, f"unknown status '{status}'")


def _check_missing_dockerfile(
    check_id: str, data: dict[str, object], readme_text: str | None
) -> dict[str, object]:
    """No Dockerfile on disk — allowed only for a lobes-override arm that says
    which image it runs (a pinned ``image_digest``) or why it cannot (§5).

    A ``sparkrun-recipe`` arm always builds its own image, so a missing
    Dockerfile there is an unreproducible arm, not an omission.
    """
    fmt = data["format"]
    if fmt != "lobes-override":
        return _fail(
            check_id,
            f"no Dockerfile, but format is '{fmt}' — a sparkrun-recipe arm must carry "
            "the Dockerfile for the image its recipe names",
        )

    pins = data["pins"]
    assert isinstance(pins, dict)
    digest = str(pins.get("image_digest", ""))
    if _IMAGE_DIGEST_RE.match(digest):
        return _pass(
            check_id,
            f"no Dockerfile; lobes-override arm pins image_digest {digest} instead",
        )

    section = _find_section(readme_text or "", "Pins")
    digest_line = re.search(r"^.*\bimage_digest\b.*$", section, re.MULTILINE) if section else None
    if digest_line is not None and _explains_emptiness(digest_line.group(0)):
        return _pass(
            check_id,
            "no Dockerfile; lobes-override arm whose README Pins section explains the "
            "empty image_digest",
        )

    return _fail(
        check_id,
        "no Dockerfile and no provenance for the image: a lobes-override arm must pin "
        "pins.image_digest to sha256:<64 hex> or explain in its README Pins section why "
        "image_digest is empty",
    )


def _check_dockerfile(
    arm_dir: Path, data: dict[str, object], readme_text: str | None
) -> dict[str, object]:
    check_id = "dockerfile-provenance"
    dockerfile = arm_dir / "Dockerfile"
    if not dockerfile.is_file():
        return _check_missing_dockerfile(check_id, data, readme_text)

    try:
        lines = dockerfile.read_text(encoding="utf-8").splitlines()[:_DOCKERFILE_SCAN_LINES]
    except (OSError, UnicodeDecodeError) as exc:
        return _fail(check_id, f"could not read Dockerfile: {exc}")

    if any(_FROM_DIGEST_RE.match(line.strip()) for line in lines):
        return _pass(check_id, "Dockerfile FROM pins an image digest")

    has_jc = any(_JC_HEADER_RE.search(line) for line in lines)
    has_l4t = any(_L4T_RE.match(line.strip()) for line in lines)
    has_cuda_version = any(_CUDA_VERSION_RE.match(line.strip()) for line in lines)
    has_cuda_arch = any(_CUDA_ARCH_RE.match(line.strip()) for line in lines)
    if has_jc and has_l4t and has_cuda_version and has_cuda_arch:
        return _pass(check_id, "Dockerfile header records the jetson-containers chain and env")

    return _fail(
        check_id,
        "Dockerfile has neither a digest-pinned FROM nor a jetson-containers header "
        "(commit + L4T_VERSION/CUDA_VERSION/CUDA_ARCH) in its first "
        f"{_DOCKERFILE_SCAN_LINES} lines",
    )


def _check_no_secrets(arm_dir: Path) -> dict[str, object]:
    check_id = "no-secrets"
    # Same streaming, fail-closed scanner `lab doctor` runs over setup/: every
    # byte of every file, whatever its size or encoding, and an unreadable file
    # is a failure rather than a silent skip.
    hits = secret_hits(arm_dir, arm_dir)
    if hits:
        return _fail(check_id, "secret-like pattern(s): " + ", ".join(hits))
    return _pass(check_id, "no secret-like patterns under the arm directory")


# --- command -------------------------------------------------------------------


def _finish(checks: list[dict[str, object]], json_mode: bool) -> int:
    """Emit the check list, then raise if anything failed.

    JSON mode emits **one** object either way: the check list on stdout when
    every check passes, or a single ``{code, message, remediation, checks}``
    error object on stderr when one does not. Printing the list *and* the error
    in JSON mode would hand an agent two payloads on two streams for one run.
    Text mode keeps printing one line per check to stdout before the error,
    because a human reads the passing lines as context.
    """
    failing = [c for c in checks if not c["passed"]]

    if not json_mode:
        lines = [f"{'pass' if c['passed'] else 'FAIL'} {c['id']}: {c['message']}" for c in checks]
        emit_result("\n".join(lines), json_mode=False)
    elif not failing:
        emit_result(checks, json_mode=True)

    if failing:
        first = failing[0]
        failing_ids = ", ".join(str(c["id"]) for c in failing)
        raise CliError(
            code=EXIT_USER_ERROR,
            message=f"arm validate failed: {failing_ids}",
            remediation=(
                f"{first['id']}: {first['message']} — fix it and re-run "
                "`lab arm validate` (see docs/lab-conventions.md)"
            ),
            details={"checks": checks},
        )
    return 0


def cmd_arm_validate(args: argparse.Namespace) -> int:
    json_mode = bool(getattr(args, "json", False))
    manifest_path = _arm._manifest_path(Path(args.path))
    arm_dir = manifest_path.parent

    checks: list[dict[str, object]] = []

    try:
        data = _arm.load_manifest(manifest_path)
    except CliError as err:
        checks.append(_fail("manifest", err.message))
        return _finish(checks, json_mode)
    checks.append(_pass("manifest", "manifest is valid"))

    readme_text = _read_text(arm_dir / "README.md")

    checks.append(_check_rollback(readme_text))
    checks.append(_check_build_footprint(readme_text))

    pins = data["pins"]
    assert isinstance(pins, dict)
    checks.append(_check_pins(readme_text, pins))

    root_arg = getattr(args, "root", None)
    root = Path(root_arg).resolve() if root_arg else _find_repo_root(arm_dir)
    checks.append(_check_status_marker(data, readme_text, root))

    checks.append(_check_dockerfile(arm_dir, data, readme_text))
    checks.append(_check_no_secrets(arm_dir))

    return _finish(checks, json_mode)


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "validate",
        help=(
            "Validate an arm against docs/lab-conventions.md "
            "(README sections, status marker, Dockerfile provenance, no secrets)."
        ),
    )
    p.add_argument("path", help="Arm directory or arm.toml path.")
    p.add_argument(
        "--root",
        help=(
            "Repo root for resolving 'measured' transcript paths "
            "(default: walk up from the arm directory to the nearest "
            "pyproject.toml/culture.yaml)."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_arm_validate)
