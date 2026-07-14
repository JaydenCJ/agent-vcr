"""Trajectory assertions: check what an agent did, not just what it returned.

A trajectory is the ordered list of tool calls in a cassette. These assertions
catch behavior drift -- a prompt change that makes the agent call an extra tool,
skip a step, or pass different arguments -- which is invisible to output-only
checks. Every failing assertion raises ``AssertionError`` with a printed
trajectory summary so CI logs show exactly what happened.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .cassette import Cassette, load

# A per-call argument check: a callable predicate or a dict of required fields.
ArgMatcher = Union[Callable[[Dict[str, Any]], bool], Dict[str, Any]]


class Trajectory:
    """Fluent assertions over the sequence of tool calls in a cassette.

    Each method returns ``self`` so checks chain; each raises ``AssertionError``
    with a trajectory summary on failure.
    """

    def __init__(self, cassette: Cassette) -> None:
        self.cassette = cassette
        self.calls = list(cassette.interactions)

    # -- introspection -----------------------------------------------------

    @property
    def tool_sequence(self) -> List[str]:
        """The ordered list of tool names that were called."""
        return [c.tool_name for c in self.calls]

    def summary(self) -> str:
        """Return a printable, numbered summary of every call."""
        if not self.calls:
            return "  (trajectory is empty)"
        lines = []
        for call in self.calls:
            args = _short(call.args)
            suffix = "" if call.error is None else f" -> ERROR {call.error}"
            lines.append(f"  {call.seq}. {call.tool_name}({args}){suffix}")
        return "\n".join(lines)

    # -- assertions --------------------------------------------------------

    def tools_called(
        self,
        expected: Sequence[str],
        mode: str = "sequence",
    ) -> "Trajectory":
        """Assert which tools were called and in what order.

        Args:
            expected: Ordered tool names.
            mode: ``"sequence"`` requires the full call list to equal
                ``expected`` exactly; ``"subsequence"`` requires ``expected`` to
                appear in order, allowing other calls in between.
        """
        expected = list(expected)
        actual = self.tool_sequence
        if mode == "sequence":
            if actual != expected:
                self._fail(
                    f"expected tool sequence {expected}, got {actual}"
                )
        elif mode == "subsequence":
            if not _is_subsequence(expected, actual):
                self._fail(
                    f"expected {expected} as an ordered subsequence of {actual}"
                )
        else:
            raise ValueError(f"unknown mode {mode!r}; use 'sequence' or 'subsequence'")
        return self

    def tool_called_with(self, name: str, matcher: ArgMatcher) -> "Trajectory":
        """Assert at least one call to ``name`` whose args satisfy ``matcher``.

        ``matcher`` may be a callable ``(args) -> bool`` or a dict of required
        key/value pairs (a subset match).
        """
        predicate = _as_predicate(matcher)
        for call in self.calls:
            if call.tool_name == name and predicate(call.args):
                return self
        self._fail(
            f"no call to {name!r} matched the given argument matcher"
        )
        return self

    def max_steps(self, n: int) -> "Trajectory":
        """Assert the trajectory has at most ``n`` calls (a step budget)."""
        if len(self.calls) > n:
            self._fail(
                f"trajectory has {len(self.calls)} steps, exceeding budget of {n}"
            )
        return self

    def no_unexpected_tools(self, allowlist: Sequence[str]) -> "Trajectory":
        """Assert every called tool is in ``allowlist``."""
        allowed = set(allowlist)
        unexpected = sorted({c.tool_name for c in self.calls} - allowed)
        if unexpected:
            self._fail(
                f"unexpected tools called: {unexpected}; allowlist={sorted(allowed)}"
            )
        return self

    def tool_call_count(self, name: str, n: int) -> "Trajectory":
        """Assert ``name`` was called exactly ``n`` times."""
        count = sum(1 for c in self.calls if c.tool_name == name)
        if count != n:
            self._fail(
                f"expected {name!r} to be called {n} time(s), got {count}"
            )
        return self

    # -- internal ----------------------------------------------------------

    def _fail(self, message: str) -> None:
        raise AssertionError(
            f"{message}\ntrajectory ({len(self.calls)} steps):\n{self.summary()}"
        )


def assert_trajectory(cassette: Union[Cassette, str]) -> Trajectory:
    """Return a :class:`Trajectory` for a cassette object or a cassette path."""
    if isinstance(cassette, str):
        cassette = load(cassette)
    return Trajectory(cassette)


def _as_predicate(matcher: ArgMatcher) -> Callable[[Dict[str, Any]], bool]:
    if callable(matcher):
        return matcher
    required = dict(matcher)

    def _match(args: Dict[str, Any]) -> bool:
        return all(args.get(k) == v for k, v in required.items())

    return _match


def _is_subsequence(needle: List[str], haystack: List[str]) -> bool:
    it = iter(haystack)
    return all(item in it for item in needle)


def _short(args: Dict[str, Any], limit: int = 80) -> str:
    import json

    text = json.dumps(args, ensure_ascii=False, sort_keys=True)
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text
