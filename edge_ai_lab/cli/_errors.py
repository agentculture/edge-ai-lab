"""CliError and exit-code policy (stable-contract).

Every failure inside edge-ai-lab raises :class:`CliError`. The
top-level ``main()`` catches it, formats via :mod:`edge_ai_lab.cli._output`,
and exits with :attr:`CliError.code`. This guarantees:

* no Python traceback leaks to stderr (the agent-first error contract);
* every error has a structured shape ``{code, message, remediation}``;
* the exit-code policy is centralised in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

# Exit-code policy. Documented in ``edge-ai-lab learn`` output.
# 0      = success
# 1      = user-input error (bad flag, missing required arg, unknown path)
# 2      = environment / setup error (tool not installed, file unreadable)
# 3+     = reserved for future categorisation
EXIT_SUCCESS = 0
EXIT_USER_ERROR = 1
EXIT_ENV_ERROR = 2


@dataclass
class CliError(Exception):
    """Structured error raised within the CLI; carries a remediation hint for agents.

    ``details`` is an optional bag of *extra* keys merged into
    :meth:`to_dict` — e.g. ``{"checks": [...]}`` from ``lab arm validate``, so
    a JSON-mode failure stays a **single** object on stderr without losing the
    per-check detail. The three contract keys (``code``/``message``/
    ``remediation``) always win: a colliding ``details`` key is dropped, never
    allowed to reshape the error contract.
    """

    code: int
    message: str
    remediation: str = ""
    details: dict[str, object] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }
        for key, value in (self.details or {}).items():
            if key not in payload:
                payload[key] = value
        return payload
