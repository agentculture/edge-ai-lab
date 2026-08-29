"""``edge-ai-lab doctor`` — check the agent-identity invariants.

Mirrors the two invariants ``steward doctor`` verifies for a mesh agent:

* **prompt-file-present** — the repo declares an agent in ``culture.yaml`` and
  has the matching prompt file on disk;
* **backend-consistency** — the declared ``backend`` matches the prompt file
  (``claude`` → ``CLAUDE.md``, ``colleague`` → ``AGENTS.colleague.md``,
  ``acp`` → ``AGENTS.md``, ``gemini`` → ``GEMINI.md``).

Plus a **skills-present** check (the vendored ``.claude/skills/`` kit) and
three lab-specific invariants from ``docs/lab-conventions.md``:

* **resident-rules-present** — ``AGENTS.colleague.md`` (the file the mesh
  runtime actually loads) still names the arm path scheme, the transcript
  rule and the shared-box budget rule, so the resident cannot silently drift
  from the rulebook (§1, §3, §4).
* **no-secrets-in-arms** — no token/password/private-host pattern anywhere
  under ``setup/`` (§8) — sparkrun passes a recipe's ``env:`` map literally
  and Spark Arena uploads publish the recipe text and run logs, so a leaked
  credential in an arm file is a real exfiltration path, not just hygiene.
* **stdlib-only** — the runtime package stays dependency-free: an empty
  ``project.dependencies`` in ``pyproject.toml`` and no ``import yaml`` /
  ``from yaml import ...`` under ``edge_ai_lab/`` (mirrors ``whoami.py``'s
  hand-rolled parsing, which exists to keep this true).

Read-only throughout. Reports the rubric-shaped contract
``{healthy, checks: [{id, passed, severity, message, remediation}]}`` so the
agent-first rubric's bundle 7 passes. When run from a wheel install (no
``culture.yaml`` alongside the package), it reports a single info check and
exits 0 — there is nothing to diagnose.
"""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path

from edge_ai_lab.cli._commands.whoami import find_culture_yaml, read_agent_fields
from edge_ai_lab.cli._output import emit_result

# backend → required prompt file (the backend-consistency mapping).
_PROMPT_FILE = {
    "claude": "CLAUDE.md",
    "colleague": "AGENTS.colleague.md",
    "acp": "AGENTS.md",
    "gemini": "GEMINI.md",
}

# docs/lab-conventions.md §1-§4: the literal phrases the resident prompt must
# still carry so the colleague backend never silently drifts from the rules.
_RESIDENT_RULE_PHRASES = (
    "setup/<device-class>/<model>/<configuration>",
    "docs/evidence/",
    "shared-box budget",
)

# docs/lab-conventions.md §8: token / password / private-host patterns that
# must never appear under setup/ (sparkrun passes env: literally, and Spark
# Arena uploads publish recipe text + run logs).
_SECRET_PATTERNS = (
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    re.compile(r"(?i)(password|passwd|api[_-]?key|token)\s*[=:]\s*['\"]?[^\s'\"]{8,}"),
    re.compile(r"\b(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d+\.\d+"),
)

_MAX_SCAN_BYTES = 1024 * 1024  # skip files > 1 MiB — keep the scan bounded.

_YAML_IMPORT_RE = re.compile(r"^\s*(import|from)\s+yaml\b")


def _default_root() -> Path | None:
    cfg = find_culture_yaml()
    return cfg.parent if cfg is not None else None


def _no_root_check(check_id: str, what: str) -> dict[str, object]:
    return {
        "id": check_id,
        "passed": True,
        "severity": "info",
        "message": f"no repo root found; {what} check skipped",
        "remediation": "",
    }


def _check_resident_rules(root: Path | None = None) -> dict[str, object]:
    """AGENTS.colleague.md must still name the arm-path, transcript and
    shared-box-budget rules — the literal phrases from lab-conventions.md."""
    if root is None:
        root = _default_root()
    if root is None:
        return _no_root_check("resident-rules-present", "resident-rules-present")

    agents_file = root / "AGENTS.colleague.md"
    if not agents_file.is_file():
        return {
            "id": "resident-rules-present",
            "passed": False,
            "severity": "error",
            "message": "AGENTS.colleague.md is missing",
            "remediation": "restore AGENTS.colleague.md with the resident rulebook summary",
        }

    try:
        text = agents_file.read_text(encoding="utf-8")
    except OSError as exc:
        return {
            "id": "resident-rules-present",
            "passed": False,
            "severity": "error",
            "message": f"could not read AGENTS.colleague.md: {exc}",
            "remediation": "make AGENTS.colleague.md readable",
        }

    missing = [phrase for phrase in _RESIDENT_RULE_PHRASES if phrase not in text]
    passed = not missing
    return {
        "id": "resident-rules-present",
        "passed": passed,
        "severity": "error",
        "message": (
            "AGENTS.colleague.md names all resident rules"
            if passed
            else "AGENTS.colleague.md is missing: " + ", ".join(missing)
        ),
        "remediation": (
            ""
            if passed
            else "restore the missing phrase(s) in AGENTS.colleague.md "
            "(see docs/lab-conventions.md)"
        ),
    }


def _iter_scannable_files(directory: Path):
    """Yield ``(path, text)`` for regular files under ``directory``, skipping
    anything over ``_MAX_SCAN_BYTES`` or that fails to decode as UTF-8 (i.e.
    binaries)."""
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > _MAX_SCAN_BYTES:
                continue
            text = path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # skip binaries / unreadable files
        yield path, text


def _secret_pattern_lines(text: str) -> list[int]:
    """1-based line numbers in ``text`` that match a secret-like pattern."""
    return [
        lineno
        for lineno, line in enumerate(text.splitlines(), start=1)
        if any(pattern.search(line) for pattern in _SECRET_PATTERNS)
    ]


