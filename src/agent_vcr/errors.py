"""Exception types raised by agent-vcr."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class AgentVCRError(Exception):
    """Base class for all agent-vcr errors."""


class AgentVCRWarning(UserWarning):
    """Warning emitted for tolerated replay drift (lenient mode)."""


class ReplayedError(AgentVCRError):
    """Raised during replay to reproduce a tool call that errored when recorded."""


class CassetteFormatError(AgentVCRError):
    """Raised when a cassette file is malformed or uses an unsupported version."""


class CassetteMissError(AgentVCRError):
    """Raised in ``replay-strict`` mode when an incoming call matches no interaction.

    The message includes a human-readable diff between the expected (recorded)
    arguments and the actual arguments so the failure is actionable in CI.
    """

    def __init__(
        self,
        tool_name: str,
        actual_args: Dict[str, Any],
        candidates: Optional[List[Dict[str, Any]]] = None,
        diff: Optional[str] = None,
    ) -> None:
        self.tool_name = tool_name
        self.actual_args = actual_args
        self.candidates = candidates or []
        self.diff = diff or ""
        message = f"no recorded interaction matched call to tool {tool_name!r}"
        if diff:
            message += "\n" + diff
        super().__init__(message)


class CassetteNotFoundError(CassetteMissError):
    """Raised when the cassette file itself is missing in a replay mode.

    This is a different failure than a per-call :class:`CassetteMissError`
    (which signals real trajectory drift): here the recording was never made
    or never committed. It subclasses :class:`CassetteMissError` so existing
    ``except CassetteMissError`` clauses keep working, while CI that wants to
    tell "missing cassette file" apart from "behavior drift" can catch this
    subclass first.
    """

    def __init__(self, cassette_path: Optional[str]) -> None:
        self.cassette_path = cassette_path
        super().__init__(
            tool_name="<cassette>",
            actual_args={},
            diff=f"cannot replay: cassette not found at {cassette_path!r}",
        )