def _check_no_secrets(root: Path | None = None) -> dict[str, object]:
    """Scan every regular file under setup/ for secret-like patterns."""
    if root is None:
        root = _default_root()
    if root is None:
        return _no_root_check("no-secrets-in-arms", "no-secrets-in-arms")

    setup_dir = root / "setup"
    if not setup_dir.is_dir():
        return {
            "id": "no-secrets-in-arms",
            "passed": True,
            "severity": "error",
            "message": "no setup/ tree",
            "remediation": "",
        }

    hits = [
        f"{path.relative_to(root)}:{lineno}"
        for path, text in _iter_scannable_files(setup_dir)
        for lineno in _secret_pattern_lines(text)
    ]

    passed = not hits
    return {
        "id": "no-secrets-in-arms",
        "passed": passed,
        "severity": "error",
        "message": (
            "no secret-like patterns under setup/"
            if passed
            else "secret-like pattern(s): " + ", ".join(hits)
        ),
        "remediation": (
            ""
            if passed
            else "remove the secret and rotate it; credentials belong in env_file, not the recipe"
        ),
    }


def _dependency_issues(pyproject_path: Path) -> list[str]:
    """``project.dependencies`` must parse and equal ``[]``."""
    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"could not read/parse pyproject.toml: {exc}"]

    deps = data.get("project", {}).get("dependencies")
    if deps != []:
        return [f"project.dependencies is not empty: {deps!r}"]
    return []


def _yaml_import_issues(pkg_dir: Path, root: Path) -> list[str]:
    """``edge_ai_lab/`` must not ``import yaml`` / ``from yaml import ...`` anywhere."""
    if not pkg_dir.is_dir():
        return []

    issues: list[str] = []
    for py_file in sorted(pkg_dir.rglob("*.py")):
        try:
            text = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _YAML_IMPORT_RE.match(line):
                issues.append(f"{py_file.relative_to(root)}:{lineno} imports yaml")
    return issues


def _check_stdlib_only(root: Path | None = None) -> dict[str, object]:
    """project.dependencies must be [] and edge_ai_lab/ must not import yaml."""
    if root is None:
        root = _default_root()
    if root is None:
        return _no_root_check("stdlib-only", "stdlib-only")

    issues = _dependency_issues(root / "pyproject.toml") + _yaml_import_issues(
        root / "edge_ai_lab", root
    )

    passed = not issues
    return {
        "id": "stdlib-only",
        "passed": passed,
        "severity": "warning",
        "message": (
            "project.dependencies == [] and no yaml import under edge_ai_lab/"
            if passed
            else "; ".join(issues)
        ),
        "remediation": (
            ""
            if passed
            else "keep the runtime package dependency-free — remove the dependency "
            "or the yaml import"
        ),
    }


def _diagnose() -> dict[str, object]:
    cfg = find_culture_yaml()
    if cfg is None:
        check = {
            "id": "source_checkout",
            "passed": True,
            "severity": "info",
            "message": "no culture.yaml found alongside the package; identity checks skipped",
            "remediation": "",
        }
        return {"healthy": True, "checks": [check]}

    root = cfg.parent
    fields = read_agent_fields()
    backend = fields["backend"]
    checks: list[dict[str, object]] = []

    # 1. backend-consistency: the prompt file for the declared backend exists.
    expected = _PROMPT_FILE.get(backend)
    if expected is None:
        checks.append(
            {
                "id": "backend_consistency",
                "passed": False,
                "severity": "error",
                "message": f"unknown backend '{backend}' in culture.yaml",
                "remediation": f"set backend to one of: {', '.join(sorted(_PROMPT_FILE))}",
            }
        )
    else:
        present = (root / expected).is_file()
        checks.append(
            {
                "id": "prompt_file_present",
                "passed": present,
                "severity": "error",
                "message": (
                    f"backend '{backend}' requires {expected} — "
                    + ("present" if present else "missing")
                ),
                "remediation": "" if present else f"create {expected} at the repo root",
            }
        )

    # 2. skills-present: the vendored skill kit is on disk.
    skills_dir = root / ".claude" / "skills"
    has_skills = skills_dir.is_dir() and any(skills_dir.iterdir())
    checks.append(
        {
            "id": "skills_present",
            "passed": has_skills,
            "severity": "warning",
            "message": (
                ".claude/skills/ vendored" if has_skills else ".claude/skills/ missing or empty"
            ),
            "remediation": (
                "" if has_skills else "vendor the skill kit (see docs/skill-sources.md)"
            ),
        }
    )

    # 3-5. lab-specific invariants from docs/lab-conventions.md.
    checks.append(_check_resident_rules(root))
    checks.append(_check_no_secrets(root))
    checks.append(_check_stdlib_only(root))

    healthy = all(c["passed"] for c in checks)
    return {"healthy": healthy, "checks": checks}


def cmd_doctor(args: argparse.Namespace) -> int:
    report = _diagnose()
    json_mode = bool(getattr(args, "json", False))
    if json_mode:
        emit_result(report, json_mode=True)
    else:
        status = "healthy" if report["healthy"] else "unhealthy"
        lines = [f"edge-ai-lab doctor: {status}", ""]
        for check in report["checks"]:
            mark = "ok" if check["passed"] else "FAIL"
            lines.append(f"[{mark}] {check['id']}: {check['message']}")
            if not check["passed"] and check["remediation"]:
                lines.append(f"  hint: {check['remediation']}")
        emit_result("\n".join(lines), json_mode=False)
    return 0 if report["healthy"] else 1


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "doctor",
        help="Check the agent-identity invariants (prompt-file-present, backend-consistency).",
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.set_defaults(func=cmd_doctor)
